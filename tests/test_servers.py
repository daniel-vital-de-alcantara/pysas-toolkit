from pathlib import Path
import io
import tempfile
import unittest
from unittest.mock import Mock, patch

import pysas_ui as ui
import ui_servers as servers

TOKEN = '123456abcdef'


def catalog_log(records, token=TOKEN):
    """Model SAS's 40-byte, space-padded $HEX80 chunks, including UTF-8 splits."""
    prefix = 'PSC' + token + '|'
    lines = ['NOTE: ordinary SAS output', prefix + 'BEGIN']
    for kind, values in records:
        lines.append(prefix + 'R|' + kind)
        for field, value in values.items():
            raw = str(value).encode('utf-8')
            for offset in range(0, len(raw), 40):
                lines.append(prefix + 'V|' + field + '|' + raw[offset:offset+40].ljust(40, b' ').hex().upper())
        lines.append(prefix + 'E')
    lines.append(prefix + 'DONE')
    return '\n'.join(lines)


RECORDS = [
    ('library', dict(libname='DATA', engine='V9', path='/server/café')),
    ('library', dict(libname='DATA', engine='V9', path='/server/archive')),
    ('library', dict(libname='EMPTY', engine='V9', path='/empty')),
    ('table', dict(libname='DATA', name='Claims', kind='DATA', label='x'*39+'é|\n年度'*20,
                   bytes=1048576, rows=120, columns=4, created='2026-09-01T12:30:00', modified='2026-09-24T10:00:00')),
    ('table', dict(libname='DATA', name='Unknown', kind='DATA', bytes='.', rows=-1, columns=2, created='.', modified='.')),
    ('table', dict(libname='DATA', name='View', kind='VIEW', bytes=0, rows=0, columns=2)),
]


class CatalogTests(unittest.TestCase):
    def test_unicode_chunks_paths_unknown_sizes_and_view_totals(self):
        log = catalog_log(RECORDS + [RECORDS[3]])
        self.assertLessEqual(max(map(len, log.splitlines())), 132)
        result = servers.parse_catalog(log, TOKEN)
        data, empty = result['libraries']
        self.assertEqual(data['paths'], ['/server/café', '/server/archive'])
        self.assertEqual((data['tables'], data['views'], data['known_bytes'], data['unknown_sizes']), (2, 1, 1048576, 1))
        self.assertEqual(empty['tables'], 0)
        claims, unknown, view = result['tables']
        self.assertEqual(claims['label'], RECORDS[3][1]['label'])
        self.assertEqual(claims['created'], '2026-09-01T12:30:00')
        self.assertIsNone(unknown['bytes']); self.assertIsNone(unknown['rows']); self.assertIsNone(unknown['created'])
        self.assertIsNone(view['bytes']); self.assertIsNone(view['rows'])

    def test_partial_corrupt_and_unrelated_logs_do_not_become_snapshots(self):
        log = catalog_log(RECORDS)
        for text in (log.rsplit('\n', 1)[0], log.replace('DONE', 'R|table'), log.replace('R|library', 'R|invalid'), log.replace('|V|libname|', '|V|libname|Z'), '1 put "PSC'+TOKEN+'|BEGIN";'):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                servers.parse_catalog(text, TOKEN)
        with self.assertRaises(ValueError):
            servers.parse_catalog(log, 'abcdef123456')
        self.assertEqual(servers.parse_catalog(catalog_log([]), TOKEN), dict(libraries=[], tables=[], issues=[], partial=False))

    def test_failed_members_and_libraries_keep_readable_tables_before_and_after(self):
        issues = [
            ('issue', dict(scope='table', libname='DATA', name='Locked', message='Access denied')),
            ('issue', dict(scope='library', libname='OFFLINE', message='Library unavailable')),
        ]
        result = servers.parse_catalog(catalog_log(RECORDS[:4]+issues+RECORDS[4:]), TOKEN)
        self.assertTrue(result['partial'])
        self.assertEqual([t['name'] for t in result['tables']], ['Claims', 'Unknown', 'View'])
        data, empty, offline = result['libraries']
        self.assertEqual((data['known_bytes'], data['skipped_members'], data['incomplete']), (1048576, 1, True))
        self.assertFalse(empty['incomplete'])
        self.assertTrue(offline['incomplete'])
        self.assertEqual(offline['known_bytes'], 0)
        self.assertEqual(len(result['issues']), 2)

    def test_partial_log_keeps_only_complete_records_and_recovers_after_corruption(self):
        prefix = 'PSC'+TOKEN+'|'
        log = catalog_log(RECORDS[:4]).rsplit('\n', 1)[0]+'\n'+prefix+'R|table\n'+prefix+'V|name|00'
        result = servers.parse_catalog(log, TOKEN, allow_partial=True)
        self.assertEqual(len(result['tables']), 1)
        self.assertTrue(result['partial'])
        self.assertTrue(all(l['incomplete'] for l in result['libraries']))
        damaged = catalog_log(RECORDS).replace('R|library', 'R|invalid', 1)
        result = servers.parse_catalog(damaged, TOKEN, allow_partial=True)
        self.assertEqual(len(result['tables']), 3)
        self.assertEqual(result['tables'][0]['label'], RECORDS[3][1]['label'])
        for log in ('no catalog', prefix+'BEGIN\n'+prefix+'R|table', catalog_log([('issue', dict(scope='library', libname='OFFLINE', message='Unavailable'))])):
            with self.assertRaises(ValueError): servers.parse_catalog(log, TOKEN, allow_partial=True)

    def test_filters_are_validated_and_script_only_queries_metadata(self):
        self.assertEqual(servers.library_filter(' data,Other DATA\n_lib'), ['DATA', 'OTHER', '_LIB'])
        for value in ("DATA'); delete", 'toolongname', '123', 'WORK', 'SASHELP'):
            with self.assertRaises(ValueError): servers.library_filter(value)
        code = servers.catalog_code(TOKEN, ['DATA'])
        self.assertIn("where libname in ('DATA')", code)
        self.assertIn('from dictionary.tables', code)
        self.assertIn('from dictionary.libnames', code)
        self.assertIn('from dictionary.members', code)
        self.assertIn('where libname="&_psc_libhex"x and memname="&_psc_memhex"x', code)
        self.assertIn('nosyntaxcheck noerrorabend', code)
        self.assertIn('set work._psc_members point=_psc_point;', code)
        self.assertIn('set work._psc_librefs point=_psc_point;', code)
        self.assertLess(code.index('data work._psc_one;'), code.index('insert into work._psc_one'))
        self.assertIn('%_psc_issue(table,', code)
        self.assertIn('%_psc_issue(library,', code)
        self.assertNotIn('select *', code)
        self.assertNotIn('proc export', code)
        self.assertIn("getoption('encoding'), 'utf-8'", code)
        self.assertIn("libname not in ('WORK','SASHELP','SASUSER')", servers.catalog_code(TOKEN, []))
        with self.assertRaises(ValueError): servers.catalog_code("';bad;", [])


class ServerWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root/'pysas.py').write_text('# engine')
        (self.root/'connection.egp').write_text('template')
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        self.app.processes.clear()
        self.app.awake.close()
        self.temp.cleanup()

    def refresh(self, records=RECORDS, rc=0, truncated=False, no_catalog=False, task_status=None):
        process = Mock(stdin=None); process.wait.return_value = rc
        # Only skip platform gating: use the real launch, arguments are covered
        # by the real Windows/cscript integration test in test_scheduler_parity.
        with patch.object(self.app, 'arguments', return_value=('server-refresh', ['runner','run','--no-notify'])), patch.object(ui.subprocess, 'Popen', return_value=process), patch.object(ui.threading, 'Thread'):
            identifier = self.app.launch(dict(action='server-refresh', template='connection.egp', label='Production', libraries='DATA'))['id']
        item = self.app.commands[identifier]
        folder = self.root/'runner/runs'/identifier
        (folder/'logs').mkdir(parents=True)
        text = catalog_log(records, item['server']['token'])
        if truncated: text = text.rsplit('\n', 1)[0]
        if no_catalog: text = 'ERROR: No server connection'
        (folder/'logs/catalog.log').write_text(text, encoding='utf-8')
        item['tasks']['source'] = dict(status=task_status or ('SUCCESS' if rc == 0 else 'FAILED'), path=self.app.relative(folder))
        self.app.complete_worker(identifier, process)
        return identifier

    def test_completed_refresh_retains_script_metadata_and_old_success_on_failure(self):
        identifier = self.refresh()
        item = self.app.commands[identifier]
        self.assertEqual(item['status'], 'SUCCESS')
        source = Path(item['args'][-1])
        self.assertTrue(source.is_file())
        self.assertIn('dictionary.tables', source.read_text())
        catalog = self.app.server_catalog(identifier)
        self.assertEqual(catalog['label'], 'Production')
        self.assertEqual(len(catalog['tables']), 3)
        for kwargs in (dict(rc=1, no_catalog=True), dict(records=[], truncated=True)):
            failed = self.refresh(**kwargs)
            self.assertEqual(self.app.commands[failed]['status'], 'FAILED')
            with self.assertRaises(ValueError): self.app.server_catalog(failed)
            self.assertEqual(self.app.server_catalog(identifier), catalog)
        snapshots = self.app.server_snapshots()
        self.assertEqual(len(snapshots), 3)
        self.assertNotIn('tables', snapshots[0])
        self.assertEqual(ui.Workbench(self.root).server_catalog(identifier), catalog)

    def test_refresh_with_sas_errors_retains_catalog_and_original_task_failure(self):
        issue = ('issue', dict(scope='table', libname='DATA', name='Locked', message='Access denied'))
        for options in (dict(rc=1, task_status='SAS_ERROR'), dict(rc=1), dict(rc=0), dict(truncated=True)):
            with self.subTest(options=options):
                identifier = self.refresh(RECORDS[:4]+[issue]+RECORDS[4:], **options)
                item = self.app.commands[identifier]
                self.assertEqual(item['status'], 'PARTIAL')
                self.assertEqual(item['exit_code'], options.get('rc', 0))
                self.assertTrue(item['server']['partial'])
                self.assertEqual(item['tasks']['source']['status'], options.get('task_status', 'FAILED' if options.get('rc') else 'SUCCESS'))
                catalog = self.app.server_catalog(identifier)
                self.assertEqual(len(catalog['tables']), 3)
                self.assertIn('Locked', [issue['name'] for issue in catalog['issues']])
                self.assertTrue(catalog['partial'])
                self.assertIn('Partial snapshot saved', item['message'])

    def test_saved_data_round_trip_remaps_catalog_paths_and_preserves_snapshot(self):
        identifier = self.refresh(truncated=True)
        expected = self.app.server_catalog(identifier)
        stream, _ = self.app.backup()
        with stream: data = stream.read()
        self.app.backup(io.BytesIO(data), len(data))
        imported = next(c for c in self.app.commands.values() if c['id'] != identifier)
        self.assertNotEqual(imported['server']['snapshot'], self.app.commands[identifier]['server']['snapshot'])
        self.assertEqual(self.app.server_catalog(imported['id']), expected)
        with self.assertRaises(ValueError): self.app.server_catalog('../outside')
        imported['server']['snapshot'] = str(self.root/'pysas.py')
        with self.assertRaises(ValueError): self.app.server_catalog(imported['id'])


if __name__ == '__main__': unittest.main()

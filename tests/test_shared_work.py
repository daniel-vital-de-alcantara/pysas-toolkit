import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import pysas
import pysas_ui as ui
import ui_data
import ui_servers


class SharedWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root/'pysas.py').write_text('# engine')
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        self.app.awake.close()
        self.temp.cleanup()

    def test_sas_literal_and_order_and_unavailable_directory_guard(self):
        job = self.root/'job.sas'; job.write_text('target;')
        init = self.root/'_lib.sas'; init.write_text('initialization;')
        cases = self.root/'cases.sas'; cases.write_text('parameters;')
        with patch.dict(os.environ, {'PYSAS_SHARED_WORK_PATH': "/server/a'b&c%macro", 'PYSAS_SHARED_WORK_LIBREF': 'vdi'}):
            code = pysas.compose_sas(job, self.root, init, parameters=cases)
        self.assertIn("libname('VDI', '/server/a''b&c%macro')", code)
        self.assertLess(code.index('options user=VDI;'), code.index('initialization;'))
        self.assertLess(code.index('initialization;'), code.rindex('options user=VDI;'))
        self.assertLess(code.rindex('options user=VDI;'), code.index('parameters;'))
        self.assertLess(code.index('parameters;'), code.index('target;'))
        self.assertIn("if libname('VDI',", code)
        self.assertIn('abort abend;', code)
        with patch.dict(os.environ, {'PYSAS_SHARED_WORK_PATH': ''}):
            self.assertNotIn('SHARED_WORK', pysas.compose_sas(job, self.root, init))

    def test_validation_and_persistence(self):
        for values in ({'enabled': True}, {'libref': 'WORK'}, {'libref': 'a;run'}, {'path': 'a\nb'}):
            with self.assertRaises(ValueError): self.app.update_shared_work(values)
        saved = self.app.update_shared_work(dict(enabled=True, path='/remote/work', libref='vdi'))
        self.assertEqual(ui.Workbench(self.root).shared_work(), saved)

    def test_every_execution_launch_gets_snapshot_and_disabled_drops_inherited_config(self):
        self.app.update_shared_work(dict(enabled=True, path='/remote/work', libref='VDI'))
        with patch.object(ui.subprocess, 'Popen', return_value=Mock()) as spawn, patch.object(ui.threading, 'Thread'):
            for action in ['run', 'watch', 'schedule']:
                with patch.object(self.app, 'arguments', return_value=(action, [action])):
                    identifier = self.app.launch({'action': action})['id']
                self.assertEqual(spawn.call_args.kwargs['env']['PYSAS_SHARED_WORK_PATH'], '/remote/work')
                self.assertEqual(self.app.commands[identifier]['shared_work']['libref'], 'VDI')
            self.app.update_shared_work(dict(enabled=False, path='/remote/work'))
            with patch.dict(os.environ, {'PYSAS_SHARED_WORK_PATH': '/stale'}), patch.object(self.app, 'arguments', return_value=('run', ['run'])):
                self.app.launch({'action': 'run'})
            self.assertNotIn('PYSAS_SHARED_WORK_PATH', spawn.call_args.kwargs['env'])
        self.app.processes.clear()

    def test_config_backup_keeps_path_but_requires_reenable_for_new_session(self):
        self.app.update_shared_work(dict(enabled=True, path='/server/work'))
        stream, _ = ui_data.export_backup(self.app, configs_only=True)
        with stream: raw = stream.read()
        target = self.root/'new'; target.mkdir(); (target/'pysas.py').write_text('# engine')
        app = ui.Workbench(target)
        app.backup(io.BytesIO(raw), len(raw))
        self.assertEqual(app.shared_work(), dict(enabled=False, path='/server/work', libref='VDI'))

    def test_discovery_only_does_not_request_table_metadata(self):
        code = ui_servers.catalog_code('123456abcdef', [], libraries_only=True)
        self.assertIn('dictionary.libnames', code)
        self.assertNotIn('dictionary.tables', code)
        self.assertNotIn('dictionary.members', code)
        self.assertIn('|DONE', code)

    def test_automatic_template_uses_last_successful_connection_or_only_input(self):
        first = self.root/'one.egp'; first.touch()
        self.assertEqual(self.app.server_template(), str(first))
        second = self.root/'two.egp'; second.touch()
        with self.assertRaisesRegex(ValueError, 'Choose a connection once'): self.app.server_template()
        self.app.commands['ok'] = dict(status='SUCCESS', started=1, args=['--template', str(second)])
        self.app.commands['bad'] = dict(status='FAILED', started=2, args=['--template', str(first)])
        self.assertEqual(self.app.server_template(), str(second))
        self.assertEqual(self.app.server_template(str(first)), str(first))


class RemainingTests(unittest.TestCase):
    def samples(self, **seconds):
        return [{'key': ui_data.signature({'name': name}), 'seconds': value, 'time': 1} for name, value in seconds.items()]

    def command(self, tasks, workers=2, action='schedule', status='RUNNING'):
        return dict(action=action, status=status, args=['--workers', str(workers)], tasks={t['key']:t for t in tasks})

    def task(self, key, status='PENDING', **values):
        return dict(key=key, name=key, status=status, **values)

    def test_counts_remaining_time_dependencies_and_skipped_barriers(self):
        tasks = [self.task('a', 'RUNNING', started=80), self.task('skip', skip=True, depends_on=['a']), self.task('c', depends_on=['skip']), self.task('done', 'SUCCESS')]
        value = ui_data.remaining_work([self.command(tasks)], [], self.samples(a=100,c=50,done=900), 100)
        self.assertEqual(value['seconds'], 130)
        self.assertEqual(value['unknown'], 0)

    def test_parallel_commands_and_slots_not_sum_of_all_durations(self):
        one = self.command([self.task('a','RUNNING',started=90), self.task('b','RUNNING',started=90), self.task('c')])
        two = self.command([self.task('d','RUNNING',started=90)], workers=1)
        value = ui_data.remaining_work([one,two], [], self.samples(a=30,b=80,c=50,d=100), 100)
        self.assertEqual(value['seconds'], 90)

    def test_watcher_queue_unknown_and_overrun(self):
        watch = self.command([self.task('a','RUNNING',started=90)], workers=1, action='watch')
        value = ui_data.remaining_work([watch], ['a','b'], self.samples(a=30,b=50), 100)
        self.assertEqual(value['seconds'], 70)
        value = ui_data.remaining_work([watch], ['unknown'], self.samples(a=30), 100)
        self.assertEqual((value['seconds'],value['unknown']), (20,1))
        value = ui_data.remaining_work([watch], [], self.samples(a=5), 100)
        self.assertIsNone(value['seconds'])
        self.assertEqual(value['unknown'], 1)

    def test_stopping_excludes_pending_and_idle_watcher_is_not_running_files(self):
        command = self.command([self.task('a','RUNNING',started=90),self.task('b')], status='STOPPING')
        value = ui_data.remaining_work([command], [], self.samples(a=30,b=900), 100)
        self.assertEqual(value['seconds'], 20)
        idle = ui_data.remaining_work([self.command([], action='watch')], [], [], 100)
        self.assertFalse(idle['active'])

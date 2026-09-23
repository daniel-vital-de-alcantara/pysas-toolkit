from pathlib import Path
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch, Mock
import pysas
import pysas_ui as ui
import ui_parameters as params
from ui_worker import load_engine

ROOT = Path(__file__).resolve().parents[1]


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'pysas.py').write_text('# test workspace')
        self.app = ui.Workbench(self.root)
        self.engine = load_engine(ROOT / 'pysas.py')
        self.engine.ROOT_DIR = self.root

    def tearDown(self):
        self.app.awake.close()
        self.temp.cleanup()

    def test_saved_lists_revision_checks_and_portable_names(self):
        saved = self.app.save_parameters(dict(name='_cases.sas', text='%let city = café;\r\n'))
        self.assertEqual(saved['text'], '%let city = café;\n')
        self.assertEqual(self.app.parameter_settings()['last'], '_cases.sas')
        self.assertTrue(self.app.parameter_settings()['enabled'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.app.save_parameters(dict(name='_cases.sas', text='changed'))
        updated = self.app.save_parameters(dict(name='_CASES.sas', text='new;', revision=saved['revision']))
        self.assertEqual(updated['name'], '_cases.sas')
        with self.assertRaises(ValueError):
            self.app.save_parameters(dict(name='_cases.sas', text='stale;', revision=saved['revision']))
        self.assertEqual(params.load_parameters(self.app.storage, '_cases.sas')['text'], 'new;')
        self.app.save_parameters(dict(name='other.sas', text='other;'))
        self.app.select_parameters('_cases.sas')
        self.assertEqual(ui.Workbench(self.root).parameter_settings()['last'], '_cases.sas')
        self.assertEqual(self.engine.init_files(folder=self.root), [])
        for name in ('../_cases.sas', 'folder\\_cases.sas', 'CON.sas', 'a.py', '.secret.sas'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.app.save_parameters(dict(name=name, text='x'))
        with self.assertRaises(ValueError):
            self.app.save_parameters(dict(name='_large.sas', text='x' * (params.PARAMETER_LIMIT + 1)))

    def test_engine_order_skips_duplicate_init_and_retains_exact_parameter_copy(self):
        lib = self.root / '_libs.sas'; lib.write_text('library_code;')
        cases = self.root / '_cases.sas'; cases.write_text('%let ids=123,456;', encoding='utf-8')
        job = self.root / 'extract.sas'; job.write_text('extraction_code;')
        submitted = []
        def execute(mode, project, source, name, first, last, run_dir, tables):
            submitted.append(source.read_text(encoding='utf-8'))
            cases.write_text('%let ids=CHANGED;')
            return 0, ''
        with patch.object(self.engine, 'execute_eg', execute), contextlib.redirect_stdout(io.StringIO()):
            result = self.engine.run_job(job, self.root/'project.egp', False, None, False, parameters=cases)
        code = submitted[0]
        self.assertLess(code.index('library_code;'), code.index('%let ids=123,456;'))
        self.assertLess(code.index('%let ids=123,456;'), code.index('extraction_code;'))
        self.assertEqual(code.count('%let ids=123,456;'), 1)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertFalse((result['run_dir'] / '_submitted.sas').exists())
        self.assertEqual((result['run_dir'] / 'parameters/_cases.sas').read_text(), '%let ids=123,456;')

    def test_override_initialization_still_precedes_parameters_and_no_option_is_unchanged(self):
        job = self.root/'job.sas'; job.write_text('job;')
        override = self.root/'init.sas'; override.write_text('override;')
        cases = self.root/'cases.sas'; cases.write_text('parameters;')
        text = self.engine.compose_sas(job, self.root/'results', override, parameters=cases)
        self.assertLess(text.index('override;'), text.index('parameters;'))
        self.assertLess(text.index('parameters;'), text.index('job;'))
        self.assertNotIn('PYSAS_PARAMETERS_START', self.engine.compose_sas(job, self.root/'results', override))
        with self.assertRaises(ValueError):
            self.engine.run_job(job, self.root/'p.egp', False, override, False, parameters=override)

    def test_launch_snapshots_unsaved_edits_and_independent_overlapping_runs(self):
        self.app.save_parameters(dict(name='_cases.sas', text='%let ids=SAVED;'))
        process = Mock()
        with patch.object(self.app, 'arguments', side_effect=lambda _: ('run', ['runner', 'run', 'extract.sas'])), patch.object(ui.subprocess, 'Popen', return_value=process), patch.object(ui.threading, 'Thread'):
            identifiers = []
            for text in ('%let ids=FIRST;', '%let ids=SECOND;'):
                identifiers.append(self.app.launch(dict(action='run', use_parameters=True, parameters_name='_cases.sas', parameters_text=text))['id'])
            disabled = self.app.launch(dict(action='run', use_parameters=False, parameters_text='must_not_run;'))['id']
        for identifier, expected in zip(identifiers, ('%let ids=FIRST;', '%let ids=SECOND;')):
            item = self.app.commands[identifier]
            snapshot = self.root / item['parameters']['path']
            self.assertEqual(snapshot.read_text(), expected)
            self.assertEqual(Path(item['args'][item['args'].index('--parameters')+1]), snapshot)
        self.assertNotIn('--parameters', self.app.commands[disabled]['args'])
        self.assertEqual(params.load_parameters(self.app.storage, '_cases.sas')['text'], '%let ids=SAVED;')
        self.assertFalse(self.app.parameter_settings()['enabled'])
        self.app.processes.clear()

    def test_standalone_cli_parameter_flag_reaches_run_job(self):
        source = self.root/'job.sas'; source.write_text('job;')
        parameter = self.root/'cases.sas'; parameter.write_text('parameters;')
        project = self.root/'p.egp'; project.write_text('project')
        with patch.object(self.engine, 'run_job', return_value=dict(status='SUCCESS', run_dir=self.root)) as job, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.main(['runner','run',str(source),'--template',str(project),'--parameters',str(parameter),'--no-notify']), 0)
        self.assertEqual(job.call_args.kwargs['parameters'], parameter)

    def test_backup_restores_parameter_lists_and_snapshot_paths_without_overwrite(self):
        self.app.save_parameters(dict(name='_cases.sas', text='first;'))
        snapshot = self.app.storage/'artifacts/original/_cases.sas'
        snapshot.parent.mkdir(parents=True); snapshot.write_text('snapshot;')
        self.app.commands['original'] = dict(id='original',action='run',args=[],name='job',status='SUCCESS',started=10,tasks={},parameters={'name':'_cases.sas','path':self.app.relative(snapshot)})
        stream, _ = self.app.backup()
        with stream: data = stream.read()
        saved = params.load_parameters(self.app.storage, '_cases.sas')
        self.app.save_parameters({**saved, 'text': 'current;'})
        result = self.app.backup(io.BytesIO(data), len(data))
        self.assertEqual(result['parameters'], 1)
        self.assertEqual(params.load_parameters(self.app.storage, '_cases.sas')['text'], 'current;')
        last = self.app.parameter_settings()['last']
        self.assertNotEqual(last, '_cases.sas')
        self.assertEqual(params.load_parameters(self.app.storage, last)['text'], 'first;')
        imported = next(c for c in self.app.commands.values() if c['id'] != 'original')
        self.assertNotEqual(imported['parameters']['path'], self.app.relative(snapshot))
        self.assertEqual((self.root/imported['parameters']['path']).read_text(), 'snapshot;')


if __name__ == '__main__': unittest.main()

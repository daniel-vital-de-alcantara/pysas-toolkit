from pathlib import Path
import argparse
import contextlib
import io
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
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
        self.assertEqual(params.load_parameters(self.app.settings, '_cases.sas')['text'], 'new;')
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
        self.assertEqual((result['run_dir'] / '_submitted.sas').read_text(encoding='utf-8'), code)
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
        (self.root/'extract.sas').write_text('target;')
        process = Mock()
        with patch.object(self.app, 'arguments', side_effect=lambda _: ('run', ['runner', 'run', 'extract.sas'])), patch.object(ui.subprocess, 'Popen', return_value=process), patch.object(ui.threading, 'Thread'):
            identifiers = []
            for text in ('%let ids=FIRST;', '%let ids=SECOND;'):
                identifiers.append(self.app.launch(dict(action='run', program='extract.sas', use_parameters=True, parameters_name='_cases.sas', parameters_text=text))['id'])
            disabled = self.app.launch(dict(action='run', program='extract.sas', use_parameters=False, parameters_text='must_not_run;'))['id']
        for identifier, expected in zip(identifiers, ('%let ids=FIRST;', '%let ids=SECOND;')):
            item = self.app.commands[identifier]
            snapshot = self.app.resolve(item['parameters']['path'])
            self.assertEqual(snapshot.read_text(), expected)
            self.assertEqual(Path(item['args'][item['args'].index('--parameters')+1]), snapshot)
        self.assertNotIn('--parameters', self.app.commands[disabled]['args'])
        self.assertEqual(params.load_parameters(self.app.settings, '_cases.sas')['text'], '%let ids=SAVED;')
        self.assertFalse(self.app.parameter_settings()['enabled'])
        self.app.processes.clear()

    def test_standalone_cli_parameter_flag_reaches_run_job(self):
        source = self.root/'job.sas'; source.write_text('job;')
        parameter = self.root/'cases.sas'; parameter.write_text('parameters;')
        project = self.root/'p.egp'; project.write_text('project')
        with patch.object(self.engine, 'run_job', return_value=dict(status='SUCCESS', run_dir=self.root)) as job, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.main(['runner','run',str(source),'--template',str(project),'--parameters',str(parameter),'--no-notify']), 0)
        self.assertEqual(job.call_args.kwargs['parameters'], parameter)

    def test_ui_single_file_uses_shared_and_inbox_initialization_before_parameters(self):
        shared=self.root/'a-shared';shared.mkdir();inbox=self.root/'z-inbox';inbox.mkdir()
        (shared/'_20_macros.SAS').write_text('shared_macro_token;',encoding='utf-8')
        (inbox/'_10_libs.sAs').write_text('inbox_library_token;',encoding='utf-8')
        source=self.root/'extract.sas';source.write_text('target_token;',encoding='utf-8')
        project=self.root/'project.egp';project.write_text('template',encoding='utf-8')
        parameters=self.app.settings/'parameters/cases.sas';parameters.parent.mkdir();parameters.write_text('%let ids=123;',encoding='utf-8')
        self.app.update_folders({'init':str(shared),'inbox':str(inbox)})
        with patch('pysas_ui.os',SimpleNamespace(name='nt')):
            _,arguments=self.app.arguments(dict(action='run',program=str(source),template=str(project)))
        captured=[]
        def execute(*args,**kwargs):captured.append(args[2].read_text(encoding='utf-8'));return 0,''
        for use_parameters in (False,True):
            with self.subTest(parameters=use_parameters),patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()) as output:
                flags=['--parameters',str(parameters)] if use_parameters else []
                self.assertEqual(self.engine.main(arguments+flags),0)
                code=captured[-1]
                self.assertLess(code.index('inbox_library_token;'),code.index('shared_macro_token;'))
                self.assertLess(code.index('shared_macro_token;'),code.index('target_token;'))
                if use_parameters:
                    self.assertLess(code.index('shared_macro_token;'),code.index('%let ids=123;'))
                    self.assertLess(code.index('%let ids=123;'),code.index('target_token;'))
                    self.assertIn('Appended parameters: '+str(parameters),output.getvalue())
                self.assertIn('Appended shared initialization: '+str(inbox/'_10_libs.sAs'),output.getvalue())
        self.assertTrue((inbox/'_10_libs.sAs').exists())
        self.assertFalse((self.root/'runner/claimed').exists())
        with patch.object(self.app,'cached_listing',side_effect=lambda key,load,*args:load()):
            listed=self.app.state()['initialization_files']
        self.assertEqual(listed,[str(inbox/'_10_libs.sAs'),str(shared/'_20_macros.SAS')])

    def test_single_file_inbox_can_supply_parameters_once_and_override_still_replaces_shared(self):
        shared=self.root/'shared';shared.mkdir();inbox=self.root/'inbox';inbox.mkdir()
        (shared/'_libs.sas').write_text('library_token;',encoding='utf-8')
        cases=inbox/'_cases.SAS';cases.write_text('%let ids=selected;',encoding='utf-8')
        job=self.root/'job.sas';job.write_text('target_token;',encoding='utf-8')
        override=self.root/'override.sas';override.write_text('override_token;',encoding='utf-8')
        project=self.root/'project.egp';project.write_text('template',encoding='utf-8')
        captured=[]
        def execute(*args,**kwargs):captured.append(args[2].read_text(encoding='utf-8'));return 0,''
        arguments=['runner','run',str(job),'--template',str(project),'--init-dir',str(shared),'--inbox',str(inbox),'--parameters',str(cases),'--no-notify']
        with patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.main(arguments),0)
            self.assertEqual(self.engine.main(arguments+['--lib',str(override)]),0)
        self.assertEqual(captured[0].count('%let ids=selected;'),1)
        self.assertLess(captured[0].index('library_token;'),captured[0].index('%let ids=selected;'))
        self.assertNotIn('library_token;',captured[1]);self.assertEqual(captured[1].count('%let ids=selected;'),1)
        self.assertLess(captured[1].index('override_token;'),captured[1].index('%let ids=selected;'))

    def test_cli_without_explicit_inbox_keeps_existing_initialization_roots(self):
        source=self.root/'job.sas';source.write_text('target_token;',encoding='utf-8')
        project=self.root/'project.egp';project.write_text('template',encoding='utf-8')
        inbox=self.root/'runner/inbox';(inbox/'_extra.sas').write_text('inbox_token;',encoding='utf-8')
        (self.root/'_libs.sas').write_text('root_token;',encoding='utf-8')
        captured=[]
        def execute(*args,**kwargs):captured.append(args[2].read_text(encoding='utf-8'));return 0,''
        with patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.main(['runner','run',str(source),'--template',str(project),'--no-notify']),0)
        self.assertIn('root_token;',captured[0]);self.assertNotIn('inbox_token;',captured[0])

    def test_effective_override_preview_matches_worker_submission_and_full_log(self):
        source=self.root/'job.sas';source.write_text('target_token;',encoding='utf-8')
        (self.root/'_auto.sas').write_text('must_not_run;',encoding='utf-8')
        override=self.root/'runner/inbox/_override.SAS';override.write_text('override_token;',encoding='cp1252')
        project=self.root/'p.egp';project.write_text('template',encoding='utf-8')
        captured=[]
        def execute(mode,project,submitted,name,first,last,folder,tables):
            captured.append(submitted.read_text(encoding='utf-8'))
            (folder/'logs').mkdir()
            (folder/'logs/job.log').write_bytes('NOTE: pre\xe7o\nWARNING: sample warning\n'.encode('cp1252'))
            (folder/'console.txt').write_text('PYSAS_STAGE|executing|Running job\n',encoding='utf-8')
            return 0,'Running job'
        for enabled in (False,True):
            data=dict(action='run',program=str(source),template=str(project),initialization_mode='override',lib=str(override),use_parameters=enabled,parameters_name='_cases.sas',parameters_text='%let ids=edited;')
            plan=self.app.run_plan(data)
            self.assertEqual([f['role'] for f in plan['files']],['initialization']+(['parameters'] if enabled else [])+['program'])
            self.assertEqual(plan['files'][0]['path'],str(override))
            self.assertIn(self.app.relative(override),self.app.inventory())
            with patch('pysas_ui.os',SimpleNamespace(name='nt')):
                _,arguments=self.app.arguments(data)
            if enabled:
                snapshot=self.app.storage/'_cases.sas';snapshot.write_text(data['parameters_text'],encoding='utf-8')
                arguments+=['--parameters',str(snapshot)]
            with patch.object(self.engine,'execute_eg',execute),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.engine.main(arguments+['--expected-plan',plan['revision']]),0)
            folder=max((self.root/'runner/runs').iterdir(),key=lambda p:p.stat().st_mtime_ns)
            saved=json.loads((folder/'execution-plan.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['revision'],plan['revision'])
            code=captured[-1];self.assertNotIn('must_not_run;',code)
            self.assertLess(code.index('override_token;'),code.index('target_token;'))
            if enabled:self.assertLess(code.index('override_token;'),code.index('%let ids=edited;'));self.assertLess(code.index('%let ids=edited;'),code.index('target_token;'))
            log=(folder/'run.log').read_text(encoding='utf-8')
            for expected in ('Initialization override: '+str(override),'1. initialization: '+str(override),'Appended shared initialization: '+str(override),'WARNING: sample warning','preço','Running job'):
                self.assertIn(expected,log)
            self.assertNotIn('PYSAS_STAGE|',log)
            self.assertEqual((folder/'initialization/01___override.SAS').read_text(encoding='utf-8'),'override_token;')
            self.assertTrue((folder/'_submitted.sas').is_file())
            self.assertIn('%put NOTE: PYSAS_FILE_START|1|initialization;',code)
            self.assertIn('%put NOTE: PYSAS_FILE_END|1|initialization;',code)

    def test_shared_mode_can_ignore_saved_override_and_missing_explicit_selection_is_rejected(self):
        source=self.root/'job.sas';source.write_text('target;')
        (self.root/'_auto.sas').write_text('auto;')
        override=self.root/'override.sas';override.write_text('override;')
        ui.atomic_json(self.app.config('preferences.json'),{'default_lib':str(override)})
        data=dict(action='run',program=str(source))
        self.assertEqual(self.app.run_plan(data)['override'],str(override))
        self.assertEqual(self.app.run_plan({**data,'initialization_mode':'shared'})['files'][0]['name'],'_auto.sas')
        with self.assertRaisesRegex(ValueError,'Select the initialization override'):
            self.app.run_plan({**data,'initialization_mode':'override','lib':''})

    def test_real_ui_worker_validates_override_and_retains_full_log_with_parameters(self):
        stub='''
def execute_eg(mode, project, submitted, name, first, last, run_dir, tables):
    (run_dir/'code').mkdir()
    (run_dir/'logs').mkdir()
    (run_dir/'code/actual.sas').write_text(submitted.read_text(encoding='utf-8'),encoding='utf-8')
    (run_dir/'logs/actual.log').write_text('NOTE: mock SAS output\\nWARNING: check sample\\n',encoding='utf-8')
    (run_dir/'console.txt').write_text('PYSAS_STAGE|executing|Running actual submission\\n',encoding='utf-8')
    return 0, 'Running actual submission'
'''
        (self.root/'pysas.py').write_text((ROOT/'pysas.py').read_text(encoding='utf-8')+stub,encoding='utf-8')
        (self.root/'job.sas').write_text('target_token;',encoding='utf-8')
        (self.root/'override.sas').write_text('override_token;',encoding='utf-8')
        (self.root/'_skip.sas').write_text('must_not_run;',encoding='utf-8')
        (self.root/'p.egp').write_text('template',encoding='utf-8')
        data=dict(action='run',program='job.sas',template='p.egp',initialization_mode='override',lib='override.sas',use_parameters=True,parameters_name='_cases.sas',parameters_text='%let ids=edited;')
        plan=self.app.run_plan(data)
        original_arguments=self.app.arguments
        def windows_arguments(values):
            with patch('pysas_ui.os',SimpleNamespace(name='nt')):return original_arguments(values)
        with patch.object(self.app,'arguments',side_effect=windows_arguments):
            identifier=self.app.launch({**data,'plan_revision':plan['revision']})['id']
        process=self.app.processes[identifier]
        try:
            exit_code=process.wait(timeout=30)
            deadline=time.monotonic()+10
            while identifier in self.app.processes and time.monotonic()<deadline:time.sleep(.02)
            item=self.app.commands[identifier]
            console=(self.app.storage/(identifier+'.txt')).read_text(encoding='utf-8')
            self.assertEqual(exit_code,0,console);self.assertEqual(item['status'],'SUCCESS',console)
            folder=self.app.resolve(next(iter(item['tasks'].values()))['path'])
            code=(folder/'code/actual.sas').read_text(encoding='utf-8')
            self.assertNotIn('must_not_run;',code)
            self.assertLess(code.index('override_token;'),code.index('%let ids=edited;'));self.assertLess(code.index('%let ids=edited;'),code.index('target_token;'))
            log=self.app.resolve(item['run_log']).read_text(encoding='utf-8')
            for value in (str(self.root/'override.sas'),'parameters:','WARNING: check sample','Running actual submission'):
                self.assertIn(value,log)
            detail=self.app.command_details(identifier)
            self.assertTrue(any(f['name']=='run.log' and f['is_log'] for f in detail['files']))
            self.assertIsNotNone(detail['self_task'])
            self.assertEqual(json.loads((folder/'execution-plan.json').read_text(encoding='utf-8'))['revision'],plan['revision'])
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_changed_preview_or_changed_worker_inputs_never_submit(self):
        source=self.root/'job.sas';source.write_text('original;')
        data=dict(action='run',program=str(source))
        plan=self.app.run_plan(data)
        source.write_text('changed;')
        with patch.object(self.app,'arguments',return_value=('run',['runner','run',str(source)])),patch.object(ui.subprocess,'Popen') as process:
            with self.assertRaisesRegex(ValueError,'execution plan changed'):
                self.app.launch({**data,'plan_revision':plan['revision']})
        process.assert_not_called()
        with patch.object(self.engine,'execute_eg') as execute:
            with self.assertRaisesRegex(ValueError,'inputs changed after preview'):
                self.engine.run_job(source,self.root/'p.egp',False,None,False,init_dir=self.root,extra_init_dir=self.root/'runner/inbox',expected_plan=plan['revision'])
        execute.assert_not_called()

    def test_full_log_survives_sas_error_cancel_and_automation_exception(self):
        source=self.root/'job.sas';source.write_text('target;')
        override=self.root/'_libs.sas';override.write_text('libs;')
        for rc,status in ((20,'FAILED'),(130,'CANCELLED'),(0,'SAS_ERROR')):
            def execute(*args):
                folder=args[6];(folder/'logs').mkdir();(folder/'logs/job.log').write_text('ERROR: failed;')
                self.assertIn('Status: RUNNING',(folder/'run.log').read_text(encoding='utf-8'))
                return rc,''
            with patch.object(self.engine,'execute_eg',execute),contextlib.redirect_stdout(io.StringIO()):
                result=self.engine.run_job(source,self.root/'p.egp',False,override,False)
            self.assertEqual(result['status'],status)
            log=result['run_log'].read_text(encoding='utf-8');self.assertIn('Status: '+status,log);self.assertIn(str(override),log);self.assertIn('ERROR: failed;',log)
        with patch.object(self.engine,'execute_eg',side_effect=RuntimeError('test export failure')),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'export failure'):
                self.engine.run_job(source,self.root/'p.egp',False,override,False)
        failed=[p for p in (self.root/'runner/runs').iterdir() if 'test export failure' in (p/'run.log').read_text(encoding='utf-8')]
        self.assertEqual(len(failed),1);self.assertIn('status=FAILED',(failed[0]/'status.txt').read_text())

    def test_backup_restores_parameter_lists_and_snapshot_paths_without_overwrite(self):
        self.app.save_parameters(dict(name='_cases.sas', text='first;'))
        snapshot = self.app.storage/'artifacts/original/_cases.sas'
        snapshot.parent.mkdir(parents=True); snapshot.write_text('snapshot;')
        self.app.commands['original'] = dict(id='original',action='run',args=[],name='job',status='SUCCESS',started=10,tasks={},parameters={'name':'_cases.sas','path':self.app.relative(snapshot)})
        stream, _ = self.app.backup()
        with stream: data = stream.read()
        saved = params.load_parameters(self.app.settings, '_cases.sas')
        self.app.save_parameters({**saved, 'text': 'current;'})
        result = self.app.backup(io.BytesIO(data), len(data))
        self.assertEqual(result['parameters'], 1)
        self.assertEqual(params.load_parameters(self.app.settings, '_cases.sas')['text'], 'current;')
        last = self.app.parameter_settings()['last']
        self.assertNotEqual(last, '_cases.sas')
        self.assertEqual(params.load_parameters(self.app.settings, last)['text'], 'first;')
        imported = next(c for c in self.app.commands.values() if c['id'] != 'original')
        self.assertNotEqual(imported['parameters']['path'], self.app.relative(snapshot))
        self.assertEqual((self.app.resolve(imported['parameters']['path'])).read_text(), 'snapshot;')


if __name__ == '__main__': unittest.main()

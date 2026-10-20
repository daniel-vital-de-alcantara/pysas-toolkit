"""Portable folder reuse and independent parent/child inspector contracts."""
import csv
import io
import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import pysas_ui as ui
import ui_paths
from ui_worker import load_engine

ROOT=Path(__file__).resolve().parents[1]

class PortableInspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.root=self.base/'app';self.root.mkdir();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py')
        self.app=ui.Workbench(self.root)
    def tearDown(self):self.temp.cleanup()
    def seed(self):
        run=self.app.tasks/'schedules/demo';child=run/'tasks/A';(child/'logs').mkdir(parents=True)
        (child/'logs/program.log').write_text('NOTE: start\nWARNING: check this\nERROR 22-322: bad\n')
        (child/'output.csv').write_text('a,b\n1,2\n');(run/'schedule.log').write_text('NOTE: saved\n')
        (run/'status.txt').write_text('status=FAILED\n');(run/'report.csv').write_text('x\n1\n')
        with (run/'run_summary.csv').open('w',newline='') as output:
            writer=csv.DictWriter(output,fieldnames=['task_id','program','status','elapsed','task_dir']);writer.writeheader();writer.writerow(dict(task_id='A',program='Program A',status='SAS_ERROR',elapsed=4,task_dir='/old/computer/tasks/A'))
        self.app.commands['schedule']=dict(id='schedule',action='schedule',name='Schedule',started=1,status='FAILED',path='tasks/schedules/demo',args=[],tasks={'A':dict(key='A',name='Program A',status='SAS_ERROR',path='tasks/schedules/demo/tasks/A',elapsed=4)})
        self.app.save(self.app.commands['schedule']);return run,child
    def test_parent_and_child_inspectors_keep_their_own_outputs_logs_and_status(self):
        run,child=self.seed();detail=self.app.details(self.app.relative(run))
        self.assertEqual(detail['status'],'FAILED');self.assertEqual(detail['tasks'][0]['path'],'tasks/schedules/demo/tasks/A')
        log=next(f for f in detail['files'] if f['name'].endswith('program.log'))
        self.assertEqual(log['log_label'],'A · program.log');self.assertTrue(log['inside_task']);self.assertTrue(log['is_log'])
        own=self.app.details(self.app.relative(child));self.assertEqual(own['status'],'SAS_ERROR');self.assertEqual(own['name'],'Program A');self.assertEqual(own['tasks'],[])
        self.assertFalse(next(f for f in own['files'] if f['name']=='output.csv')['inside_task'])
        self.assertEqual(own['export_scope'],'task');self.assertEqual(self.app.resolve(own['export_path']),child)
        deadline=time.monotonic()+3
        while self.app.logs.status(child/'logs/program.log')=='pending' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.logs.status(child/'logs/program.log'),'error')
    def test_default_folders_and_standalone_defaults_remain_separate(self):
        self.assertEqual(self.app.config('preferences.json'),self.root/'settings/preferences.json')
        self.assertEqual(self.app.storage,self.root/'tasks/.workbench')
        engine=load_engine(ROOT/'pysas.py');engine.ROOT_DIR=self.root
        with patch.dict(engine.os.environ,{},clear=True):
            self.assertEqual(engine.saved_runs('files'),self.root/'runner/runs');self.assertEqual(engine.saved_runs('schedules'),self.root/'runs')
        with patch.dict(engine.os.environ,{'PYSAS_RUNS_DIR':str(self.base/'shared-tasks')}):self.assertEqual(engine.saved_runs('files'),self.base/'shared-tasks/files')
    def test_windows_data_references_use_portable_forward_slashes(self):
        class WindowsPath(PureWindowsPath):
            def resolve(self):return self
        app=SimpleNamespace(root=WindowsPath('C:/app'),tasks=WindowsPath('D:/data/tasks'),
                            settings=WindowsPath('D:/data/settings'),storage=WindowsPath('D:/data/tasks/.workbench'))
        with patch.object(ui_paths,'Path',WindowsPath):
            for path,expected in [('D:/data/tasks/graph-sources/a.sas','tasks/graph-sources/a.sas'),
                                  ('D:/data/tasks/files/run/logs/a.log','tasks/files/run/logs/a.log'),
                                  ('D:/data/settings/graphs/plan.json','settings/graphs/plan.json'),
                                  ('D:/data/tasks/.workbench/command.txt','.pysas-ui/command.txt'),
                                  ('C:/app/example.sas','example.sas')]:
                with self.subTest(path=path):self.assertEqual(ui_paths.relative(app,path),expected)
    def test_point_new_installation_to_existing_external_tasks_and_settings(self):
        run,_=self.seed();self.app.save_parameters({'name':'cases.sas','text':'%let ids=1;'})
        tasks=self.base/'shared-tasks';settings=self.base/'shared-settings'
        shutil.copytree(self.app.tasks,tasks);shutil.copytree(self.app.settings,settings)
        self.app.update_data_locations({'tasks':str(tasks),'settings':str(settings)})
        # Apply only at next launch; current jobs never change roots underneath them.
        self.assertNotEqual(self.app.tasks,tasks)
        reopened=ui.Workbench(self.root)
        self.assertEqual(reopened.tasks,tasks);self.assertIn('schedule',reopened.commands)
        self.assertTrue(reopened.resolve('tasks/schedules/demo/tasks/A/logs/program.log').is_file())
        self.assertIn('cases.sas',reopened.parameter_settings()['files'])
        self.assertEqual(reopened.history()[0]['path'],'tasks/schedules/demo')
        other=self.base/'other-install';other.mkdir();shutil.copy2(ROOT/'pysas.py',other/'pysas.py')
        (other/'.pysas-locations.json').write_text(json.dumps({'tasks':str(tasks),'settings':str(settings)}))
        self.assertIn('schedule',ui.Workbench(other).commands)
    def test_external_roots_backup_restore_download_and_cleanup(self):
        self.app.update_data_locations({'tasks':str(self.base/'saved-tasks'),'settings':str(self.base/'saved-settings')});self.app=ui.Workbench(self.root)
        run,child=self.seed();stream,_=self.app.backup()
        with stream:data=stream.read()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:self.assertIn('tasks/schedules/demo/tasks/A/logs/program.log',archive.namelist())
        result=self.app.backup(io.BytesIO(data),len(data));self.assertEqual(result['runs'],1)
        job=self.app.exports.start('task',self.app.relative(child));deadline=time.monotonic()+3
        while self.app.exports.get(job['id'])['status']=='WORKING' and time.monotonic()<deadline:time.sleep(.01)
        done=self.app.exports.get(job['id']);self.assertEqual(done['status'],'READY',done)
        with zipfile.ZipFile(self.app.resolve(done['path'])) as archive:self.assertIn('A/output.csv',archive.namelist())
        plan=ui.ui_storage.cleanup_plan(self.app,'failed');self.assertEqual(plan['runs'],2)
        ui.ui_storage.delete_runs(self.app,plan);self.assertEqual(self.app.history(),[])
    def test_legacy_settings_upgrade_preserves_originals_and_reads_old_runs(self):
        legacy=self.root/'.pysas-ui';legacy.mkdir();(legacy/'preferences.json').write_text(json.dumps({'default_egp':'p.egp'}))
        old=self.root/'runner/runs/old';old.mkdir(parents=True);(old/'status.txt').write_text('status=SUCCESS\nsource=old.sas\n')
        reopened=ui.Workbench(self.root);self.assertEqual(reopened.preferences()['default_egp'],'p.egp')
        self.assertTrue((legacy/'preferences.json').exists());self.assertEqual(reopened.history()[0]['name'],'old.sas')
    def test_locations_reject_overlap_and_running_folder_changes(self):
        with self.assertRaises(ValueError):self.app.update_data_locations({'tasks':str(self.root),'settings':str(self.base/'settings')})
        with self.assertRaises(ValueError):self.app.update_data_locations({'tasks':str(self.base/'data'),'settings':str(self.base/'data/settings')})
        self.app.processes['live']=object()
        with self.assertRaisesRegex(ValueError,'Finish commands'):self.app.update_data_locations({'tasks':str(self.base/'data'),'settings':str(self.base/'settings')})
        self.assertFalse((self.root/'.pysas-locations.json').exists())
    def test_second_installation_cannot_write_to_a_shared_data_folder_concurrently(self):
        folder=self.base/'shared';handle=ui_paths.lock_folder(folder)
        try:
            with self.assertRaises(ValueError):ui_paths.lock_folder(folder)
        finally:handle.close()
        ui_paths.lock_folder(folder).close()
    def test_resolver_refuses_escape_and_symlink_export(self):
        for value in ['tasks/../../outside','settings/../secret','.pysas-ui/../../secret']:
            with self.assertRaises(ValueError):self.app.resolve(value)
        outside=self.base/'outside';outside.mkdir()
        try:(self.app.tasks/'files/linked').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Symlinks unavailable')
        self.assertIsNone(self.app.run_folder('tasks/files/linked'))
        with self.assertRaises(ValueError):self.app.resolve('tasks/files/linked/file')

    def test_import_legacy_runs_is_portable_non_destructive_and_not_duplicated(self):
        old=self.root/'runner/runs/legacy';old.mkdir(parents=True);(old/'status.txt').write_text('status=SUCCESS\nsource=job.sas\nelapsed_seconds=12\n');(old/'log.log').write_text('NOTE: complete')
        command=dict(id='legacy',action='run',name='job.sas',status='SUCCESS',args=[],started=1,tasks={'job':dict(key='job',name='job.sas',status='SUCCESS',elapsed=12,path=str(old))})
        self.app.commands['legacy']=command;self.app.save(command)
        ui_paths.start_legacy_import(self.app);deadline=time.monotonic()+3
        while self.app.storage_busy and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.migration['status'],'READY',self.app.migration)
        self.assertTrue((old/'log.log').is_file());self.assertEqual(len(self.app.history()),1)
        self.assertEqual(self.app.history()[0]['path'],'tasks/files/legacy')
        self.assertEqual(self.app.resolve('runner/runs/legacy/log.log'),self.app.tasks/'files/legacy/log.log')
        self.assertEqual(self.app.resolve(str(old/'log.log')),self.app.tasks/'files/legacy/log.log')
        self.assertEqual(len(self.app.timing_samples()),1)
        reopened=ui.Workbench(self.root);self.assertEqual(len(reopened.history()),1)
        stream,_=reopened.backup()
        with stream,zipfile.ZipFile(stream) as archive:
            self.assertIn('tasks/files/legacy/log.log',archive.namelist());self.assertNotIn('runner/runs/legacy/log.log',archive.namelist())

    def test_legacy_import_failure_keeps_original_and_does_not_publish_partial_run(self):
        old=self.root/'runner/runs/legacy';old.mkdir(parents=True);(old/'status.txt').write_text('status=SUCCESS\n');(old/'log.log').write_text('old')
        with patch.object(ui_paths.shutil,'copystat',side_effect=OSError('disk full')):
            ui_paths.start_legacy_import(self.app);deadline=time.monotonic()+3
            while self.app.storage_busy and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.migration['status'],'FAILED');self.assertTrue((old/'log.log').is_file())
        self.assertFalse((self.app.tasks/'files/legacy').exists());self.assertEqual(self.app.legacy_moves,{})

    def test_command_and_child_names_stay_independent_and_command_artifacts_can_be_zipped(self):
        run,child=self.seed();self.app.rename_run({'path':self.app.relative(child),'name':'Check the extract'})
        self.assertEqual(self.app.details(self.app.relative(child))['name'],'Check the extract');self.assertEqual(self.app.details(self.app.relative(run))['name'],'demo')
        self.app.commands['bundle']=dict(id='bundle',action='bundle-pack',status='SUCCESS',name='Bundle',args=[],tasks={},started=1)
        artifact=self.app.storage/'artifacts/bundle';artifact.mkdir(parents=True);(artifact/'code.txt').write_text('bundle bytes')
        self.app.rename_run({'command':'bundle','name':'My bundle'})
        detail=self.app.command_details('bundle');self.assertEqual(detail['name'],'My bundle');self.assertEqual(detail['export_scope'],'command')
        job=self.app.exports.start('command',detail['export_path']);deadline=time.monotonic()+3
        while self.app.exports.get(job['id'])['status']=='WORKING' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.exports.get(job['id'])['status'],'READY')

class PortableHttpTests(unittest.TestCase):
    def test_external_file_zip_command_inspection_and_pending_location_change(self):
        import http.client
        import threading
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();root=base/'app';root.mkdir();(root/'pysas.py').touch()
            (root/'.pysas-locations.json').write_text(json.dumps({'tasks':str(base/'data'),'settings':str(base/'config')}))
            server=ui.make_server(root);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,data=None):
                client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                client.request(method,path,body=json.dumps(data) if data is not None else None,headers={'Content-Type':'application/json','X-PySAS-Token':server.token})
                response=client.getresponse();result=(response.status,response.read());client.close();return result
            try:
                run=base/'data/files/a';run.mkdir();(run/'status.txt').write_text('status=SUCCESS\n');(run/'log.log').write_text('WARNING: test\n')
                code,body=request('GET','/api/details?path=tasks/files/a');self.assertEqual(code,200,body);self.assertEqual(json.loads(body)['status'],'SUCCESS')
                code,body=request('GET','/api/download?path=tasks/files/a/log.log');self.assertEqual(code,200,body);self.assertIn(b'WARNING:',body)
                code,body=request('GET','/api/run-zip?path=tasks/files/a');self.assertEqual(code,200,body)
                with zipfile.ZipFile(io.BytesIO(body)) as archive:self.assertIn('a/log.log',archive.namelist())
                server.app.commands['command']=dict(id='command',name='Check project',action='egp-inspect',status='SUCCESS',started=1,args=[],tasks={})
                (server.app.storage/'command.txt').write_text('read project')
                code,body=request('GET','/api/command-details?id=command');self.assertEqual(code,200,body);self.assertEqual(json.loads(body)['files'][0]['log_label'],'Command console')
                code,body=request('POST','/api/data-locations',{'tasks':str(base/'another-data'),'settings':str(base/'another-config')});self.assertEqual(code,200,body);self.assertIn('Restart',json.loads(body)['message'])
                self.assertEqual(server.app.tasks,base/'data');self.assertTrue((root/'.pysas-locations.json').is_file())
            finally:server.shutdown();server.server_close();thread.join(timeout=3)

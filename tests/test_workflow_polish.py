"""Immediate preparation, fresh stream sources, replay and folder bundle versions."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pysas_ui as ui
import ui_projects
import ui_storage
import ui_stream


class WorkflowPolishTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py');self.app=ui.Workbench(self.root)
        self.source=self.root/'example.sas';self.source.write_text('%let version=1;')
    def tearDown(self):
        self.app.launches.close();self.app.stream_jobs.close()
        deadline=time.monotonic()+8
        while self.app.processes and time.monotonic()<deadline:time.sleep(.01)
        self.temp.cleanup()
    def wait(self,key):
        deadline=time.monotonic()+10
        while (key in self.app.launches.pending or key in self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
        self.assertNotIn(key,self.app.launches.pending);self.assertNotIn(key,self.app.processes);return self.app.commands[key]
    def test_immediate_ack_and_status_stay_available_while_arguments_are_read_then_same_id_runs(self):
        entered,release=threading.Event(),threading.Event();original=self.app.arguments
        def delayed(data):entered.set();release.wait(5);return original(data)
        with patch.object(self.app,'arguments',side_effect=delayed):
            started=time.monotonic();result=self.app.launches.start({'action':'bundle-pack'});self.assertLess(time.monotonic()-started,.3)
            try:
                self.assertTrue(entered.wait(1));item=self.app.commands[result['id']];self.assertTrue(item['preparing']);self.assertEqual(item['tasks']['_preparing']['status'],'RUNNING');self.assertTrue(self.app.lock.acquire(timeout=.15));self.app.lock.release()
            finally:release.set()
            item=self.wait(result['id'])
        self.assertEqual(item['status'],'SUCCESS');self.assertFalse(item['preparing']);self.assertTrue(self.app.resolve(item['launch_request']).is_file());self.assertTrue(item['download']);self.assertEqual(item['id'],result['id'])
    def test_cancel_during_preparation_prevents_a_worker_and_duplicate_folder_operations(self):
        entered,release=threading.Event(),threading.Event();original=self.app.arguments
        def delayed(data):entered.set();release.wait(5);return original(data)
        with patch.object(self.app,'arguments',side_effect=delayed),patch('pysas_ui.subprocess.Popen',side_effect=AssertionError('Cancelled work cannot launch')):
            result=self.app.launches.start({'action':'bundle-pack'})
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaisesRegex(ValueError,'active bundle'):self.app.launches.start({'action':'bundle-unpack'})
                self.app.stop(result['id'])
            finally:release.set()
            item=self.wait(result['id'])
        self.assertEqual(item['status'],'CANCELLED');self.assertIn('Cancelled',(self.app.storage/(item['id']+'.txt')).read_text())
    def test_invalid_source_finishes_preparation_as_failed_instead_of_counting_forever(self):
        result=self.app.launches.start({'action':'bundle-pack','code_root':str(self.root/'missing')});item=self.wait(result['id'])
        self.assertEqual(item['status'],'FAILED');self.assertIsNotNone(item['finished']);self.assertFalse(item['preparing']);self.assertIn('Preparation FAILED',(self.app.storage/(item['id']+'.txt')).read_text())
    def test_project_names_and_immutable_pack_unpack_history_copy_the_correct_latest_bundle(self):
        first=self.app.launches.start({'action':'bundle-pack'});a=self.wait(first['id']);original=(self.app.storage/'artifacts'/a['download']).read_bytes()
        self.source.write_text('%let version=2;');b=self.wait(self.app.launches.start({'action':'bundle-pack'})['id'])
        self.assertNotEqual(original,(self.app.storage/'artifacts'/b['download']).read_bytes());self.assertEqual(original,(self.app.storage/'artifacts'/a['download']).read_bytes())
        (self.root/'old.bundle.txt').write_bytes(original);c=self.wait(self.app.launches.start({'action':'bundle-unpack','bundle':'old.bundle.txt'})['id']);self.assertEqual(c['status'],'SUCCESS');self.assertEqual(self.source.read_text().strip(),'%let version=1;')
        project=ui_projects.listing(self.app)[0];self.assertEqual(project['name'],self.root.name);self.assertEqual(project['version_count'],3);self.assertEqual(project['latest_command'],c['id'])
        ui_projects.rename(self.app,{'id':project['id'],'name':'Daily source'});detail=ui_projects.detail(self.app,project['id'],a['id']);self.assertEqual(detail['name'],'Daily source');self.assertEqual(detail['command_id'],a['id']);self.assertEqual(len(detail['project_versions']),3)
        with patch('windows_clipboard.copy_file') as clipboard:ui_projects.copy_latest(self.app,project['id']);self.assertEqual(clipboard.call_args.args[0],self.app.storage/'artifacts'/c['download'])
    def test_stream_refresh_uses_latest_original_source_and_current_shared_work_then_rerun_refreshes_again(self):
        project=self.root/'connection.egp';project.write_bytes(b'egp');source=ui_stream.describe(self.app,self.source)
        value=dict(format=ui_stream.FORMAT,name='Extract',egp=ui_stream.describe(self.app,project),shared_work={'enabled':True,'path':'/old/work','libref':'VDI'},rows=[dict(id='source',file=source)])
        self.source.write_text('%let version=2;');ui.atomic_json(self.app.config('shared-work.json'),dict(enabled=True,path='/new/work',libref='VDI'));submitted=[]
        def run(data,**kw):
            folder,document,_=ui_stream.prepare(self.app,data['stream']);submitted.append((folder/'source.sas').read_text());item=self.app.commands[kw['reserved_id']];item.update(preparing=False,status='SUCCESS',path=self.app.relative(folder),finished=time.time(),tasks={});self.app.save(item);return {'id':item['id']}
        with patch('ui_launch.os',SimpleNamespace(name='nt')),patch.object(self.app,'launch',side_effect=run):
            first=self.wait(self.app.launches.start({'action':'stream','stream':value})['id']);self.assertIn('%let version=2;',submitted[0]);self.assertIn("'/new/work'",submitted[0]);self.assertNotIn('%let version=1;',submitted[0])
            self.source.write_text('%let version=3;');second=self.wait(self.app.launches.replay({'command':first['id']})['id']);self.assertNotEqual(second['id'],first['id']);self.assertIn('%let version=3;',submitted[1]);self.assertEqual(self.app.commands[first['id']]['status'],'SUCCESS')
    def test_bundle_project_names_and_replay_configuration_survive_full_backup_with_new_paths(self):
        item=self.wait(self.app.launches.start({'action':'bundle-pack','code_root':str(self.root)})['id']);project=ui_projects.listing(self.app)[0];ui_projects.rename(self.app,{'id':project['id'],'name':'Named folder'})
        archive,_=self.app.backup()
        with archive:raw=archive.read()
        destination=self.root/'another';destination.mkdir();shutil.copy2(ROOT/'pysas.py',destination/'pysas.py');app=ui.Workbench(destination)
        try:
            app.backup(io.BytesIO(raw),len(raw));restored=next(c for c in app.commands.values() if c.get('launch_request'));spec=json.loads(app.resolve(restored['launch_request']).read_text());self.assertEqual(spec['code_root'],str(destination));self.assertEqual(ui_projects.listing(app)[0]['name'],'Named folder');detail=app.command_details(restored['id']);self.assertEqual(detail['project_id'],ui_projects.listing(app)[0]['id'])
        finally:app.launches.close();app.stream_jobs.close()
    def test_continue_reserves_the_schedule_during_preparation_and_preserves_workers(self):
        folder=self.app.tasks/'schedules'/'previous';folder.mkdir();(folder/'schedule_state.json').write_text('{}')
        old=dict(id='old',action='schedule',name='Daily',status='FAILED',path=self.app.relative(folder),started=1,args=['schedule','--workers','4'],tasks={});self.app.commands['old']=old
        entered,release=threading.Event(),threading.Event();captured=[]
        def run(data,**kw):entered.set();release.wait(5);captured.append(data);self.app.commands[kw['reserved_id']]['status']='CANCELLED';return {'id':kw['reserved_id']}
        with patch('ui_launch.os',SimpleNamespace(name='nt')),patch.object(self.app,'launch',side_effect=run):
            result=self.app.launches.replay({'command':'old','mode':'continue'})
            try:
                self.assertTrue(entered.wait(1));self.assertIn(folder,ui_storage.protected_runs(self.app))
                with self.assertRaisesRegex(ValueError,'already running'):self.app.launches.replay({'command':'old','mode':'continue'})
            finally:release.set()
            self.wait(result['id'])
        self.assertEqual(captured[0]['workers'],'4');self.assertEqual(captured[0]['display_name'],'Daily')

    def test_portable_template_uses_embedded_copies_when_original_pc_paths_are_unavailable(self):
        connection=self.root/'connection.egp';connection.write_bytes(b'egp')
        document=dict(format=ui_stream.FORMAT,name='Portable',egp=ui_stream.describe(self.app,connection),rows=[dict(id='one',file=ui_stream.describe(self.app,self.source))])
        document=ui_stream.validate(document);raw=json.dumps(ui_stream.portable(document,ui_stream.assets(self.app,document))).encode()
        self.source.unlink();connection.unlink()
        restored=ui_stream.import_document(self.app,raw)
        self.assertNotIn('origin_path',restored['egp']);self.assertNotIn('origin_path',restored['rows'][0]['file'])
        refreshed=ui_stream.refresh_document(self.app,restored)
        self.assertEqual(ui_stream.read_asset(self.app,refreshed['rows'][0]['file'],'.sas'),b'%let version=1;')

    def test_linked_sources_in_external_configured_input_folder_keep_usable_paths(self):
        with tempfile.TemporaryDirectory() as outside:
            folder=Path(outside).resolve();source=folder/'linked.sas';source.write_text('%let ids=1;')
            ui.atomic_json(self.app.config('folders.json'),{'inputs':str(folder)})
            ref=ui_stream.describe(self.app,source);self.assertEqual(ref['path'],str(source));self.assertEqual(ref['origin_path'],str(source))
            source.write_text('%let ids=2;')
            document=dict(format=ui_stream.FORMAT,name='Linked',rows=[dict(id='one',file=ref)])
            fresh=ui_stream.refresh_document(self.app,document)
            self.assertEqual(ui_stream.read_asset(self.app,fresh['rows'][0]['file'],'.sas'),b'%let ids=2;')

    def test_stream_preparation_failure_keeps_replay_choices_for_retry_after_source_returns(self):
        connection=self.root/'connection.egp';connection.write_bytes(b'egp')
        document=dict(format=ui_stream.FORMAT,name='Retry',egp=ui_stream.describe(self.app,connection),rows=[dict(id='one',file=ui_stream.describe(self.app,self.source))])
        self.source.unlink()
        with patch('ui_launch.os',SimpleNamespace(name='nt')):
            first=self.wait(self.app.launches.start({'action':'stream','stream':document})['id']);self.assertEqual(first['status'],'FAILED');self.assertTrue(self.app.resolve(first['launch_request']).is_file())
            self.source.write_text('%let version=2;')
            def run(data,**kw):
                ui_stream.prepare(self.app,data['stream']);self.app.commands[kw['reserved_id']].update(preparing=False,status='SUCCESS');return {'id':kw['reserved_id']}
            with patch.object(self.app,'launch',side_effect=run):second=self.wait(self.app.launches.replay({'command':first['id']})['id'])
        self.assertEqual(second['status'],'SUCCESS');self.assertNotEqual(first['id'],second['id'])

    def test_quitting_cancels_a_preparing_watcher_before_it_can_start_watching(self):
        entered,release,closed=threading.Event(),threading.Event(),threading.Event()
        def arguments(data):entered.set();release.wait(5);return 'watch',['runner','watch']
        server=SimpleNamespace(app=self.app,shutdown=closed.set)
        with patch('ui_launch.os',SimpleNamespace(name='nt')),patch.object(self.app,'arguments',side_effect=arguments),patch('pysas_ui.subprocess.Popen',side_effect=AssertionError('Quit must not start a watcher')):
            result=self.app.launches.start({'action':'watch'});self.assertTrue(entered.wait(1));thread=threading.Thread(target=ui.LocalServer.request_close,args=(server,));thread.start()
            try:
                deadline=time.monotonic()+2
                while self.app.commands[result['id']]['status']!='STOPPING' and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(self.app.commands[result['id']]['status'],'STOPPING')
            finally:release.set();thread.join(5)
            self.assertTrue(closed.is_set());self.assertEqual(self.wait(result['id'])['status'],'CANCELLED')


if __name__=='__main__':unittest.main()

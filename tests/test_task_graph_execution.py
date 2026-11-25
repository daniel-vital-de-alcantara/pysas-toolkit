"""Task graphs use frozen Run stream submissions, real threads and dependency rules."""
from pathlib import Path
import copy
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import graph_worker
import pysas_ui as ui
import ui_stream
import ui_task_graph as graph


def task(key):
    return dict(id=key,name=key,rows=[dict(id='source_'+key,source_kind='inline',name=key,code='%put task_'+key+';')])


class TaskGraphExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py');self.app=ui.Workbench(self.root)
        self.project=self.root/'connection.egp'
        with zipfile.ZipFile(self.project,'w') as archive:
            archive.writestr('project.xml','<ProjectCollection><Elements><Element Type="SAS.EG.ProjectElements.CodeTask"><Element><ID>Connect</ID><Label>Connection</Label></Element></Element></Elements></ProjectCollection>');archive.writestr('Connect/code.sas','%put connection;')
        self.value=dict(format=graph.FORMAT,id='execution',name='Daily',workers=2,egp=ui_stream.describe(self.app,self.project),
            setup=[dict(id='Setup',name='Libraries and cases',rows=[dict(id='libs',source_kind='inline',name='Libraries',code='%let lib_token=1;'),dict(id='cases',source_kind='inline',name='Cases',code='%let case_ids=12;')])],
            nodes=[task(key) for key in 'ABCD'],edges=[dict(zip(('from','to'),edge)) for edge in [('A','C'),('B','C'),('C','D'),('A','D')]])
    def tearDown(self):
        self.app.launches.close();self.app.stream_jobs.close();deadline=time.monotonic()+5
        while self.app.processes and time.monotonic()<deadline:time.sleep(.01)
        self.temp.cleanup()
    def result(self,folder):return json.loads((folder/'graph-result.json').read_text(encoding='utf-8'))
    def output(self,destination,status='SUCCESS',message=''):
        destination.mkdir(parents=True,exist_ok=True);log='NOTE: '+destination.parent.name+'\n'+message
        (destination/'sas.log').write_text(log)
        return SimpleNamespace(status=status,errors=(message,) if message else (),warnings=(),log=log,html_files=(),table_files=())
    def run_graph(self,folder,runner):
        events=[]
        with patch.dict(os.environ,{'PYSAS_UI_EVENTS':'','PYSAS_UI_CONTROL_FILE':''}),patch('sys.stdout',new=io.StringIO()):
            rc=graph_worker.execute(folder,runner,event_sink=lambda event,**data:events.append(dict(event=event,**data)))
        return rc,events

    def test_parallel_dependencies_shared_setup_and_consolidated_log(self):
        folder,_,_=graph.prepare(self.app,self.value);active=set();completed=set();lock=threading.Lock();barrier=threading.Barrier(2);maximum=[0];codes={}
        def runner(project,source,destination,**options):
            key=source.parent.name.removeprefix('task_');code=source.read_text(encoding='utf-8');codes[key]=code
            self.assertLess(code.index('%let lib_token'),code.index('%let case_ids'));self.assertLess(code.index('%let case_ids'),code.index('%put task_'))
            with lock:
                if key=='C':self.assertTrue({'A','B'}<=completed)
                if key=='D':self.assertTrue({'A','B','C'}<=completed)
                active.add(key);maximum[0]=max(maximum[0],len(active))
            if key in {'A','B'}:barrier.wait(3)
            time.sleep(.025)
            with lock:active.remove(key);completed.add(key)
            return self.output(destination)
        rc,events=self.run_graph(folder,runner);self.assertEqual(rc,0);self.assertEqual(maximum[0],2);self.assertEqual(set(codes),set('ABCD'))
        self.assertEqual(self.result(folder)['status'],'SUCCESS');self.assertEqual(len([e for e in events if e['event']=='start']),4)
        self.assertEqual(len([e for e in events if e['event']=='finish']),4);self.assertTrue(all(e['key']!='Setup' for e in events if e['event']=='start'))
        text=(folder/'run.log').read_text(encoding='utf-8');self.assertIn('A · A · SUCCESS',text);self.assertIn('NOTE: task_D',text)
        rows=list(csv.DictReader(io.StringIO((folder/'run_summary.csv').read_text(encoding='utf-8'))));self.assertEqual(len(rows),4)
        detail=self.app.details(self.app.relative(folder));self.assertEqual(len(detail['tasks']),4);self.assertTrue(all(self.app.resolve(t['path']).is_dir() for t in detail['tasks']))
        self.assertEqual(self.app.history()[0]['kind'],'graph')

    def test_failed_prerequisites_block_all_descendants_but_independent_branch_finishes(self):
        value=copy.deepcopy(self.value);value['edges']=[{'from':'A','to':'B'},{'from':'B','to':'C'}];value['workers']=1
        folder,_,_=graph.prepare(self.app,value);called=[]
        def runner(project,source,destination,**options):
            key=source.parent.name.removeprefix('task_');called.append(key);return self.output(destination,'SAS_ERROR' if key=='A' else 'SUCCESS','ERROR: fixture' if key=='A' else '')
        rc,events=self.run_graph(folder,runner);self.assertEqual(rc,1);self.assertEqual(called,['A','D']);statuses={t['task_id']:t['status'] for t in self.result(folder)['tasks']}
        self.assertEqual(statuses,dict(A='SAS_ERROR',B='BLOCKED_DEPENDENCY',C='BLOCKED_DEPENDENCY',D='SUCCESS'));self.assertEqual(len([e for e in events if e['event']=='finish']),4)

    def test_global_stop_cancels_owned_active_tasks_and_never_starts_waiting_tasks(self):
        value=copy.deepcopy(self.value);value['workers']=1;folder,_,_=graph.prepare(self.app,value);control=self.root/'graph.stop';called=[]
        def runner(project,source,destination,**options):
            called.append(source.parent.name);control.touch();deadline=time.monotonic()+3
            while not options['cancel_file'].is_file() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(options['cancel_file'].is_file());return self.output(destination,'CANCELLED','Cancelled by fixture')
        with patch.dict(os.environ,{'PYSAS_UI_CONTROL_FILE':str(control)}),patch('sys.stdout',new=io.StringIO()):rc=graph_worker.execute(folder,runner,event_sink=lambda *a,**k:None)
        self.assertEqual(rc,130);self.assertEqual(called,['task_A']);self.assertEqual(self.result(folder)['status'],'CANCELLED');self.assertTrue(all(t['status']=='CANCELLED' for t in self.result(folder)['tasks']))

    def test_manual_task_has_setup_without_prerequisites_and_frozen_linked_source(self):
        source=self.root/'selected.sas';source.write_text('%put frozen;');value=copy.deepcopy(self.value)
        value['nodes'][2]['rows']=[dict(id='selected',file=ui_stream.describe(self.app,source))]
        folder,document,manifest=graph.prepare(self.app,value,'C');source.write_text('%put edited;')
        self.assertEqual([t['task_id'] for t in manifest['tasks']],['C']);self.assertEqual(manifest['tasks'][0]['depends_on'],[]);self.assertEqual(document['edges'],[])
        codes=[]
        def runner(project,source,destination,**options):codes.append(source.read_text(encoding='utf-8'));return self.output(destination)
        rc,_=self.run_graph(folder,runner);self.assertEqual(rc,0);self.assertEqual(len(codes),1);self.assertIn('%let case_ids=12;',codes[0]);self.assertIn('%put frozen;',codes[0]);self.assertNotIn('%put edited;',codes[0]);self.assertIn('Manual task run',(folder/'run.log').read_text(encoding='utf-8'))

    def test_preparation_validates_every_task_and_cleans_partial_output_without_engine(self):
        value=copy.deepcopy(self.value);value['nodes'][-1]['rows']=[];before=set((self.app.tasks/'schedules').iterdir())
        with patch('engine.run_sas',side_effect=AssertionError('Preparation cannot execute')):
            with self.assertRaisesRegex(ValueError,'add at least one source'):graph.prepare(self.app,value)
        self.assertEqual(set((self.app.tasks/'schedules').iterdir()),before)
        with self.assertRaises(InterruptedError):graph.prepare(self.app,self.value,cancelled=lambda:True)
        self.assertEqual(set((self.app.tasks/'schedules').iterdir()),before)

    def test_authoring_json_binds_local_paths_and_uses_the_same_section_scanner_as_stream(self):
        source=self.root/'source.sas';source.write_bytes('* (please do not delete) section_start: Réalisé;\r\n%put preço;\r\n* (please do not delete) section_end: Réalisé;'.encode('utf-16'))
        authored=dict(format=graph.AUTHORING_FORMAT,name='AI plan',egp=str(self.project),setup=[],nodes=[dict(id='Extract',name='Extract',rows=[dict(file=str(source),mode='section',sections=['Réalisé'])])],edges=[])
        result=graph.import_document(self.app,json.dumps(authored).encode());self.assertEqual(result['format'],graph.FORMAT);ref=result['nodes'][0]['rows'][0]['file']
        self.assertEqual(ref['sections'],ui_stream.describe(self.app,source)['sections']);self.assertEqual(len(ref['sha256']),64);self.assertEqual(ref['origin_path'],str(source))
        folder,_,_=graph.prepare(self.app,result);self.assertIn('%put preço;',(folder/'tasks/task_Extract/source.sas').read_text(encoding='utf-8'));self.assertNotIn('section_start:',(folder/'tasks/task_Extract/source.sas').read_text(encoding='utf-8'))

    def test_graph_task_successful_timings_are_reused_as_stream_estimates(self):
        folder,document,_=graph.prepare(self.app,self.value)
        self.run_graph(folder,lambda p,s,d,**o:self.output(d))
        estimate=ui_stream.estimate(self.app,graph.task_document(document,document['nodes'][0]));self.assertEqual(estimate['samples'],1);self.assertIsNotNone(estimate['seconds']);self.assertEqual(estimate['unknown'],0)

    def test_selected_branch_keeps_internal_dependencies_and_logs_omitted_prerequisites(self):
        value=copy.deepcopy(self.value);value['nodes'][1]['rows']=[]  # An unselected draft cannot block this run.
        folder,frozen,plan=graph.prepare(self.app,value,task_ids=['D','C']);self.assertEqual(plan['mode'],'selection')
        self.assertEqual(plan['selected_task_ids'],['D','C']);self.assertEqual([n['id'] for n in frozen['nodes']],['C','D'])
        self.assertEqual(frozen['edges'],[{'from':'C','to':'D'}])
        self.assertEqual(plan['tasks'][0]['depends_on'],[]);self.assertEqual(plan['tasks'][1]['depends_on'],['C'])
        self.assertEqual(plan['external_prerequisites'],[e for e in value['edges'] if e['from'] in {'A','B'}])
        called=[]
        def runner(project,source,destination,**options):
            key=source.parent.name.removeprefix('task_');called.append(key)
            if key=='D':self.assertEqual(called,['C','D'])
            code=source.read_text(encoding='utf-8');self.assertIn('%let lib_token',code);self.assertIn('%let case_ids',code)
            return self.output(destination)
        rc,_=self.run_graph(folder,runner);self.assertEqual(rc,0);self.assertEqual(called,['C','D'])
        log=(folder/'run.log').read_text(encoding='utf-8');self.assertIn('Selected-task run: D, C',log)
        self.assertIn('A -> C',log);self.assertIn('B -> C',log);self.assertIn('A -> D',log)
        self.assertEqual({t['task_id'] for t in self.app.details(self.app.relative(folder))['tasks']},{'C','D'})
        self.assertEqual(len(value['nodes']),4);self.assertEqual(len(value['edges']),4)

    def test_invalid_selections_never_fall_back_to_the_full_graph(self):
        for ids in ([], 'A', ['Missing'], ['Setup'], ['A','A'], [None], [1], ['../A']):
            with self.subTest(ids=ids),self.assertRaises(ValueError):graph.prepare(self.app,self.value,task_ids=ids)
        with self.assertRaises(ValueError):graph.prepare(self.app,self.value,'A',task_ids=['B'])
        self.assertEqual(list((self.app.tasks/'schedules').iterdir()),[])

    def test_selection_launch_scope_conflicts_and_replay_preserve_the_exact_selection(self):
        entered,release=threading.Event(),threading.Event();requests=[]
        def launch(data,**options):
            requests.append(copy.deepcopy(data));entered.set();release.wait(5)
            self.app.commands[options['reserved_id']].update(status='SUCCESS',preparing=False);return {'id':options['reserved_id']}
        with patch('ui_launch.os',SimpleNamespace(name='nt')),patch.object(self.app,'launch',side_effect=launch):
            first=self.app.launches.start(dict(action='task-graph',graph=self.value,task_ids=['A','C']))
            try:
                self.assertTrue(entered.wait(1));self.assertEqual(first['command']['graph_task_ids'],['A','C'])
                for scope in ({'task_ids':['C','D']},{'task_id':'A'},{}):
                    with self.assertRaisesRegex(ValueError,'already running'):self.app.launches.start(dict(action='task-graph',graph=self.value,**scope))
                second=self.app.launches.start(dict(action='task-graph',graph=self.value,task_ids=['B','D']));self.assertNotEqual(first['id'],second['id'])
            finally:release.set()
            deadline=time.monotonic()+5
            while self.app.launches.working() and time.monotonic()<deadline:time.sleep(.01)
            self.app.commands[first['id']]['display_name']='Renamed branch'
            replay=self.app.launches.replay(dict(command=first['id'],mode='again'))
            deadline=time.monotonic()+5
            while self.app.launches.working() and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(requests[-1]['task_ids'],['A','C']);self.assertEqual(requests[-1]['graph']['name'],'Daily')
        self.assertEqual(requests[-1]['display_name'],'Renamed branch');self.assertEqual(self.app.commands[replay['id']]['graph_task_ids'],['A','C'])
        legacy=dict(id='old',action='task-graph',graph_id='execution',graph_task_id='B',status='RUNNING')
        self.assertTrue(graph.conflicts([legacy],'execution',['B','D']));self.assertFalse(graph.conflicts([legacy],'execution',['A','C']))

    def test_run_uses_current_shared_work_and_linked_file_but_each_snapshot_stays_frozen(self):
        ui.atomic_json(self.app.config('shared-work.json'),dict(enabled=True,path='/current/work',libref='VDI'));value=copy.deepcopy(self.value);value['shared_work']=dict(enabled=True,path='/old/work',libref='OLD')
        source=self.root/'fresh.sas';source.write_text('%put old;');value['nodes'][0]['rows']=[dict(id='live',file=ui_stream.describe(self.app,source))];source.write_text('%put fresh;')
        folder,_,_=graph.prepare(self.app,value);code=(folder/'tasks/task_A/source.sas').read_text(encoding='utf-8');self.assertIn("'/current/work'",code);self.assertIn('options user=VDI;',code);self.assertIn('%put fresh;',code);self.assertNotIn('%put old;',code)

    def test_launch_registration_and_worker_handoff_use_one_id_and_graph_events(self):
        class Process:
            stdin=None
            def poll(self):return 0
            def wait(self):return 0
        platform=SimpleNamespace(name='nt',environ=os.environ,path=os.path)
        for scope,keys in (({},set('ABCD')),({'task_ids':['C','D']},set('CD'))):
            with self.subTest(scope=scope):
                processes=[]
                def popen(command,**options):
                    self.assertEqual(Path(command[2]).name,'graph_worker.py');folder=Path(command[3]);self.assertTrue((folder/'task-graph-plan.json').is_file());processes.append(command)
                    with patch.dict(os.environ,options['env']),patch('sys.stdout',new=io.StringIO()):self.assertEqual(graph_worker.execute(folder,lambda p,s,d,**o:self.output(d)),0)
                    return Process()
                with patch('ui_launch.os',platform),patch('pysas_ui.os',platform),patch.object(ui.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(ui.subprocess,'CREATE_NO_WINDOW',134217728,create=True),patch('pysas_ui.subprocess.Popen',side_effect=popen):
                    result=self.app.launches.start(dict(action='task-graph',graph=self.value,**scope));deadline=time.monotonic()+10
                    while (self.app.launches.working() or self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
                item=self.app.commands[result['id']];self.assertEqual(item['status'],'SUCCESS',item.get('message'));self.assertEqual(set(item['tasks']),keys);self.assertEqual(len(processes),1);self.assertFalse(item['preparing']);self.assertEqual(item['id'],result['command']['id'])
                self.assertEqual(item['graph_task_ids'],scope.get('task_ids'))
                detail=self.app.command_details(item['id']);self.assertEqual(detail['status'],'SUCCESS');self.assertEqual(len(detail['tasks']),len(keys));self.assertTrue(any(f['name']=='run.log' for f in detail['files']))

    def test_full_backup_remaps_colliding_graph_identity_inside_saved_replay_choices(self):
        graph.save(self.app,{'graph':self.value});key='saved';spec=self.app.storage/'artifacts'/key/'launch/request.json';spec.parent.mkdir(parents=True);ui.atomic_json(spec,dict(action='task-graph',graph=self.value,task_ids=['A','C']))
        self.app.commands[key]=dict(id=key,action='task-graph',graph_id='execution',status='SUCCESS',started=1,name='Daily',args=[],tasks={},launch_request=self.app.relative(spec));self.app.save(self.app.commands[key])
        archive,_=self.app.backup()
        with archive:raw=archive.read()
        self.app.backup(io.BytesIO(raw),len(raw));restored=next(c for c in self.app.commands.values() if c['id']!=key and c.get('launch_request'));request=json.loads(self.app.resolve(restored['launch_request']).read_text(encoding='utf-8'))
        self.assertNotEqual(restored['graph_id'],'execution');self.assertEqual(request['graph']['id'],restored['graph_id']);self.assertEqual(request['task_ids'],['A','C'])

    def test_inactive_source_drafts_do_not_block_execution_but_remain_in_the_editor(self):
        source=self.root/'gone.sas';source.write_text('%put previous draft;');value=copy.deepcopy(self.value);value['nodes'][0]['rows'][0]['file']=ui_stream.describe(self.app,source);source.unlink()
        refreshed=graph.refresh(self.app,value);self.assertIsNotNone(refreshed['nodes'][0]['rows'][0]['file'])
        folder,frozen,_=graph.prepare(self.app,value);self.assertIsNone(frozen['nodes'][0]['rows'][0]['file']);self.assertIn('%put task_A;',(folder/'tasks/task_A/source.sas').read_text(encoding='utf-8'))

    def test_pending_full_graph_and_manual_tasks_have_correct_duplicate_guards(self):
        entered,release=threading.Event(),threading.Event()
        def launch(data,**options):
            entered.set();release.wait(5);self.app.commands[options['reserved_id']].update(status='SUCCESS',preparing=False);return {'id':options['reserved_id']}
        with patch('ui_launch.os',SimpleNamespace(name='nt')),patch.object(self.app,'launch',side_effect=launch):
            first=self.app.launches.start(dict(action='task-graph',graph=self.value,task_id='A'))
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaisesRegex(ValueError,'already running'):self.app.launches.start(dict(action='task-graph',graph=self.value,task_id='A'))
                with self.assertRaisesRegex(ValueError,'already running'):self.app.launches.start(dict(action='task-graph',graph=self.value))
                second=self.app.launches.start(dict(action='task-graph',graph=self.value,task_id='B'));self.assertNotEqual(first['id'],second['id'])
            finally:release.set()
            deadline=time.monotonic()+5
            while self.app.launches.working() and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(self.app.launches.working())

    def test_abrupt_graph_worker_failure_is_finished_and_persisted_in_history(self):
        class Process:
            stdin=None
            def poll(self):return 1
            def wait(self):return 1
        platform=SimpleNamespace(name='nt',environ=os.environ,path=os.path)
        with patch('ui_launch.os',platform),patch('pysas_ui.os',platform),patch.object(ui.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(ui.subprocess,'CREATE_NO_WINDOW',134217728,create=True),patch('pysas_ui.subprocess.Popen',return_value=Process()):
            result=self.app.launches.start(dict(action='task-graph',graph=self.value));deadline=time.monotonic()+8
            while (self.app.launches.working() or self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
        item=self.app.commands[result['id']];self.assertEqual(item['status'],'FAILED');self.assertFalse(item['preparing']);self.assertIn('ended without a final result',item['message']);folder=self.app.resolve(item['path']);self.assertIn('status=FAILED',(folder/'status.txt').read_text(encoding='utf-8'));self.assertIn('ERROR:',(folder/'run.log').read_text(encoding='utf-8'))

    def test_all_tasks_reuse_one_frozen_source_even_if_original_changes_during_preparation(self):
        source=self.root/'shared.sas';source.write_text('%put captured;');value=copy.deepcopy(self.value)
        for node in value['nodes']:node['rows']=[dict(id='input_'+node['id'],file=ui_stream.describe(self.app,source))]
        original=ui_stream.prepare;count=[0]
        def prepare(*args,**options):
            result=original(*args,**options);count[0]+=1
            if count[0]==1:source.write_text('%put later edit;')
            return result
        with patch('ui_stream.prepare',side_effect=prepare):folder,_,_=graph.prepare(self.app,value)
        for node in value['nodes']:
            text=(folder/'tasks'/('task_'+node['id'])/'source.sas').read_text(encoding='utf-8');self.assertIn('%put captured;',text);self.assertNotIn('%put later edit;',text)

    def test_source_budget_is_checked_before_reading_all_excess_assets(self):
        files=[dict(path=key+'.sas',name=key+'.sas',sha256=key*64) for key in 'abc'];value=ui_stream.validate(dict(format=ui_stream.FORMAT,rows=[dict(id=key,file=ref) for key,ref in zip('abc',files)]))
        with patch('ui_stream.SOURCE_LIMIT',4),patch('ui_stream.read_asset',side_effect=[b'aaa',b'bbb',b'ccc']) as read:
            with self.assertRaisesRegex(ValueError,'16 MB'):ui_stream.assets(self.app,value)
        self.assertEqual(read.call_count,2)

    def test_ui_launch_extracts_egp_sources_before_taking_the_snapshot_upload_lock(self):
        previous=self.root/'previous.sas';previous.write_text('%put previous;');value=copy.deepcopy(self.value)
        value['nodes']=[dict(id='A',name='Embedded task',rows=[dict(id='egp',source_kind='egp',project=ui_stream.describe(self.app,self.project),programs=[dict(id='embedded',program_id='Connect',name='Connection',file=ui_stream.describe(self.app,previous))])])];value['edges']=[]
        refresh=graph.refresh;captured=[]
        def outside_lock(*args,**kwargs):
            available=self.app.upload_lock.acquire(False);self.assertTrue(available,'Source refresh must not recursively acquire the snapshot lock')
            if available:self.app.upload_lock.release()
            return refresh(*args,**kwargs)
        class Process:
            stdin=None
            def poll(self):return 1
            def wait(self):return 1
        def popen(command,**options):captured.append((Path(command[3])/'tasks/task_A/source.sas').read_text(encoding='utf-8'));return Process()
        platform=SimpleNamespace(name='nt',environ=os.environ,path=os.path)
        with patch('ui_launch.os',platform),patch('pysas_ui.os',platform),patch.object(ui.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(ui.subprocess,'CREATE_NO_WINDOW',134217728,create=True),patch('pysas_ui.subprocess.Popen',side_effect=popen),patch('ui_task_graph.refresh',side_effect=outside_lock):
            result=self.app.launch(dict(action='task-graph',graph=value));deadline=time.monotonic()+5
            while (self.app.launches.working() or self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(self.app.launches.working());self.assertEqual(len(captured),1,self.app.commands[result['id']].get('message'));self.assertIn('%put connection;',captured[0]);self.assertNotIn('%put previous;',captured[0])

    def test_embedded_egp_sections_are_scanned_and_only_the_chosen_section_is_submitted(self):
        code='outside_before;\n* (please do not delete) section_start: Extract;\n%put selected;\n* (please do not delete) section_end: Extract;\noutside_after;'
        with zipfile.ZipFile(self.project,'w') as archive:
            archive.writestr('project.xml','<ProjectCollection><Elements><Element Type="SAS.EG.ProjectElements.CodeTask"><Element><ID>Connect</ID><Label>Connection</Label></Element></Element></Elements></ProjectCollection>');archive.writestr('Connect/code.sas',code.encode('utf-16'))
        value=copy.deepcopy(self.value);value['egp']=ui_stream.describe(self.app,self.project);value['nodes']=[dict(id='A',name='Section task',rows=[dict(id='project',source_kind='egp',project=value['egp'],programs=[dict(id='code',program_id='Connect',name='Connection',mode='section',sections=['Extract'])])])];value['edges']=[]
        folder,frozen,_=graph.prepare(self.app,value);text=(folder/'tasks/task_A/source.sas').read_text(encoding='utf-8');self.assertIn('%put selected;',text);self.assertNotIn('outside_before',text);self.assertNotIn('outside_after',text)
        self.assertEqual(graph.hydrate(self.app,frozen)['nodes'][0]['rows'][0]['programs'][0]['file']['sections'],['Extract'])


if __name__=='__main__':unittest.main()

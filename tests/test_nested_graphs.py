"""Nested graph gates, bounded concurrency, inherited setup and portable snapshots."""
import copy
import io
import json
from pathlib import Path
import threading
import time
import unittest

import test_task_graph_execution as fixtures
import ui_task_graph as graph
import ui_stream


class NestedGraphTests(unittest.TestCase):
    setUp=fixtures.TaskGraphExecutionTests.setUp
    tearDown=fixtures.TaskGraphExecutionTests.tearDown
    output=fixtures.TaskGraphExecutionTests.output
    result=fixtures.TaskGraphExecutionTests.result
    run_graph=fixtures.TaskGraphExecutionTests.run_graph

    def group(self,key,nodes=None,edges=(),workers=2,setup=()):
        child=dict(format=graph.FORMAT,id=key+'_graph',name=key,egp=None,workers=workers,setup=list(setup),nodes=nodes or [fixtures.task('A'),fixtures.task('B')],edges=list(edges),inherit_connection=True,inherit_shared_work=True)
        return dict(id=key,name=key,kind='graph',rows=[],graph=child)

    def test_container_waits_for_parent_and_releases_downstream_only_after_all_inner_tasks(self):
        value=copy.deepcopy(self.value);inner_setup=dict(id='Setup',name='Inner setup',rows=[dict(id='libs',source_kind='inline',code='%put inner_setup;')])
        value['nodes']=[fixtures.task('A'),self.group('G',edges=[{'from':'A','to':'B'}],setup=[inner_setup]),fixtures.task('Z')]
        value['edges']=[{'from':'A','to':'G'},{'from':'G','to':'Z'}]
        folder,_,plan=graph.prepare(self.app,value);by_path={str((folder/t['path']).resolve()):t for t in plan['tasks']};completed=set();lock=threading.Lock()
        def runner(project,source,destination,**options):
            task=by_path[str(source.parent)];path=tuple(task['node_path']);code=source.read_text(encoding='utf-8')
            with lock:
                if path==('G','A'):self.assertIn(('A',),completed)
                if path==('G','B'):self.assertIn(('G','A'),completed)
                if path==('Z',):self.assertTrue({('G','A'),('G','B')}<=completed)
                completed.add(path)
            if path[0]=='G':self.assertLess(code.index('%let lib_token'),code.index('%put inner_setup'));self.assertLess(code.index('%put inner_setup'),code.index('%put task_'))
            return self.output(destination)
        rc,events=self.run_graph(folder,runner);self.assertEqual(rc,0);self.assertEqual(len(completed),4)
        states={tuple(t['node_path']):t['status'] for t in self.result(folder)['tasks']};self.assertEqual(states[('G',)],'SUCCESS')
        starts=[e for e in events if e['event']=='start'];self.assertEqual(sum(e['kind']=='graph' for e in starts),1);self.assertEqual(sum(e['kind']=='task' for e in starts),4)
        detail=self.app.details(self.app.relative(folder));self.assertEqual({t['task_id'] for t in detail['tasks']},{'A','G','Z'})
        group_task=next(t for t in detail['tasks'] if t['task_id']=='G');inner=self.app.details(group_task['path']);self.assertEqual({t['program'] for t in inner['tasks']},{'A','B'});self.assertTrue(all(self.app.resolve(t['path']).is_dir() for t in inner['tasks']))
        log=(folder/'run.log').read_text(encoding='utf-8');self.assertEqual(log.count('Submitted as one SAS program'),4);self.assertIn('G / A',next(f['log_label'] for f in detail['files'] if '/task_G/' in f['path'] and f['name'].endswith('sas.log')))

    def test_nested_graphs_share_global_slots_and_respect_local_limits(self):
        value=copy.deepcopy(self.value);value['workers']=3;value['setup']=[];value['edges']=[]
        value['nodes']=[self.group('One',nodes=[fixtures.task(k) for k in 'AB'],workers=1),self.group('Two',nodes=[fixtures.task(k) for k in 'ABC'],workers=2)]
        folder,_,plan=graph.prepare(self.app,value);mapping={str((folder/t['path']).resolve()):t['node_path'][0] for t in plan['tasks']};barrier=threading.Barrier(3);lock=threading.Lock();active={'One':0,'Two':0};peak={'One':0,'Two':0,'total':0};entered=[0]
        def runner(project,source,destination,**options):
            group=mapping[str(source.parent)]
            with lock:
                active[group]+=1;peak[group]=max(peak[group],active[group]);peak['total']=max(peak['total'],sum(active.values()));entered[0]+=1;first=entered[0]<=3
            if first:barrier.wait(3)
            time.sleep(.02)
            with lock:active[group]-=1
            return self.output(destination)
        self.assertEqual(self.run_graph(folder,runner)[0],0);self.assertEqual(peak,dict(One=1,Two=2,total=3))

    def test_inner_failure_blocks_outer_dependents_but_independent_branches_finish(self):
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G',nodes=[fixtures.task(k) for k in 'ABC'],edges=[{'from':'A','to':'B'}]),fixtures.task('After'),fixtures.task('Independent')];value['edges']=[{'from':'G','to':'After'}]
        folder,_,plan=graph.prepare(self.app,value);mapping={str((folder/t['path']).resolve()):tuple(t['node_path']) for t in plan['tasks']};called=[]
        def runner(project,source,destination,**options):
            path=mapping[str(source.parent)];called.append(path);return self.output(destination,'SAS_ERROR' if path==('G','A') else 'SUCCESS','ERROR: inner fixture' if path==('G','A') else '')
        self.assertEqual(self.run_graph(folder,runner)[0],1);states={tuple(t['node_path']):t['status'] for t in self.result(folder)['tasks']}
        self.assertEqual(states[('G',)],'FAILED');self.assertEqual(states[('G','B')],'BLOCKED_DEPENDENCY');self.assertEqual(states[('After',)],'BLOCKED_DEPENDENCY');self.assertEqual(states[('Independent',)],'SUCCESS');self.assertEqual(states[('G','C')],'SUCCESS')
        self.assertNotIn(('G','B'),called);self.assertNotIn(('After',),called)

    def test_stopping_one_graph_cancels_its_descendants_and_preserves_independent_work(self):
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G',edges=[{'from':'A','to':'B'}]),fixtures.task('After'),fixtures.task('Independent')];value['edges']=[{'from':'G','to':'After'}]
        folder,_,plan=graph.prepare(self.app,value);mapping={str((folder/t['path']).resolve()):tuple(t['node_path']) for t in plan['tasks']};called=[]
        def runner(project,source,destination,**options):
            path=mapping[str(source.parent)];called.append(path)
            if path==('G','A'):
                (folder/'tasks/task_G/_cancel.request').touch();deadline=time.monotonic()+3
                while not options['cancel_file'].is_file() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(options['cancel_file'].is_file());return self.output(destination,'CANCELLED')
            return self.output(destination)
        self.assertEqual(self.run_graph(folder,runner)[0],1);states={tuple(t['node_path']):t['status'] for t in self.result(folder)['tasks']}
        self.assertEqual(states[('G',)],'CANCELLED');self.assertEqual(states[('G','B')],'CANCELLED');self.assertEqual(states[('After',)],'BLOCKED_DEPENDENCY');self.assertEqual(states[('Independent',)],'SUCCESS')

    def test_nested_manual_selection_keeps_ancestor_setup_and_exact_scope(self):
        value=copy.deepcopy(self.value);value['nodes']=[fixtures.task('Before'),self.group('G',nodes=[fixtures.task(k) for k in 'ABC'],edges=[{'from':'A','to':'B'},{'from':'B','to':'C'}])];value['edges']=[{'from':'Before','to':'G'}]
        folder,_,plan=graph.prepare(self.app,value,task_ids=['B','C'],graph_path=['G']);self.assertEqual({tuple(t['node_path']) for t in plan['tasks']},{('G',),('G','B'),('G','C')})
        self.assertEqual(plan['external_prerequisites'],[{'from':'Before','to':'G'},{'from':'G/A','to':'G/B'}])
        self.assertEqual(self.run_graph(folder,lambda p,s,d,**o:self.output(d))[0],0)
        for task in plan['tasks']:
            if task['kind']=='task':self.assertIn('%let lib_token',(folder/task['path']/'source.sas').read_text(encoding='utf-8'))
        running=dict(id='active',action='task-graph',graph_id='execution',status='RUNNING',graph_run_path=['G'],graph_task_ids=['B'])
        self.assertTrue(graph.conflicts([running],'execution',None));self.assertTrue(graph.conflicts([running],'execution',['G']))
        self.assertFalse(graph.conflicts([running],'execution',['Before']));self.assertTrue(graph.conflicts([running],'execution',None,graph_path=['G']))
        self.assertFalse(graph.conflicts([running],'execution',['C'],graph_path=['G']))

    def test_portable_nested_sources_round_trip_and_validate_every_level(self):
        source=self.root/'nested.sas';source.write_text('%put nested_file;',encoding='utf-8');value=copy.deepcopy(self.value)
        group=self.group('G');group['graph']['nodes'][0]['rows']=[dict(id='file',file=ui_stream.describe(self.app,source))];value['nodes']=[group];value['edges']=[]
        exported=graph.export(self.app,value);raw=self.app.resolve(exported['path']).read_bytes();source.unlink();restored=graph.import_document(self.app,raw)
        self.assertEqual(restored['nodes'][0]['kind'],'graph');ref=restored['nodes'][0]['graph']['nodes'][0]['rows'][0]['file'];self.assertNotIn('origin_path',ref)
        self.assertEqual(ui_stream.read_asset(self.app,ref,'.sas'),b'%put nested_file;');self.assertEqual(self.run_graph(graph.prepare(self.app,restored)[0],lambda p,s,d,**o:self.output(d))[0],0)
        invalid=copy.deepcopy(value);invalid['nodes'][0]['graph']['edges']=[{'from':'A','to':'B'},{'from':'B','to':'A'}]
        with self.assertRaisesRegex(ValueError,'Circular'):graph.validate(invalid)
        invalid=copy.deepcopy(value);invalid['setup']=[invalid['nodes'][0]]
        with self.assertRaisesRegex(ValueError,'Shared setup'):graph.validate(invalid)
        invalid=copy.deepcopy(self.value)
        for i in range(9):invalid=dict(format=graph.FORMAT,id='level'+str(i),name='Deep',nodes=[dict(id='G',name='G',kind='graph',graph=invalid)],setup=[],edges=[])
        with self.assertRaisesRegex(ValueError,'8 levels'):graph.validate(invalid)

    def test_explicit_inner_connection_and_work_options_override_parent_defaults(self):
        import shutil
        value=copy.deepcopy(self.value);group=self.group('G');value['nodes']=[group];value['edges']=[]
        other=self.root/'other.egp';shutil.copy2(self.project,other);child=group['graph'];child.update(inherit_connection=False,egp=ui_stream.describe(self.app,other),server_program='Explicit server',inherit_shared_work=False,shared_work=dict(enabled=False,path='',libref='VDI'));self.project.unlink()
        folder,_,_=graph.prepare(self.app,value)
        def runner(project,source,destination,**options):
            self.assertEqual(options['server_program'],'Explicit server');self.assertEqual(project.read_bytes(),other.read_bytes());self.assertNotIn('options user=',source.read_text(encoding='utf-8'));return self.output(destination)
        self.assertEqual(self.run_graph(folder,runner)[0],0)

    def test_nested_timings_are_reused_and_forecast_respects_container_limits(self):
        import ui_data
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G',workers=1)];value['edges']=[]
        folder,_,_=graph.prepare(self.app,value);self.run_graph(folder,lambda p,s,d,**o:self.output(d));_,_,again=graph.prepare(self.app,value)
        self.assertTrue(all(t['estimate']['samples']==1 for t in again['tasks'] if t['kind']=='task'))
        definitions=[dict(key='G',kind='graph',workers=1,parent_id=None,status='PENDING',depends_on=[]),dict(key='A',kind='task',parent_id='G',status='PENDING',depends_on=[],estimate=dict(seconds=10)),dict(key='B',kind='task',parent_id='G',status='PENDING',depends_on=[],estimate=dict(seconds=20)),dict(key='C',kind='task',parent_id=None,status='PENDING',depends_on=[],estimate=dict(seconds=5)),dict(key='D',kind='task',parent_id=None,status='PENDING',depends_on=['G'],estimate=dict(seconds=7))]
        command=dict(action='task-graph',status='RUNNING',workers=2,tasks={t['key']:t for t in definitions})
        result=ui_data.remaining_work([command],[],[],100);self.assertEqual(result['seconds'],37);self.assertEqual(result['unknown'],0)
        definitions[1]['estimate']['seconds']=None;result=ui_data.remaining_work([command],[],[],100);self.assertEqual(result['seconds'],27);self.assertEqual(result['unknown'],1)

    def test_nested_worker_handoff_replay_and_offline_inspectors(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        import graph_worker
        import pysas_ui as ui
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G'),fixtures.task('Unused')];value['edges']=[]
        class Process:
            stdin=None
            def poll(self):return 0
            def wait(self):return 0
        def popen(command,**options):
            with patch.dict(os.environ,options['env']),patch('sys.stdout',new=io.StringIO()):self.assertEqual(graph_worker.execute(Path(command[3]),lambda p,s,d,**o:self.output(d)),0)
            return Process()
        platform=SimpleNamespace(name='nt',environ=os.environ,path=os.path)
        with patch('ui_launch.os',platform),patch('pysas_ui.os',platform),patch.object(ui.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(ui.subprocess,'CREATE_NO_WINDOW',134217728,create=True),patch('pysas_ui.subprocess.Popen',side_effect=popen):
            result=self.app.launches.start(dict(action='task-graph',graph=value,graph_path=['G'],task_ids=['A']))
            deadline=time.monotonic()+8
            while (self.app.launches.working() or self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
            item=self.app.commands[result['id']];self.assertEqual(item['status'],'SUCCESS',item.get('message'));self.assertEqual(item['graph_run_path'],['G']);self.assertEqual(len(item['tasks']),2)
            root=self.app.command_details(item['id']);self.assertEqual(len(root['tasks']),1);self.assertEqual(root['tasks'][0]['kind'],'graph')
            inner=self.app.details(root['tasks'][0]['path']);self.assertEqual(len(inner['tasks']),1);self.assertEqual(inner['tasks'][0]['status'],'SUCCESS');self.assertEqual(inner['command_id'],item['id'])
            replay=self.app.launches.replay(dict(command=item['id'],mode='again'));deadline=time.monotonic()+8
            while (self.app.launches.working() or self.app.processes) and time.monotonic()<deadline:time.sleep(.01)
            again=self.app.commands[replay['id']];self.assertEqual(again['status'],'SUCCESS',again.get('message'));self.assertEqual(again['graph_run_path'],['G']);self.assertEqual(again['graph_task_ids'],['A'])
        self.app.commands.clear();offline=self.app.details(root['tasks'][0]['path']);self.assertEqual(len(offline['tasks']),1);self.assertEqual(offline['status'],'SUCCESS');self.assertTrue(self.app.resolve(offline['tasks'][0]['path']).is_dir())

    def test_completed_inner_log_is_ready_while_outer_work_is_running(self):
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G',nodes=[fixtures.task('A')]),fixtures.task('Independent')];value['edges']=[];value['workers']=2
        folder,_,plan=graph.prepare(self.app,value);mapping={str((folder/t['path']).resolve()):tuple(t['node_path']) for t in plan['tasks']}
        def runner(project,source,destination,**options):
            if mapping[str(source.parent)]==('Independent',):
                summary=folder/'tasks/task_G/run_summary.csv';deadline=time.monotonic()+3
                while not summary.is_file() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(summary.is_file());self.assertIn('SUCCESS',summary.read_text(encoding='utf-8'));self.assertIn('--- SAS log ---',(summary.parent/'run.log').read_text(encoding='utf-8'))
                detail=self.app.details(self.app.relative(summary.parent));self.assertEqual(detail['status'],'SUCCESS')
            return self.output(destination)
        self.assertEqual(self.run_graph(folder,runner)[0],0)

    def test_previous_flat_formats_upgrade_and_nested_authoring_binds_all_levels(self):
        old=copy.deepcopy(self.value);old['format']='pysas-task-graph-1';self.assertEqual(graph.validate_saved(old)['format'],graph.FORMAT)
        old_authoring=dict(format='pysas-task-graph-authoring-1',name='Old authored',egp=str(self.project),setup=[],nodes=[fixtures.task('A')],edges=[])
        self.assertEqual(graph.import_document(self.app,json.dumps(old_authoring).encode())['format'],graph.FORMAT)
        authored=dict(old_authoring,format=graph.AUTHORING_FORMAT,nodes=[self.group('G')]);imported=graph.import_document(self.app,json.dumps(authored).encode());self.assertEqual(imported['nodes'][0]['graph']['format'],graph.FORMAT)
        self.assertEqual(self.run_graph(graph.prepare(self.app,imported)[0],lambda p,s,d,**o:self.output(d))[0],0)

    def test_backup_preserves_nested_definitions_paths_and_replay_scope(self):
        import pysas_ui as ui
        value=copy.deepcopy(self.value);value['nodes']=[self.group('G')];value['edges']=[];graph.save(self.app,dict(graph=value))
        folder,_,_=graph.prepare(self.app,value);self.run_graph(folder,lambda p,s,d,**o:self.output(d));key='nested_saved'
        spec=self.app.storage/'artifacts'/key/'launch/request.json';spec.parent.mkdir(parents=True);ui.atomic_json(spec,dict(action='task-graph',graph=value,graph_path=['G'],task_ids=['A']))
        item=dict(id=key,action='task-graph',graph_id=value['id'],graph_run_path=['G'],graph_task_ids=['A'],status='SUCCESS',started=1,name='Nested saved',args=[],tasks={},path=self.app.relative(folder),launch_request=self.app.relative(spec));self.app.commands[key]=item;self.app.save(item)
        archive,_=self.app.backup()
        with archive:raw=archive.read()
        self.app.backup(io.BytesIO(raw),len(raw));restored=next(c for c in self.app.commands.values() if c['id']!=key and c.get('launch_request'))
        request=json.loads(self.app.resolve(restored['launch_request']).read_text(encoding='utf-8'));self.assertEqual(request['graph_path'],['G']);self.assertEqual(request['task_ids'],['A']);self.assertEqual(request['graph']['nodes'][0]['kind'],'graph');self.assertEqual(request['graph']['id'],restored['graph_id']);self.assertNotEqual(restored['graph_id'],value['id'])
        detail=self.app.details(restored['path']);self.assertEqual(len(detail['tasks']),1);self.assertTrue(self.app.resolve(detail['tasks'][0]['path']).is_dir())

    def test_eight_levels_keep_physical_sas_paths_short_with_long_local_ids(self):
        value=copy.deepcopy(self.value);nodes=[fixtures.task('A')]
        for i in range(8):nodes=[self.group('Nested'+str(i)+'x'*40,nodes=nodes)]
        value['nodes']=nodes;value['edges']=[];folder,_,plan=graph.prepare(self.app,value)
        leaves=[t for t in plan['tasks'] if t['kind']=='task'];self.assertEqual(len(leaves),1)
        self.assertLess(len(leaves[0]['path']),100);self.assertEqual(len(leaves[0]['node_path']),9)
        self.assertEqual(self.run_graph(folder,lambda p,s,d,**o:self.output(d))[0],0)

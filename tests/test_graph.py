"""Graph plans reuse the scheduler, with frozen code, setup and dependency barriers."""
import argparse
import contextlib
import csv
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
import pysas_ui as ui
import ui_graph
from ui_worker import load_engine

ROOT=Path(__file__).resolve().parents[1]

def node(identifier,path,**values):
    return dict(id=identifier,name=identifier,source=dict(type='file',path=str(path)),x=0,y=0,stop_process_on_error=False,**values)

def graph(nodes,setup=None,edges=None,connection=''):
    return dict(format='pysas-graph-1',id='test_graph',name='Example',workers=10,connection=str(connection),setup=setup or [],nodes=nodes,edges=edges or [])

def egp(path,duplicate=False):
    root=ET.Element('ProjectCollection');items=ET.SubElement(root,'Elements')
    for identifier,label in [('Flow','Flow'),('CodeTask-A','Extract'),('CodeTask-B','Extract' if duplicate else 'Other')]:
        entry=ET.SubElement(items,'Element',Type='SAS.EG.ProjectElements.'+('ProcessFlow' if identifier=='Flow' else 'CodeTask'));meta=ET.SubElement(entry,'Element')
        for name,value in [('ID',identifier),('Label',label),('Container','Flow')]:ET.SubElement(meta,name).text=value
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('project.xml',ET.tostring(root,encoding='utf-16',xml_declaration=True))
        archive.writestr('CodeTask-A/code.sas','/* café */\n%put target;'.encode('cp1252'))
        archive.writestr('CodeTask-B/code.sas',b'%put other;')
    return path

class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.engine=load_engine(ROOT/'pysas.py');self.engine.ROOT_DIR=self.root
        self.project=egp(self.root/'project.egp');self.source=self.root/'a.sas';self.source.write_text('line one;\nline two;\nline three;')
    def tearDown(self):self.temp.cleanup()
    def save(self,data):
        path=self.root/'graph-plan.json';path.write_text(json.dumps(data));return path
    def run_graph(self,data,execute=None,workers=None):
        path=self.save(data)
        with patch.object(self.engine,'execute_eg',side_effect=execute or self.fake_execute),contextlib.redirect_stdout(io.StringIO()):
            status=self.engine.graph_run(argparse.Namespace(action='run',path=str(path),workers=workers,no_notify=True,cancel_file=None))
        folder=next((self.root/'runs').glob('*__graph_*'))
        return status,folder
    def fake_execute(self,mode,project,source,program,first,last,folder,tables,**kwargs):
        (folder/'logs').mkdir(exist_ok=True);(folder/'logs/program.log').write_text('NOTE: complete\n');return 0,'Complete'
    def test_validation_rejects_cycles_duplicates_dangling_setup_edges_and_bad_bounds(self):
        a=node('A',self.source);b=node('B',self.source)
        cases=[graph([a,b],edges=[{'from':'A','to':'B'},{'from':'B','to':'A'}]),graph([a,a]),graph([a],edges=[{'from':'A','to':'missing'}]),graph([a],setup=[node('S',self.source)],edges=[{'from':'S','to':'A'}]),graph([node('A',self.source,row_start=2,section='x')])]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ValueError):self.engine.validate_graph(value)
        self.assertEqual(self.engine.validate_graph(graph([a]))['workers'],10)
    def test_selection_uses_terminal_section_markers_and_inclusive_rows(self):
        text='head\n* (please do not delete) section_start: X;\nvalue;\n* (please do not delete) section_end: X;\ntail'
        self.assertEqual(self.engine.select_graph_text(text,dict(name='A',section='x')),'value;')
        self.assertEqual(self.engine.select_graph_text(text,dict(name='A',row_start=2,row_end=3)),text.splitlines()[1]+'\nvalue;')
        with self.assertRaises(ValueError):self.engine.select_graph_text(text,dict(name='A',row_start=100))
    def test_snapshot_and_shared_setup_survive_source_edits_and_do_not_run_as_jobs(self):
        setup=self.root/'_libs.sas';setup.write_text('%let library_token=1;')
        value=graph([node('A',self.source,row_start=2,row_end=2)],setup=[node('S',setup)],connection=self.project)
        folder=self.engine.prepare_graph_run(self.save(value));self.source.write_text('changed after snapshot;');setup.write_text('changed setup;')
        captured=[]
        def execute(*args,**kwargs):captured.append(args[2].read_text());return self.fake_execute(*args,**kwargs)
        with patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            model,tasks=self.engine.graph_tasks(folder)
            self.engine.execute_schedule(argparse.Namespace(workers=10,no_notify=True,cancel_file=None),folder,self.project,tasks)
        self.assertEqual(len(captured),1);self.assertIn('library_token',captured[0]);self.assertIn('line two;',captured[0]);self.assertNotIn('line one;',captured[0]);self.assertNotIn('changed',captured[0]);self.assertLess(captured[0].index('library_token'),captured[0].index('line two;'))
        self.assertIn('ALWAYS_RUN_DEFINITION',(folder/'run_summary.csv').read_text());self.assertIn('graph order',(folder/'schedule.log').read_text())
        self.assertTrue((folder/'graph-sources.json').is_file())
        manifest=json.loads((folder/'graph-sources.json').read_text())
        self.assertEqual(manifest['nodes']['A']['origin']['path'],str(self.source))
    def test_skipped_middle_node_waits_for_all_prerequisites(self):
        value=graph([node('A',self.source),node('B',self.source,skip=True),node('C',self.source)],edges=[{'from':'A','to':'B'},{'from':'B','to':'C'}],connection=self.project)
        finished=threading.Event();seen=[]
        def execute(*args,**kwargs):
            program=args[3];seen.append(program)
            if program=='A':time.sleep(.03);finished.set()
            if program=='C':self.assertTrue(finished.is_set())
            return self.fake_execute(*args,**kwargs)
        status,folder=self.run_graph(value,execute)
        self.assertEqual(status,0);self.assertEqual(seen,['A','C']);self.assertIn('SKIPPED_SUCCESS',(folder/'run_summary.csv').read_text())
    def test_egp_graph_uses_selected_program_server_and_exports_outputs_with_graph_bridge(self):
        value=graph([dict(id='A',name='Friendly name',source=dict(type='egp',path=str(self.project),program_id='CodeTask-A'))])
        captured=[]
        def execute(*args,**kwargs):captured.append((args,kwargs));return self.fake_execute(*args,**kwargs)
        status,_=self.run_graph(value,execute);args,kwargs=captured[0]
        self.assertEqual(status,0);self.assertEqual(args[0],'RUNGRAPH');self.assertEqual(args[3],'Extract')
        self.assertIn('Set sourceCode = FindProgram(programName)',kwargs['bridge']);self.assertIn('/* café */',args[2].read_text())
        self.assertIn('If UCase(mode) <> "RUNFILE" And UCase(mode) <> "RUNGRAPH" Then',kwargs['bridge'])
        self.assertNotIn('If UCase(mode) = "RUNGRAPH" Then',self.engine.VBS)
    def test_duplicate_egp_labels_fail_before_sas_and_source_failures_publish_no_partial_run(self):
        self.project=egp(self.project,duplicate=True)
        value=graph([dict(id='A',name='A',source=dict(type='egp',path=str(self.project),program_id='CodeTask-A'))])
        with self.assertRaisesRegex(ValueError,'duplicate EGP'):self.engine.prepare_graph_run(self.save(value))
        self.assertFalse(list((self.root/'runs').glob('*__graph_*')))
        value=graph([node('A',self.root/'missing.sas')],connection=self.project)
        with self.assertRaises(ValueError):self.engine.prepare_graph_run(self.save(value))
        self.assertFalse(list((self.root/'runs').glob('*__graph_*')))
    def test_continuation_uses_frozen_graph_and_rejects_edited_snapshot(self):
        value=graph([node('A',self.source)],connection=self.project)
        def fail(*args,**kwargs):self.fake_execute(*args,**kwargs);(args[6]/'logs/program.log').write_text('ERROR: first try\n');return 0,'Error'
        status,folder=self.run_graph(value,fail);self.assertEqual(status,1)
        self.source.write_text('live source changed;')
        captured=[]
        def execute(*args,**kwargs):captured.append(args[2].read_text());return self.fake_execute(*args,**kwargs)
        with patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            result=self.engine.graph_run(argparse.Namespace(action='continue',path=str(folder),workers=1,no_notify=True,cancel_file=None))
        self.assertEqual(result,0);self.assertNotIn('live source changed',captured[0]);self.assertIn('2 parts',(folder/'schedule.log').read_text())
        (folder/'sources/A.selected.sas').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):self.engine.graph_tasks(folder)
    def test_cli_graph_valid_without_openpyxl_and_legacy_parser_is_retained(self):
        value=graph([node('A',self.source)],connection=self.project)
        parsed=self.engine.parser().parse_args(['graph','run',str(self.save(value))]);self.assertEqual(parsed.action,'run')
        self.assertEqual(self.engine.parser().parse_args(['schedule','--max-parallel','4']).workers,4)
        self.assertEqual(self.engine.parser().parse_args(['runner','run','a.sas']).program,'a.sas')
        with patch.dict(sys.modules,{'openpyxl':None}),patch.object(self.engine,'require_openpyxl',side_effect=AssertionError('Graph needs no Excel dependency')):
            status,folder=self.run_graph(value)
        self.assertEqual(status,0);self.assertTrue((folder/'run_summary.csv').is_file());self.assertFalse((folder/'run_summary.xlsx').exists())

    def test_graph_stop_cancels_pending_nodes_and_passes_cancellation_to_active_program(self):
        control=self.root/'cancel.request';called=[]
        value=graph([node('A',self.source),node('B',self.source)],edges=[{'from':'A','to':'B'}],connection=self.project)
        def execute(*args,**kwargs):
            called.append(args[3]);self.assertEqual(kwargs['cancel_file'],str(control))
            control.write_text('stop');return 130,'Stopped by user'
        with patch.object(self.engine,'execute_eg',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            result=self.engine.graph_run(argparse.Namespace(action='run',path=str(self.save(value)),workers=1,no_notify=True,cancel_file=str(control)))
        self.assertEqual(result,130);self.assertEqual(called,['A'])
        folder=next((self.root/'runs').glob('*__graph_*'))
        self.assertIn('CANCELLED',(folder/'run_summary.csv').read_text())

    def test_invalid_parallelism_is_rejected_even_when_continuing(self):
        for workers in (0,33,-1):
            with self.subTest(workers=workers),self.assertRaisesRegex(ValueError,'1 to 32'):
                self.engine.graph_run(argparse.Namespace(action='continue',path='missing',workers=workers))

    def test_graph_run_duration_samples_keep_node_selection_without_excel(self):
        from ui_data import duration_history
        _,folder=self.run_graph(graph([node('A',self.source,row_start=2,row_end=2)],connection=self.project))
        summary=folder/'run_summary.csv'
        with summary.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream);fields=reader.fieldnames;rows=list(reader)
        # Use a known duration: fast fake execution may take zero Windows clock ticks.
        for row in rows:row['elapsed']='42'
        with summary.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        samples=duration_history(self.root,[],bases=[(folder.parent,'schedule')])
        self.assertEqual(len(samples),1);self.assertEqual(samples[0]['key'],('a','',2,2))

class GraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py');self.app=ui.Workbench(self.root)
        self.source=self.root/'a.sas';self.source.write_text('sas;');self.project=egp(self.root/'project.egp')
    def tearDown(self):self.temp.cleanup()
    def test_saved_json_revision_protects_edits_and_actual_local_sources_can_be_linked(self):
        data=graph([node('A',self.source)],connection=self.project)
        saved=ui_graph.save(self.app,{'graph':data});self.assertEqual(ui_graph.load(self.app,'test_graph')['graph']['nodes'][0]['name'],'A')
        self.assertEqual(ui_graph.listing(self.app)[0]['nodes'],1)
        with self.assertRaisesRegex(ValueError,'another window'):ui_graph.save(self.app,{'graph':data,'revision':'old'})
        ui_graph.save(self.app,{'graph':data,'revision':saved['revision']})
        self.assertEqual(ui_graph.link_file(self.app,{'path':str(self.source)})['source']['type'],'file')
        with self.assertRaises(ValueError):ui_graph.link_file(self.app,{'path':str(self.project)})
    def test_saved_graphs_and_uploaded_sources_roundtrip_in_backups_without_overwriting(self):
        sources=self.app.tasks/'graph-sources';sources.mkdir();source=sources/'a.sas';source.write_text('source;');project=egp(sources/'project.egp')
        data=graph([node('A','tasks/graph-sources/a.sas')],connection='tasks/graph-sources/project.egp')
        ui_graph.save(self.app,{'graph':data});stream,_=self.app.backup()
        with stream:raw=stream.read()
        result=self.app.backup(io.BytesIO(raw),len(raw));self.assertEqual(result['runs'],0);self.assertEqual(result['graphs'],1)
        saved=ui_graph.listing(self.app);self.assertEqual(len(saved),2)
        other=next(g for g in saved if g['id']!='test_graph');imported=ui_graph.load(self.app,other['id'])['graph']
        self.assertNotEqual(imported['nodes'][0]['source']['path'],data['nodes'][0]['source']['path']);self.assertTrue(self.app.resolve(imported['nodes'][0]['source']['path']).is_file());self.assertTrue(source.is_file())
        self.assertNotEqual(imported['connection'],data['connection']);self.assertTrue(self.app.resolve(imported['connection']).is_file())
        stream,_=self.app.backup(configs_only=True)
        with stream,zipfile.ZipFile(stream) as archive:
            self.assertIn('.pysas-ui/graphs/test_graph.json',archive.namelist())
            self.assertFalse(any('graph-sources/' in p for p in archive.namelist()))
    def test_binding_checks_sections_and_programs_without_starting_sas(self):
        with self.assertRaisesRegex(ValueError,'section'):ui_graph.bind(self.app,graph([node('A',self.source,section='missing')],connection=self.project),runnable=True)
        programs=ui_graph.egp_programs(self.app,{'path':str(self.project)})['programs'];self.assertEqual(len(programs),2)

    def test_graph_launch_uses_existing_worker_schedule_controls_and_windows_gate(self):
        data=graph([node('A',self.source)],connection=self.project)
        with patch.object(self.app,'launch',return_value={'id':'worker'}) as launch:
            self.assertEqual(ui_graph.launch(self.app,{'graph':data}),{'id':'worker'})
        payload=launch.call_args.args[0];self.assertEqual(payload['action'],'schedule');self.assertEqual(payload['workers'],10)
        self.assertTrue(Path(payload['_graph_plan']).is_file())
        with patch('pysas_ui.os',SimpleNamespace(name='nt')):
            action,args=self.app.arguments(payload)
            self.assertEqual(action,'schedule');self.assertEqual(args[:2],['graph','run']);self.assertIn('--no-notify',args)
            for workers in (0,33):
                with self.assertRaises(ValueError):self.app.arguments({**payload,'workers':workers})
        if sys.platform!='win32':
            with self.assertRaisesRegex(ValueError,'requires Windows'):self.app.arguments(payload)

    def test_observation_reports_setup_as_definitions_and_node_progress(self):
        from ui_worker import observe
        engine=load_engine(ROOT/'pysas.py');engine.ROOT_DIR=self.root
        item={'id':'observed_graph','tasks':{},'status':'RUNNING','action':'schedule'};plan=self.root/'graph.json'
        plan.write_text(json.dumps(graph([node('A',self.source)],setup=[node('S',self.source)],connection=self.project)))
        with patch('ui_worker.emit',side_effect=lambda event_name,**values:self.app.event(item,dict(event=event_name,time=time.time(),**values))),patch.object(engine,'execute_eg',return_value=(0,'Complete')),contextlib.redirect_stdout(io.StringIO()):
            observe(engine)
            result=engine.graph_run(argparse.Namespace(action='run',path=str(plan),workers=None,no_notify=True,cancel_file=None))
        self.assertEqual(result,0);self.assertEqual(item['tasks']['S']['status'],'ALWAYS_RUN_DEFINITION');self.assertIsNone(item['tasks']['S'].get('started'))
        self.assertEqual(item['tasks']['A']['status'],'SUCCESS');self.assertEqual(item['tasks']['A']['setup'][0]['task_id'],'S')

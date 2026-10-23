"""Task graph UI documents: portable drafts, validation and no execution side effects."""
from pathlib import Path
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pysas_ui as ui
import ui_graph
import ui_stream
import ui_task_graph as graph


def project(path):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('project.xml','<ProjectCollection><Elements><Element Type="SAS.EG.ProjectElements.CodeTask"><Element><ID>A</ID><Label>Extract</Label></Element></Element></Elements></ProjectCollection>')
        z.writestr('A/code.sas','%put café;'.encode('cp1252'))
    return path


def source(key,code='%let ids=12;'):
    return dict(id='s_'+key,source_kind='inline',name=key,code=code,mode='whole')


def task(key,**values):
    return dict(id=key,name=key,rows=[source(key)],x=0,y=0,**values)


def document(**values):
    return dict(format=graph.FORMAT,id='example',name='Example',setup=[],nodes=[],edges=[],**values)


class TaskGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py');self.app=ui.Workbench(self.root)
        self.project=project(self.root/'connection.egp');self.source=self.root/'program.sas';self.source.write_text('* (please do not delete) section_start: Extract;\n%put &ids.;\n* (please do not delete) section_end: Extract;',encoding='utf-8')
    def tearDown(self):self.app.stream_jobs.close();self.temp.cleanup()
    def populated(self):
        value=document();value['egp']=ui_stream.describe(self.app,self.project);value['setup']=[task('Libraries'),task('Parameters')];value['setup'][0]['rows'][0]['code']='libname vdi "server-path";'
        first=task('Extract');first['rows'].append(dict(id='sas',source_kind='file',file=ui_stream.describe(self.app,self.source),mode='section',sections=['Extract']))
        value['nodes']=[first,task('Report')];value['nodes'][1].update(x=410,y=85,export_tables=True,consolidate_tables=True)
        value['edges']=[{'from':'Extract','to':'Report'}];value['viewport']=dict(x=-300,y=95,zoom=.75)
        return value

    def test_blank_draft_is_saveable_but_dependencies_are_strict_and_setup_has_no_edges(self):
        value=document();value['nodes']=[dict(id='A',name='A',rows=[dict(id='empty',source_kind='file')],x=-30,y=10),task('B')]
        validated=graph.validate(value);self.assertEqual(validated['workers'],10);self.assertIsNone(validated['nodes'][0]['rows'][0]['file'])
        saved=graph.save(self.app,{'graph':value});self.assertEqual(graph.load(self.app,saved['graph']['id'])['graph']['nodes'][0]['x'],-30)
        value['setup']=[task('Setup')]
        for edges in ([{'from':'A','to':'B'},{'from':'B','to':'A'}],[{'from':'Setup','to':'A'}],[{'from':'A','to':'A'}],[{'from':'A','to':'Missing'}],[{'from':'A','to':'B'}]*2):
            with self.assertRaises(ValueError):graph.validate({**value,'edges':edges})
        for replacement in ({'workers':0},{'viewport':{'zoom':0}},{'viewport':{'x':float('nan')}}):
            with self.assertRaises(ValueError):graph.validate({**value,**replacement})
        duplicate=copy.deepcopy(value);duplicate['nodes'][1]['rows'][0]['id']='empty'
        with self.assertRaisesRegex(ValueError,'unique'):graph.validate(duplicate)

    def test_save_load_export_check_never_launch_sas_and_revision_protects_another_window(self):
        value=self.populated()
        with patch.object(self.app,'launch',side_effect=AssertionError('Editor must not execute')),patch('engine.run_sas',side_effect=AssertionError('Editor must not execute')):
            saved=graph.save(self.app,{'graph':value});loaded=graph.load(self.app,'example')['graph'];artifact=graph.export(self.app,value)
        self.assertEqual(loaded['viewport'],value['viewport']);self.assertEqual(loaded['nodes'][0]['rows'][1]['file']['sections'],['Extract'])
        self.assertEqual(graph.listing(self.app)[0]['nodes'],2);self.assertTrue(self.app.resolve(artifact['path']).is_file())
        with self.assertRaisesRegex(ValueError,'another window'):graph.save(self.app,{'graph':value,'revision':'stale'})
        value['name']='Updated';graph.save(self.app,{'graph':value,'revision':saved['revision']})

    def test_portable_json_restores_sources_setup_order_outputs_and_view_on_another_pc(self):
        value=self.populated();value['shared_work']=dict(enabled=True,path='/server/shared',libref='VDI')
        artifact=graph.export(self.app,value);raw=self.app.resolve(artifact['path']).read_bytes();self.source.unlink();self.project.unlink()
        second=self.root/'second';second.mkdir();shutil.copy2(ROOT/'pysas.py',second/'pysas.py');app=ui.Workbench(second)
        try:
            restored=graph.import_document(app,raw)
            self.assertNotEqual(restored['id'],value['id']);self.assertEqual(restored['edges'],value['edges']);self.assertEqual(restored['viewport'],value['viewport']);self.assertEqual([n['name'] for n in restored['setup']],['Libraries','Parameters']);self.assertTrue(restored['nodes'][1]['consolidate_tables'])
            compiled=ui_stream.compose(app,dict(restored,format=ui_stream.FORMAT,rows=[*graph.all_rows({**restored,'nodes':[]}),*restored['nodes'][0]['rows']]))['source']
            self.assertLess(compiled.index('libname vdi'),compiled.index('%put &ids.;'));self.assertIn('options user=VDI;',compiled)
            self.assertEqual(restored['nodes'][0]['rows'][1]['file']['sections'],['Extract'])
        finally:app.stream_jobs.close()

    def test_tampered_or_cyclic_import_is_atomic(self):
        artifact=graph.export(self.app,self.populated());value=json.loads(self.app.resolve(artifact['path']).read_text());value['assets'][next(iter(value['assets']))]='AAAA'
        before=list((self.app.tasks/'stream-sources').glob('*')) if (self.app.tasks/'stream-sources').exists() else []
        with self.assertRaises(ValueError):graph.import_document(self.app,json.dumps(value).encode())
        after=list((self.app.tasks/'stream-sources').glob('*')) if (self.app.tasks/'stream-sources').exists() else []
        self.assertEqual(before,after)
        value['edges'].append({'from':'Report','to':'Extract'})
        with self.assertRaisesRegex(ValueError,'Circular'):graph.import_document(self.app,json.dumps(value).encode())

    def test_saved_data_roundtrip_remaps_new_graph_refs_and_preserves_existing_graphs(self):
        upload=self.app.upload({'target':['stream'],'name':['source.sas']},io.BytesIO(b'%put restored;'),14)
        value=document();value['nodes']=[dict(id='A',name='A',x=0,y=0,rows=[dict(id='r',file=upload)])];graph.save(self.app,{'graph':value})
        archive,_=self.app.backup()
        with archive:raw=archive.read()
        result=self.app.backup(io.BytesIO(raw),len(raw));self.assertEqual(result['graphs'],1)
        copies=graph.listing(self.app);self.assertEqual(len(copies),2);other=next(item for item in copies if item['id']!='example');restored=graph.load(self.app,other['id'])['graph'];ref=restored['nodes'][0]['rows'][0]['file']
        self.assertNotEqual(ref['path'],upload['path']);self.assertEqual(self.app.resolve(ref['path']).read_bytes(),b'%put restored;')

    def test_saved_graph_larger_than_old_two_mb_limit_survives_config_backup(self):
        value=document();value['nodes']=[dict(id='A',name='A',x=0,y=0,rows=[source(str(i),'%put x;\n'*90000) for i in range(3)])]
        graph.save(self.app,{'graph':value});archive,_=self.app.backup(configs_only=True)
        with archive:raw=archive.read()
        self.assertEqual(self.app.backup(io.BytesIO(raw),len(raw))['graphs'],1)

    def test_legacy_graph_opens_as_a_new_draft_without_overwriting_legacy_or_executing(self):
        legacy=dict(format='pysas-graph-1',id='old',name='Old graph',workers=10,connection=str(self.project),setup=[],nodes=[dict(id='A',name='Extract',source=dict(type='egp',path=str(self.project),program_id='A'),x=50,y=60)],edges=[])
        old=ui_graph.save(self.app,{'graph':legacy});loaded=graph.load(self.app,'old');self.assertTrue(loaded['legacy']);self.assertIsNone(loaded['revision']);self.assertNotEqual(loaded['graph']['id'],'old')
        self.assertEqual(loaded['graph']['nodes'][0]['rows'][0]['source_kind'],'egp');self.assertEqual(loaded['graph']['nodes'][0]['rows'][0]['programs'][0]['file']['has_code'],True)
        graph.save(self.app,{'graph':loaded['graph']});self.assertEqual(ui_graph.load(self.app,'old')['revision'],old['revision'])


if __name__=='__main__':unittest.main()

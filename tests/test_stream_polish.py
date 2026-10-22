"""Polished stream sources and shared EGP reader: meaningful selection/async cases."""
import base64
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import egp_extract
import pysas_ui as ui
import ui_stream as stream


def make_project(path, *, classic=False, malformed=False):
    root=ET.Element('ProjectCollection');elements=ET.SubElement(root,'Elements')
    def node(kind,identifier,name,parent=None):
        item=ET.SubElement(elements,'Element',Type='SAS.EG.ProjectElements.'+kind);meta=ET.SubElement(item,'Element')
        for key,value in [('ID',identifier),('Label',name)]+([('Container',parent)] if parent else []):ET.SubElement(meta,key).text=value
        return item
    flow=node('PFD' if classic else 'ProcessFlow','F1','Préparation')
    node('ProcessFlow','F2','Extracts')
    node('CodeTask','A','_libs',None if classic else 'F1')
    node('CodeTask','B','Cases','F2');node('CodeTask','C','Cases','F2');node('CodeTask','Linked','External','F2')
    if classic:ET.SubElement(ET.SubElement(ET.SubElement(flow,'PFD'),'Process'),'ID').text='A'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('project.xml',b'<broken' if malformed else ET.tostring(root,encoding='utf-16',xml_declaration=True))
        z.writestr('A/code.sas',b'%let prefix=1;')
        z.writestr('B/code.sas','* (please do not delete) section_start: Extract;\n%put café &prefix.;\n* (please do not delete) section_end: Extract;'.encode('cp1252'))
        z.writestr('C/code.sas','%put 年度;'.encode('utf-16'))
        z.writestr('Unmapped/code.sas',b'%put retained;')
    return path


class StreamPolishTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py')
        self.app=ui.Workbench(self.root);self.project=make_project(self.root/'connection.egp')
        self.source=self.root/'parts.sas';self.source.write_text('* (please do not delete) section_start: One;\n%let one=1;\n* (please do not delete) section_end: One;\n%put outside;\n* (please do not delete) section_start: Two;\n%put &one.;\n* (please do not delete) section_end: Two;',encoding='utf-8')
        self.document=dict(format=stream.FORMAT,name='Polished run',egp=stream.describe(self.app,self.project),rows=[],export_html=True,export_tables=False,consolidate_tables=False)
    def tearDown(self):self.app.stream_jobs.close();self.temp.cleanup()
    def file_card(self,key='file',**values):
        return dict(id=key,file=stream.describe(self.app,self.source),**{'mode':'whole',**values})
    def job(self,**request):
        value=self.app.stream_jobs.start(request);deadline=time.monotonic()+5
        while value['status']=='WORKING' and time.monotonic()<deadline:
            time.sleep(.01);value=self.app.stream_jobs.get(value['id'])
        self.assertNotEqual(value['status'],'WORKING',value)
        self.assertEqual(value['status'],'READY',value)
        return value['result']
    def egp_card(self):
        project=stream.describe(self.app,self.project)
        programs=[]
        for identifier in ('A','B'):
            source=self.job(kind='program',project=project,program_id=identifier)
            programs.append(dict(id='program_'+identifier,program_id=identifier,name=source['program']['name'],flow=source['program']['flow'],file=source['file'],mode='whole'))
        return dict(id='project',source_kind='egp',project=project,programs=programs)

    def test_multi_section_selection_only_includes_chosen_parts_in_order(self):
        doc={**self.document,'rows':[self.file_card(mode='section',sections=['Two','One'])]}
        result=stream.compose(self.app,doc)
        self.assertNotIn('%put outside;',result['source']);self.assertNotIn('section_start:',result['source'])
        self.assertLess(result['source'].index('%put &one.;'),result['source'].index('%let one=1;'))
        self.assertEqual([s['section'] for s in result['selections']],['Two','One'])
        self.assertEqual(stream.describe(self.app,self.source)['sections'],['One','Two'])

    def test_blank_bounds_are_invalid_but_one_blank_is_permitted_and_legacy_whole_range_upgrades(self):
        card=self.file_card();card.update(mode='lines',row_start=None,row_end=None)
        with self.assertRaisesRegex(ValueError,'first or last line'):stream.compose(self.app,{**self.document,'rows':[card]})
        card['row_end']=2;self.assertIn('%let one=1;',stream.compose(self.app,{**self.document,'rows':[card]})['source'])
        legacy={**self.document,'format':stream.LEGACY_FORMAT,'rows':[dict(card,row_end=None)]}
        upgraded=stream.validate(legacy);self.assertEqual(upgraded['format'],stream.FORMAT);self.assertEqual(upgraded['rows'][0]['mode'],'whole')

    def test_scan_omits_broken_empty_or_duplicate_sections_and_handles_windows_lines(self):
        text='* (please do not delete) section_start: Broken;\r\n%put 1;\r\n* (please do not delete) section_start: Broken;\r\n* (please do not delete) section_end: Broken;\r\n* (please do not delete) section_start: Empty;\r\n* (please do not delete) section_end: Empty;'
        result=stream.scan_source(text);self.assertEqual(result['sections'],[]);self.assertEqual(len(result['section_issues']),2);self.assertEqual(result['lines'],6)
        whitespace='* (please do not delete) section_start: Blank;\n \t\n* (please do not delete) section_end: Blank;'
        self.assertEqual(stream.scan_source(whitespace)['sections'],[])
        self.assertFalse(stream.scan_source(' \t\r\n')['has_code'])

    def test_inline_macros_precede_file_and_shared_work_is_explicit_and_snapshotted(self):
        inline=dict(id='macro',source_kind='inline',name='Parameters',code='%let case_ids=10,20;',mode='whole')
        doc={**self.document,'rows':[inline,self.file_card()], 'shared_work':dict(enabled=True,path="/server/a'b&c%macro",libref='vdi')}
        compiled=stream.compose(self.app,doc)['source'];self.assertIn("libname('VDI', '/server/a''b&c%macro')",compiled)
        self.assertLess(compiled.index('options user=VDI;'),compiled.index('%let case_ids='));self.assertLess(compiled.index('%let case_ids='),compiled.index('%put outside;'))
        without=stream.compose(self.app,{**doc,'shared_work':{}})['source'];self.assertNotIn('options user=',without)
        folder,_,_=stream.prepare(self.app,doc);restored=stream.import_document(self.app,(folder/'stream.json').read_bytes())
        self.assertEqual(restored['shared_work']['path'],"/server/a'b&c%macro");self.assertEqual(restored['rows'][0]['code'],inline['code'])
        self.assertEqual(stream.compose(self.app,restored)['source'],compiled)

    def test_egp_nested_order_sections_and_json_survive_original_project_removal(self):
        card=self.egp_card();card['programs'][1].update(mode='section',sections=['Extract'])
        doc={**self.document,'rows':[card]};compiled=stream.compose(self.app,doc)['source']
        self.assertLess(compiled.index('%let prefix=1;'),compiled.index('%put café'))
        exported=stream.artifact(self.app,doc,'json');raw=self.app.resolve(exported['path']).read_bytes()
        second=self.root/'other';second.mkdir();shutil.copy2(ROOT/'pysas.py',second/'pysas.py');app=ui.Workbench(second)
        try:
            self.project.unlink();restored=stream.import_document(app,raw)
            self.assertEqual([p['program_id'] for p in restored['rows'][0]['programs']],['A','B'])
            self.assertEqual(restored['rows'][0]['programs'][1]['sections'],['Extract'])
            self.assertEqual(stream.compose(app,restored)['source'],compiled)
        finally:app.stream_jobs.close()

    def test_background_catalog_and_program_extraction_use_shared_reader_without_sas(self):
        with patch('engine.run_sas',side_effect=AssertionError('Must not start SAS')):
            project=stream.describe(self.app,self.project)
            catalog=self.job(kind='project',project=project)['catalog'];self.assertTrue(any(p['flow']=='Préparation' for p in catalog['programs']))
            source=self.job(kind='program',project=project,program_id='B')
            self.assertEqual(source['file']['sections'],['Extract']);self.assertIn('café',self.app.resolve(source['file']['path']).read_bytes().decode('cp1252'))
        linked=self.app.stream_jobs.start(dict(kind='program',project=project,program_id='Linked'));deadline=time.monotonic()+5
        while linked['status']=='WORKING' and time.monotonic()<deadline:time.sleep(.01);linked=self.app.stream_jobs.get(linked['id'])
        self.assertEqual(linked['status'],'FAILED');self.assertIn('externally',linked['error'])

    def test_automatic_connection_skips_invalid_candidates_and_prefers_saved_valid_project(self):
        broken=self.root/'0_bad.egp';broken.write_bytes(b'not a project')
        result=self.job(kind='connection');self.assertEqual(result['egp']['name'],'connection.egp')
        other=make_project(self.root/'other.egp');self.app.update_preferences({'default_egp':str(other)})
        with patch.object(self.app,'inventory',side_effect=AssertionError('A saved valid EGP does not need folder discovery')):
            self.assertEqual(self.job(kind='connection')['egp']['name'],'other.egp')
        self.project.unlink();other.unlink();result=self.job(kind='connection');self.assertIsNone(result['egp']);self.assertTrue(result['warnings'])

    def test_slow_project_preparation_does_not_hold_the_status_lock(self):
        entered,release=threading.Event(),threading.Event();original=egp_extract.inspect_project
        def delayed(value):entered.set();release.wait(3);return original(value)
        with patch.object(egp_extract,'inspect_project',side_effect=delayed):
            job=self.app.stream_jobs.start(dict(kind='project',project=stream.describe(self.app,self.project)))
            self.assertTrue(entered.wait(1));self.assertTrue(self.app.lock.acquire(timeout=.15));self.app.lock.release()
            self.assertEqual(self.app.stream_jobs.get(job['id'])['status'],'WORKING');release.set()
        deadline=time.monotonic()+5
        while self.app.stream_jobs.working() and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(self.app.stream_jobs.working())

    def test_template_restore_keeps_status_available_during_source_writes(self):
        value={**self.document,'rows':[self.file_card()]};document=stream.validate(value)
        raw=json.dumps(stream.portable(document,stream.assets(self.app,document))).encode()
        entered,release=threading.Event(),threading.Event();original=stream.describe;outcome=[]
        def delayed(*args,**kwargs):entered.set();release.wait(3);return original(*args,**kwargs)
        def restore():
            try:outcome.append(stream.import_document(self.app,raw))
            except Exception as exc:outcome.append(exc)
        with patch.object(stream,'describe',side_effect=delayed):
            thread=threading.Thread(target=restore);thread.start()
            try:
                self.assertTrue(entered.wait(1));self.assertTrue(self.app.lock.acquire(timeout=.15));self.app.lock.release();self.assertTrue(self.app.uploading)
            finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertIsInstance(outcome[0],dict);self.assertFalse(self.app.uploading)

    def test_standalone_extractor_handles_classic_modern_duplicate_external_and_unmapped_sources(self):
        for classic in (False,True):
            project=make_project(self.root/('classic.egp' if classic else 'modern.egp'),classic=classic)
            catalog=egp_extract.inspect_project(project)
            self.assertEqual(next(p for p in catalog['programs'] if p['id']=='A')['flow'],'Préparation')
            self.assertEqual(next(p for p in catalog['programs'] if p['id']=='Linked')['member'],None)
            result=egp_extract.extract_project(project,self.root/('classic' if classic else 'modern'))
            self.assertEqual(len(result['programs']),4)
            with zipfile.ZipFile(project) as source:
                for program in result['programs']:
                    self.assertEqual((Path(result['path'])/program['path']).read_bytes(),source.read(program['member']))
                    self.assertEqual((Path(result['path'])/program['by_flow']).read_bytes(),source.read(program['member']))
            self.assertEqual(len({p['path'].casefold() for p in result['programs']}),4)
            with self.assertRaises(FileExistsError):egp_extract.extract_project(project,Path(result['path']))

    def test_standalone_cli_needs_no_pysas_or_workbench_and_lists_machine_readable_catalog(self):
        standalone=self.root/'standalone';standalone.mkdir();shutil.copy2(ROOT/'egp_extract.py',standalone/'egp_extract.py')
        completed=subprocess.run([sys.executable,'egp_extract.py',str(self.project),'--json'],cwd=standalone,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(completed.returncode,0,completed.stderr);self.assertEqual(len(json.loads(completed.stdout)['programs']),5)

    def test_egp_path_traversal_and_xml_entities_are_rejected_without_partial_output(self):
        for entry,body in [('../escape.sas',b'bad'),('project.xml',b'<!DOCTYPE project [<!ENTITY x SYSTEM "file:///etc/passwd">]><project/>')]:
            project=self.root/'unsafe.egp'
            with zipfile.ZipFile(project,'w') as z:z.writestr(entry,body)
            with self.assertRaises(ValueError):egp_extract.inspect_project(project)
            self.assertFalse((self.root/'escape.sas').exists())


if __name__=='__main__':unittest.main()

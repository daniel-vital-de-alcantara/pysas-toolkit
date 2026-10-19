"""EGP extraction parity with MagicRoot's labeled, process-flow exports."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
from ui_worker import load_engine

ROOT=Path(__file__).resolve().parents[1]

class EGPExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.engine=load_engine(ROOT/'pysas.py');self.engine.ROOT_DIR=self.root
    def tearDown(self):self.temp.cleanup()
    def project(self, *, classic=False, encoding='utf-16', extra=None):
        root=ET.Element('ProjectCollection');elements=ET.SubElement(root,'Elements')
        def element(kind,identifier,label,parent=None):
            node=ET.SubElement(elements,'Element',Type='SAS.EG.ProjectElements.'+kind);metadata=ET.SubElement(node,'Element')
            for tag,value in [('ID',identifier),('Label',label)]+([('Container',parent)] if parent else []):ET.SubElement(metadata,tag).text=value
            return node
        flow=element('PFD' if classic else 'ProcessFlow','Flow-A','01. Résultats / Claims')
        element('CodeTask','CodeTask-A','2.04 Realised.SAS',None if classic else 'Flow-A')
        element('CodeTask','CodeTask-B','2.04 Realised.SAS',None if classic else 'Flow-A')
        element('CodeTask','CodeTask-C','CON',None if classic else 'Flow-A')
        element('CodeTask','CodeTask-Linked','Linked program','Flow-A')
        if classic:
            pfd=ET.SubElement(flow,'PFD')
            for identifier in ['CodeTask-A','CodeTask-B','CodeTask-C']:
                ET.SubElement(ET.SubElement(pfd,'Process'),'ID').text=identifier
        path=self.root/'project.egp'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('project.xml',ET.tostring(root,encoding=encoding,xml_declaration=True))
            archive.writestr('CodeTask-A/code.sas','/* café */\ndata _null_;run;'.encode('cp1252'))
            archive.writestr('CodeTask-B/code.sas','%put 年度;'.encode('utf-16'))
            archive.writestr('CodeTask-C/code.sas',b'proc print;run;')
            archive.writestr('Unmapped/code.sas',b'/* retain unmapped */')
            archive.writestr('other/results.html',b'<p>Unchanged result</p>')
            if extra:archive.writestr(*extra)
        return path
    def extract(self,project,output='extracted'):
        with contextlib.redirect_stdout(io.StringIO()):self.engine.egp_extract(argparse.Namespace(project=str(project),output=output))
        folder=self.root/output
        return folder,json.loads((folder/'.pysas_egp_manifest.json').read_text(encoding='utf-8'))
    def pack(self,folder,project,output='repacked.egp'):
        with contextlib.redirect_stdout(io.StringIO()):self.engine.egp_pack(argparse.Namespace(source=str(folder),template=str(project),output=output))
        return self.root/output
    def test_labels_flows_duplicate_names_unicode_and_all_original_bytes(self):
        for classic in [False,True]:
            with self.subTest(classic=classic):
                project=self.project(classic=classic)
                folder,saved=self.extract(project,'classic' if classic else 'modern')
                paths=list(saved['members']);self.assertEqual(len(paths),4)
                self.assertIn('01 SAS project files/2.04 Realised.sas',paths)
                self.assertIn('01 SAS project files/2.04 Realised (1).sas',paths)
                self.assertIn('01 SAS project files/_CON.sas',paths)
                with zipfile.ZipFile(project) as source:
                    for canonical,member in saved['members'].items():
                        self.assertEqual((folder/canonical).read_bytes(),source.read(member))
                        alias=saved['aliases'][canonical][0]
                        self.assertEqual((folder/alias).read_bytes(),source.read(member))
                self.assertTrue((folder/'03. By process flow/01. Résultats _ Claims/2.04 Realised.sas').exists())
                self.assertTrue(any('Unknown_' in aliases[0] for aliases in saved['aliases'].values()))
                self.assertTrue(any('Linked program' in warning for warning in saved['warnings']))
                self.assertTrue((folder/'02 Other files/project.xml').exists())
    def test_namespaces_owner_mapping_and_windows_zip_separators(self):
        project=self.project(encoding='utf-8')
        with zipfile.ZipFile(project) as archive:entries={info.filename:archive.read(info) for info in archive.infolist()}
        root=ET.fromstring(entries['project.xml'])
        for node in root.iter():
            tag=node.tag
            if tag=='Container':tag='OwnerID'
            node.tag='{urn:sas:eg}'+tag
        entries['project.xml']=ET.tostring(root,encoding='utf-16',xml_declaration=True)
        entries['CodeTask-A\\code.sas']=entries.pop('CodeTask-A/code.sas')
        with zipfile.ZipFile(project,'w') as archive:
            for name,raw in entries.items():archive.writestr(name,raw)
        folder,saved=self.extract(project)
        canonical=next(path for path,member in saved['members'].items() if member=='CodeTask-A\\code.sas')
        self.assertIn('01. Résultats _ Claims',saved['aliases'][canonical][0])
        self.assertEqual((folder/canonical).read_bytes(),entries['CodeTask-A\\code.sas'])

    def test_long_labels_are_portable_and_source_hashes_do_not_change(self):
        project=self.project()
        with zipfile.ZipFile(project) as archive:entries={info.filename:archive.read(info) for info in archive.infolist()}
        xml=ET.fromstring(entries['project.xml'])
        for node in xml.iter('Label'):
            if node.text=='2.04 Realised.SAS':node.text='Long program label '*20
        entries['project.xml']=ET.tostring(xml,encoding='utf-16',xml_declaration=True)
        with zipfile.ZipFile(project,'w') as archive:
            for name,raw in entries.items():archive.writestr(name,raw)
        folder,saved=self.extract(project,output='nested output '*4)
        for path,member in saved['members'].items():
            self.assertLessEqual(len(Path(path).name),104)
            self.assertEqual((folder/path).read_bytes(),entries[member])
            if self.engine.os.name=='nt':
                self.assertLessEqual(len(str(folder/path)),240)
                self.assertLessEqual(len(str(folder/saved['aliases'][path][0])),240)

    def test_editing_either_view_repackages_only_the_right_member(self):
        project=self.project();folder,saved=self.extract(project)
        canonical=next(p for p,m in saved['members'].items() if m=='CodeTask-A/code.sas')
        alias=saved['aliases'][canonical][0];edited=b'%put edited by flow;'
        (folder/alias).write_bytes(edited)
        output=self.pack(folder,project)
        with zipfile.ZipFile(project) as original,zipfile.ZipFile(output) as repacked:
            self.assertEqual(original.namelist(),repacked.namelist())
            for name in original.namelist():self.assertEqual(repacked.read(name),edited if name=='CodeTask-A/code.sas' else original.read(name))
        (folder/canonical).write_bytes(edited)
        self.pack(folder,project,'matching-edits.egp')
        (folder/canonical).write_bytes(b'conflicting edit')
        with self.assertRaisesRegex(ValueError,'Conflicting edits'):self.pack(folder,project,'conflict.egp')
        self.assertFalse((self.root/'conflict.egp').exists())
    def test_legacy_manifests_still_repack_and_manifest_escapes_fail(self):
        project=self.project();folder=self.root/'legacy';folder.mkdir()
        (folder/'job.sas').write_bytes(b'changed')
        manifest=folder/'.pysas_egp_manifest.json';manifest.write_text(json.dumps(dict(members={'job.sas':'CodeTask-A/code.sas'})))
        output=self.pack(folder,project)
        with zipfile.ZipFile(output) as archive:self.assertEqual(archive.read('CodeTask-A/code.sas'),b'changed')
        manifest.write_text(json.dumps(dict(members={'../outside.sas':'CodeTask-A/code.sas'})))
        with self.assertRaises(ValueError):self.pack(folder,project,'escape.egp')
        self.assertFalse((self.root/'escape.egp').exists())
    def test_malformed_metadata_falls_back_without_losing_embedded_programs(self):
        project=self.root/'minimal.egp'
        with zipfile.ZipFile(project,'w') as archive:
            archive.writestr('project.xml',b'<broken');archive.writestr('CodeTask-X/code.sas',b'original')
        folder,saved=self.extract(project)
        self.assertEqual(len(saved['members']),1);self.assertTrue(saved['warnings'])
        self.assertEqual(next((folder/'01 SAS project files').glob('*.sas')).read_bytes(),b'original')
    def test_unsafe_archives_and_existing_output_are_not_overwritten(self):
        for index,name in enumerate(['../outside.sas','C:/outside.sas','\\\\server\\share\\outside.sas']):
            project=self.root/f'bad{index}.egp'
            with zipfile.ZipFile(project,'w') as archive:archive.writestr(name,b'bad')
            with self.assertRaises(ValueError):self.extract(project,'unsafe'+str(index))
            self.assertFalse((self.root/('unsafe'+str(index))).exists())
        project=self.project();folder,saved=self.extract(project)
        before=(folder/'.pysas_egp_manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):self.extract(project)
        self.assertEqual((folder/'.pysas_egp_manifest.json').read_bytes(),before)
    def test_failed_read_rolls_back_staging_and_no_source_projects_fail_clearly(self):
        project=self.project()
        with patch.object(self.engine.shutil,'copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.extract(project)
        self.assertFalse((self.root/'extracted').exists());self.assertFalse(list(self.root.glob('.pysas-egp-*')))
        with zipfile.ZipFile(project,'w') as archive:archive.writestr('project.xml',b'<Project/>')
        with self.assertRaisesRegex(ValueError,'no embedded SAS'):self.extract(project)

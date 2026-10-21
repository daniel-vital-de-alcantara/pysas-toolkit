"""Independent engine contract and real process-lifecycle checks; no UI wiring."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine


class StandaloneEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.egp = self.root / 'connection.egp'
        self.egp.write_text('{}', encoding='utf-8')
        self.sas = self.root / 'my program.sas'
        self.sas.write_text('%let city=café;\nproc print data=sashelp.class; run;\n', encoding='utf-8')
        self.output = self.root / 'outputs'

    def tearDown(self):
        self.temp.cleanup()

    def run_engine(self, config=None, **options):
        self.egp.write_text(json.dumps(config or {}), encoding='utf-8')
        def launch(request, output):
            isolation = {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session':True}
            return subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/standalone_engine_worker.py'),str(request)],
                                    cwd=request.parent,stdout=output,stderr=subprocess.STDOUT,**isolation)
        with patch.object(engine,'_require_windows'),patch.object(engine,'_launch_worker',side_effect=launch):
            return engine.run_sas(self.egp,self.sas,self.output,**options)

    def test_single_file_is_independently_importable_without_pysas_or_ui(self):
        standalone = self.root / 'standalone'; standalone.mkdir()
        shutil.copy2(ROOT/'engine.py',standalone/'engine.py')
        child = subprocess.run([sys.executable,'-I','-c',
                                'import sys; sys.path.insert(0, sys.argv[1]); import engine; '
                                'assert "pysas" not in sys.modules and "pysas_ui" not in sys.modules; '
                                'print(engine.__all__)',str(standalone)],capture_output=True,text=True)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertIn('run_sas',child.stdout)

    def test_requested_outputs_full_log_and_exact_source_are_returned_and_saved(self):
        original = self.sas.read_bytes()
        (self.root/'_libs.sas').write_text('must not be automatically prepended;')
        with patch.dict(os.environ,{'PYSAS_SHARED_WORK_PATH':'must not be injected'}):
            result = self.run_engine({'change_source':True},export_html=True,export_tables=True,server_program='Connection seed')
        self.assertTrue(result.success,result.errors); self.assertEqual(result.status,'SUCCESS')
        self.assertEqual(result.server,'SASApp'); self.assertGreater(result.elapsed_seconds,0)
        self.assertEqual(result.log,'NOTE: completed café\n')
        self.assertEqual(len(result.html_files),1); self.assertEqual(len(result.table_files),2)
        self.assertTrue((result.html_files[0].parent/'plot.png').exists())
        self.assertEqual((self.output/'source.sas').read_bytes(),original)
        self.assertEqual(result.submitted_path.read_bytes(),original)
        observed=json.loads((self.output/'observed.json').read_text(encoding='utf-8'))
        self.assertEqual(observed['text'],original.decode('utf-8'))
        self.assertEqual(observed['request']['server_program'],'Connection seed')
        self.assertNotIn('must not',observed['text'])
        summary=json.loads((self.output/'result.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['status'],'SUCCESS');self.assertEqual(summary['html_files'],[str(p) for p in result.html_files])
        self.assertFalse((self.output/'.engine.lock').exists())

    def test_export_flags_are_independent_and_data_only_is_successful(self):
        for html,tables in ((False,False),(True,False),(False,True)):
            with self.subTest(html=html,tables=tables):
                self.output=self.root/f'outputs_{html}_{tables}'
                result=self.run_engine(export_html=html,export_tables=tables,table_format='csv')
                self.assertTrue(result.success,result.errors)
                self.assertEqual(bool(result.html_files),html);self.assertEqual(bool(result.table_files),tables)
                if tables:self.assertIn('café',result.table_files[0].read_text(encoding='utf-8'))
        self.output=self.root/'empty_program'
        result=self.run_engine({'html_count':0,'table_count':0},export_tables=True)
        self.assertTrue(result.success,result.errors);self.assertEqual(result.html_files,());self.assertEqual(result.table_files,())

    def test_sas_errors_are_failures_but_available_results_and_warnings_are_retained(self):
        result=self.run_engine({'log':'1 %put ERROR: echoed source;\nWARNING: check sample\nERROR 22-322: Syntax error.\n'},export_tables=True)
        self.assertEqual(result.status,'SAS_ERROR');self.assertFalse(result.success)
        self.assertEqual(result.errors,('ERROR 22-322: Syntax error.',))
        self.assertEqual(result.warnings,('WARNING: check sample',))
        self.assertEqual(len(result.table_files),2)

    def test_failed_export_keeps_readable_siblings_without_claiming_success(self):
        result=self.run_engine({'failed_table':0},export_tables=True)
        self.assertEqual(result.status,'EXPORT_ERROR');self.assertEqual(len(result.table_files),1)
        self.assertEqual(len(result.html_files),1);self.assertIn('Access denied',' '.join(result.errors))

    def test_non_html_and_invalid_xlsx_are_not_returned_as_valid_outputs(self):
        result=self.run_engine({'html':'%PDF fake <html>metadata</html>','bad_xlsx':True},export_tables=True)
        self.assertEqual(result.status,'EXPORT_ERROR');self.assertEqual(result.html_files,());self.assertEqual(result.table_files,())
        self.assertIn('not HTML',' '.join(result.errors));self.assertIn('not an XLSX',' '.join(result.errors))

    def test_missing_incomplete_or_failed_automation_never_reports_success(self):
        for index,config in enumerate(({'no_manifest':True},{'broken_manifest':True},{'complete':'0'},
                                       {'no_log':True},{'returncode':20},{'error':'Cannot run on SAS server'})):
            with self.subTest(config=config):
                self.output=self.root/str(index)
                result=self.run_engine(config)
                self.assertEqual(result.status,'FAILED');self.assertFalse(result.success)
                self.assertTrue((self.output/'result.json').is_file())

    def test_report_paths_cannot_collect_input_files_as_outputs(self):
        result=self.run_engine({'outside_path':str(self.sas)},export_tables=True)
        self.assertEqual(result.status,'EXPORT_ERROR');self.assertNotIn(self.sas,result.table_files)

    def test_large_worker_console_does_not_deadlock_on_a_pipe(self):
        result=self.run_engine({'output_bytes':2*1024**2},timeout=10)
        self.assertTrue(result.success,result.errors)
        self.assertEqual((self.output/'worker.txt').stat().st_size,2*1024**2)

    def test_timeout_stops_the_owned_process_tree_and_preserves_partial_log(self):
        started=time.monotonic()
        result=self.run_engine({'delay':60},timeout=2)
        self.assertEqual(result.status,'TIMED_OUT');self.assertFalse(result.success)
        self.assertLess(time.monotonic()-started,15)
        self.assertIn('started before timeout',result.log)
        self.assertFalse((self.output/'.engine.lock').exists())
        if os.name!='nt':
            child_pid=int((self.output/'child.pid').read_text())
            # A killed child may briefly be a zombie until its OS parent reaps it.
            child=subprocess.run(['ps','-p',str(child_pid),'-o','stat='],capture_output=True,text=True)
            self.assertTrue(not child.stdout.strip() or child.stdout.strip().startswith('Z'),child.stdout)

    def test_existing_outputs_and_lock_are_preserved(self):
        self.output.mkdir();keep=self.output/'keep.txt';keep.write_bytes(b'keep unchanged')
        with self.assertRaises(FileExistsError):self.run_engine()
        self.assertEqual(keep.read_bytes(),b'keep unchanged');self.assertFalse((self.output/'.engine.lock').exists())
        keep.unlink();lock=self.output/'.engine.lock';lock.touch()
        with self.assertRaises(FileExistsError):self.run_engine()
        self.assertTrue(lock.exists())

    def test_bad_inputs_are_rejected_before_a_process_or_output_directory_exists(self):
        with patch.object(engine,'_launch_worker') as launch:
            for values in ({'export_html':'yes'},{'export_tables':1},{'table_format':'xls'}, {'server_program':''},
                           {'timeout':0},{'timeout':-1},{'timeout':float('nan')},{'timeout':float('inf')},{'timeout':True}):
                with self.subTest(values=values),self.assertRaises(ValueError):
                    engine.run_sas(self.egp,self.sas,self.output,**values)
            self.sas.write_bytes(b'\x00MSMAMARPCRYPT'+b'x'*80)
            with self.assertRaisesRegex(ValueError,'encrypted/protected'):engine.run_sas(self.egp,self.sas,self.output)
            with self.assertRaises(FileNotFoundError):engine.run_sas(self.root/'missing.egp',self.sas,self.output)
            self.assertFalse(self.output.exists());launch.assert_not_called()

    @unittest.skipIf(os.name=='nt','Non-Windows platform validation')
    def test_non_windows_error_is_clear_and_import_does_not_require_windows(self):
        with self.assertRaisesRegex(OSError,'requires Windows'):engine.run_sas(self.egp,self.sas,self.output)
        self.assertFalse(self.output.exists())

    def test_source_log_and_html_encodings_preserve_unicode(self):
        source='/* Informação preço € 中文 */\ndata example; run;\n'
        for encoding in ('utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be'):
            self.assertEqual(engine._decode(source.encode(encoding)),source,encoding)
        self.assertEqual(engine._decode('/* preço € */'.encode('cp1252')),'/* preço € */')
        self.sas.write_bytes('/* preço */'.encode('cp1252'))
        result=self.run_engine({'log':'NOTE: preço €','log_encoding':'cp1252','html_encoding':'utf-16'},encoding='cp1252')
        self.assertTrue(result.success,result.errors);self.assertEqual(result.log,'NOTE: preço €')
        self.assertEqual(result.submitted_path.read_text(encoding='utf-8'),'/* preço */')

    def test_worker_start_failure_returns_failure_with_saved_request(self):
        with patch.object(engine,'_require_windows'),patch.object(engine,'_launch_worker',side_effect=OSError('No Python console')):
            result=engine.run_sas(self.egp,self.sas,self.output)
        self.assertEqual(result.status,'FAILED');self.assertIn('No Python console',' '.join(result.errors))
        self.assertTrue((self.output/'request.json').exists())

    def test_caller_interrupt_stops_its_worker_saves_cancelled_status_and_reraises(self):
        process=Mock(returncode=-9)
        process.wait.side_effect=KeyboardInterrupt
        process.poll.return_value=None
        def stopped(owned):
            self.assertIs(owned,process)
            process.poll.return_value=-9
        with patch.object(engine,'_require_windows'),patch.object(engine,'_launch_worker',return_value=process),patch.object(engine,'_stop_worker',side_effect=stopped) as stop:
            with self.assertRaises(KeyboardInterrupt):engine.run_sas(self.egp,self.sas,self.output)
        stop.assert_called_once_with(process)
        self.assertEqual(json.loads((self.output/'result.json').read_text(encoding='utf-8'))['status'],'CANCELLED')
        self.assertFalse((self.output/'.engine.lock').exists())


@unittest.skipUnless(sys.platform=='win32','Real cscript/hidden console; SAS COM substituted')
class StandaloneEngineWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.sas=self.root/'sample.sas';self.sas.write_text('/* café */\nproc print data=sashelp.class; run;\n',encoding='utf-8')
        self.egp=self.root/'project.egp';self.output=self.root/'output'
        self.workbook=self.root/'table.xlsx'
        with zipfile.ZipFile(self.workbook,'w') as z:z.writestr('xl/workbook.xml','<workbook/>')
        self.config={'log':'NOTE: completed café','expected_server':'SASApp','workbook':str(self.workbook)}
        self.programs=[('Connection','SASApp')]

    def tearDown(self):self.temp.cleanup()

    def run_engine(self,allow_failure=False,**options):
        project=ET.Element('project',self.config)
        for name,server in self.programs:ET.SubElement(project,'program',name=name,server=server)
        ET.ElementTree(project).write(self.egp,encoding='utf-8')
        stub=(ROOT/'tests/fixtures/standalone_engine_com.vbs').read_text(encoding='utf-8')
        bridge=engine._VBS.replace('Option Explicit','Option Explicit\n'+stub,1)
        bridge=bridge.replace('CreateObject("SASEGObjectModel.Application." & version)','New ApplicationStub')
        bridge=bridge.replace('In project.CodeCollection\n','In project.CodeCollection.AllItems\n')
        with patch.object(engine,'_VBS',bridge):
            result=engine.run_sas(self.egp,self.sas,self.output,**options)
        if result.status=='FAILED' and not allow_failure:
            self.fail(str(result.errors)+'\n'+(self.output/'worker.txt').read_text(encoding='utf-8',errors='replace')+'\n'+engine._decode((self.output/'console.txt').read_bytes()))
        return result

    def test_real_worker_cscript_exact_code_server_and_html_table_exports(self):
        result=self.run_engine(export_tables=True)
        self.assertTrue(result.success,result.errors);self.assertEqual(result.server,'SASApp')
        self.assertEqual(len(result.html_files),2);self.assertEqual(len(result.table_files),2)
        self.assertEqual(engine._decode((self.output/'executed.sas').read_bytes()),self.sas.read_text(encoding='utf-8'))
        self.assertTrue((self.output/'closed.txt').exists());self.assertTrue((self.output/'quit.txt').exists())
        self.assertEqual(result.log,'NOTE: completed café')

    def test_real_worker_respects_disabled_outputs(self):
        result=self.run_engine(export_html=False,export_tables=False)
        self.assertTrue(result.success,result.errors);self.assertEqual(result.html_files,());self.assertEqual(result.table_files,())

    def test_real_worker_saves_csv_and_named_server_connection(self):
        self.programs=[('Other','OtherServer'),('Selected','SASApp')]
        result=self.run_engine(export_html=False,export_tables=True,table_format='csv',server_program='selected')
        self.assertTrue(result.success,result.errors);self.assertEqual(result.server,'SASApp')
        self.assertIn('café',result.table_files[0].read_text(encoding='utf-8-sig'))

    def test_real_worker_keeps_sibling_exports_after_one_table_fails(self):
        self.config['fail_first_table']='1'
        result=self.run_engine(export_tables=True)
        self.assertEqual(result.status,'EXPORT_ERROR');self.assertEqual(len(result.table_files),1)
        self.assertEqual(len(result.html_files),2);self.assertIn('Access denied',' '.join(result.errors))

    def test_real_worker_sas_error_preserves_log_and_outputs(self):
        self.config['log']='ERROR 22-322: bad statement'
        result=self.run_engine(export_tables=True)
        self.assertEqual(result.status,'SAS_ERROR');self.assertEqual(len(result.table_files),2)

    def test_real_worker_rejects_ambiguous_servers_before_running(self):
        self.programs=[('First','SASApp'),('Second','OtherServer')]
        result=self.run_engine(allow_failure=True)
        self.assertEqual(result.status,'FAILED');self.assertIn('multiple SAS servers',' '.join(result.errors))
        self.assertFalse((self.output/'executed.sas').exists())
        self.assertTrue((self.output/'closed.txt').exists());self.assertTrue((self.output/'quit.txt').exists())

    def test_real_worker_run_exception_still_saves_log_and_closes_its_session(self):
        self.config['run_error']='1'
        result=self.run_engine(allow_failure=True,export_tables=True)
        self.assertEqual(result.status,'FAILED');self.assertIn('code.Run failure',' '.join(result.errors))
        self.assertTrue(result.log_path.is_file());self.assertEqual(len(result.table_files),2)
        self.assertTrue((self.output/'closed.txt').exists());self.assertTrue((self.output/'quit.txt').exists())

    def test_real_worker_log_save_failure_cannot_report_success(self):
        self.config['log_error']='1'
        result=self.run_engine(allow_failure=True)
        self.assertEqual(result.status,'FAILED');self.assertIn('log save failure',' '.join(result.errors))
        self.assertEqual(len(result.html_files),2);self.assertFalse(result.log_path.exists())


if __name__=='__main__':unittest.main()

from pathlib import Path
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pysas as engine
import pysas_ui as ui


class LiveControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        shutil.copy2(ROOT/'pysas.py',self.root/'pysas.py')
        self.app=ui.Workbench(self.root)

    def tearDown(self):
        self.app.awake.close()
        self.temp.cleanup()

    def test_slow_folder_scan_does_not_block_live_status(self):
        release=threading.Event()
        entered=threading.Event()
        def slow_inventory():
            entered.set()
            release.wait(5)
            return ['job.sas']
        try:
            with patch.object(self.app,'inventory',side_effect=slow_inventory):
                began=time.monotonic()
                first=self.app.state()
                self.assertLess(time.monotonic()-began,1)
                self.assertTrue(entered.wait(1))
                self.assertEqual(first['files'],[])
                self.assertEqual(self.app.state()['files'],[])
                release.set()
                deadline=time.monotonic()+2
                while not self.app.state()['files'] and time.monotonic()<deadline: time.sleep(.02)
                self.assertEqual(self.app.state()['files'],['job.sas'])
        finally:
            release.set()

    def test_legacy_accents_do_not_decode_as_chinese(self):
        text='/* Informação, realização — preço € */\ndata café; run;\n'
        for encoding in ('cp1252','utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be'):
            path=self.root/'code.sas';path.write_bytes(text.encode(encoding))
            self.assertEqual(engine.read_text(path),text,encoding)
            self.assertEqual(ui.read_text(path),text,encoding)
        # Genuine Chinese Unicode remains valid too.
        path.write_text('/* 中文 */\n',encoding='utf-8')
        self.assertIn('中文',ui.read_text(path))

    def test_cancel_before_export_preserves_source_and_submission(self):
        source=self.root/'job.sas'
        original=b'/* pre\xe7o */\ndata sample; run;'
        source.write_bytes(original)
        with patch.object(engine,'execute_eg',return_value=(130,'Stopped by user')), patch.object(engine,'ROOT_DIR',self.root):
            result=engine.run_job(source,self.root/'project.egp',False,None,False)
        self.assertEqual(result['status'],'CANCELLED')
        self.assertEqual((result['run_dir']/'source/job.sas').read_bytes(),original)
        self.assertTrue((result['run_dir']/'_submitted.sas').is_file())

    def test_log_preview_shows_latest_output(self):
        path=self.root/'current.log'
        path.write_text('old line\n'*60000+'NOTE: latest progress\n',encoding='utf-8')
        text=self.app.preview('current.log')['text']
        self.assertEqual(text.splitlines()[-1], 'NOTE: latest progress')
        self.assertIn('Showing latest output',text)

    def test_cancel_targets_only_active_owned_file(self):
        folder=self.root/'runs'/'A';folder.mkdir(parents=True)
        item={'id':'command','tasks':{'A':{'status':'RUNNING','path':'runs/A'},'B':{'status':'SUCCESS','path':'runs/B'}}}
        self.app.commands['command']=item;self.app.processes['command']=object()
        with self.assertRaises(ValueError): self.app.cancel_file('command','B')
        with self.assertRaises(ValueError): self.app.cancel_file('unknown','A')
        self.app.cancel_file('command','A')
        self.assertTrue((folder/'_cancel.request').is_file())
        self.assertEqual(item['tasks']['A']['status'],'CANCELLING')
        self.assertFalse((self.root/'runs/B/_cancel.request').exists())
        self.app.processes.clear()

    def test_execution_streams_before_completion_and_cancel_is_isolated(self):
        run=self.root/'running';run.mkdir()
        original=subprocess.Popen
        target=[]
        def start(command,**kwargs):
            if command[0]=='taskkill.exe': return original(command,**kwargs)
            process=original([sys.executable,'-u','-c','import time; print("NOTE: working",flush=True); time.sleep(30)'],**kwargs)
            target.append(process)
            return process
        other=original([sys.executable,'-c','import time; time.sleep(30)'])
        answer=[]
        try:
            with patch.object(engine.subprocess,'Popen',side_effect=start), patch.dict(os.environ,{'PYSAS_LIVE_LOG':'0'}), patch.object(engine,'cscript_path',return_value=Path(sys.executable)), contextlib.redirect_stdout(io.StringIO()):
                thread=threading.Thread(target=lambda: answer.append(engine.execute_eg('RUNFILE',self.root/'project.egp',self.root/'job.sas','job',0,0,run,False)))
                thread.start()
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    path=run/'console.txt'
                    if path.exists() and 'NOTE: working' in path.read_text(): break
                    time.sleep(.05)
                self.assertTrue(thread.is_alive())
                self.assertIn('NOTE: working',path.read_text())
                (run/'_cancel.request').write_text('stop')
                thread.join(20)
                self.assertFalse(thread.is_alive())
                self.assertEqual(answer[0][0],130)
                self.assertIsNone(other.poll())
        finally:
            for process in target+[other]:
                if process.poll() is None: process.kill()
                process.wait()

    def test_finished_process_does_not_wait_for_inherited_output_handle(self):
        run=self.root/'finished';run.mkdir()
        original=subprocess.Popen
        child_pid=self.root/'child.pid'
        helper=self.root/'simulate.py'
        helper.write_text("import subprocess, sys\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(4)'])\nPath(sys.argv[1]).write_text(str(p.pid))\nprint('Completed',flush=True)\n")
        launched=[]
        def start(command, **kwargs):
            process=original([sys.executable,str(helper),str(child_pid)],**kwargs)
            launched.append(process)
            return process
        began=time.monotonic()
        with patch.object(engine.subprocess,'Popen',side_effect=start), patch.object(engine,'cscript_path',return_value=Path(sys.executable)), patch.dict(os.environ,{'PYSAS_LIVE_LOG':'1'}):
            rc, text=engine.execute_eg('RUNFILE',self.root/'project.egp',self.root/'job.sas','job',0,0,run,False)
        self.assertEqual(rc,0)
        self.assertIn('Completed',text)
        self.assertLess(time.monotonic()-began,3, 'Completion waited for an inherited output handle')
        # The unrelated simulated server naturally exits; it was not killed by the runner.
        time.sleep(max(0,4.5-(time.monotonic()-began)))



if __name__=='__main__': unittest.main()

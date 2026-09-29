import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
import pysas_ui as ui
import ui_storage
from ui_data import export_backup
from pysas import schedule_lock

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        (self.root/'pysas.py').write_text('# engine');self.app=ui.Workbench(self.root)
    def tearDown(self):self.app.awake.close();self.temp.cleanup()
    def seed(self,key,status,kind='file'):
        folder=self.root/('runs' if kind=='schedule' else 'runner/runs')/key;folder.mkdir(parents=True)
        (folder/'log.log').write_text('NOTE: saved')
        (folder/'status.txt').write_text(f'status={status}\n')
        item=dict(id=key,started=100,action='schedule' if kind=='schedule' else 'run',status=status,args=[],tasks={})
        if kind=='schedule':item['path']=self.app.relative(folder)
        else:item['tasks']={'file':dict(status=status,path=self.app.relative(folder))}
        self.app.commands[key]=item;self.app.save(item)
        return folder
    def wait_job(self,job):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=self.app.exports.get(job['id'])
            if result['status']!='WORKING':return result
            time.sleep(.01)
        self.fail('Export did not finish')
    def test_background_export_reports_progress_and_can_be_copied_as_file(self):
        self.seed('good','SUCCESS')
        entered=threading.Event();release=threading.Event();real=export_backup
        def slow(*args,**kwargs):entered.set();release.wait(3);return real(*args,**kwargs)
        with patch.object(ui_storage,'export_backup',slow):
            job=self.app.exports.start('all');self.assertTrue(entered.wait(2))
            self.assertEqual(self.app.exports.get(job['id'])['status'],'WORKING')
            self.assertTrue(self.app.lock.acquire(timeout=.2));self.app.lock.release()
            with self.assertRaisesRegex(ValueError,'operation'):self.app.exports.start('all')
            release.set();done=self.wait_job(job)
        self.assertEqual(done['status'],'READY',done)
        self.assertGreater(done['done'],0)
        with zipfile.ZipFile(self.root/done['path']) as z:self.assertIn('runner/runs/good/log.log',z.namelist())
        with patch.object(ui.windows_clipboard,'copy_file') as copy:
            self.app.copy_file(export=job['id']);copy.assert_called_once_with(self.root/done['path'])
    def test_configs_export_works_while_running_and_excludes_saved_results(self):
        self.seed('live','RUNNING')
        ui.atomic_json(self.app.storage/'bundle-paths.json',dict(paths=[str(self.root)],last=str(self.root)))
        (self.app.storage/'parameters').mkdir();(self.app.storage/'parameters/_cases.sas').write_text('%let id=1;')
        with self.assertRaisesRegex(ValueError,'Finish active'):self.app.exports.start('all')
        done=self.wait_job(self.app.exports.start('configs'))
        with zipfile.ZipFile(self.root/done['path']) as z:
            self.assertEqual(set(z.namelist()),{'manifest.json','.pysas-ui/parameters/_cases.sas'})
            manifest=json.loads(z.read('manifest.json'));self.assertEqual(manifest['commands'],[])
            self.assertEqual(manifest['bundle_settings']['last'],str(self.root))
        self.app.commands['live']['status']='SUCCESS'
        raw=(self.root/done['path']).read_bytes()
        self.assertEqual(self.app.backup(io.BytesIO(raw),len(raw))['commands'],0)
        self.assertTrue((self.root/'runner/runs/live/log.log').is_file())
    def test_export_failure_is_local_job_error_and_releases_busy_flag(self):
        with patch.object(ui_storage,'export_backup',side_effect=OSError('Disk full')):
            done=self.wait_job(self.app.exports.start('all'))
        self.assertEqual(done['status'],'FAILED');self.assertIn('Disk full',done['message'])
        self.assertFalse(self.app.storage_busy)
    def test_cleanup_modes_protect_active_unknown_and_recheck_review(self):
        paths={s:self.seed(s,s) for s in ('SUCCESS','FAILED','STOPPED','RUNNING','UNKNOWN')}
        failed=self.app.cleanup({'mode':'failed'})
        self.assertEqual(failed['runs'],2)
        result=self.app.cleanup({'token':failed['token']});self.assertEqual(result['runs'],2)
        self.assertFalse(paths['FAILED'].exists());self.assertTrue(paths['SUCCESS'].exists())
        self.assertNotIn('FAILED',self.app.commands)
        self.assertFalse((self.app.storage/'FAILED.json').exists())
        finished=self.app.cleanup({'mode':'finished'});self.assertEqual(finished['runs'],1)
        self.app.commands['SUCCESS']['status']='RUNNING';self.app.commands['SUCCESS']['tasks']['file']['status']='RUNNING'
        with self.assertRaisesRegex(ValueError,'changed'):self.app.cleanup({'token':finished['token']})
        for status in ('SUCCESS','RUNNING','UNKNOWN'):self.assertTrue(paths[status].exists())
    def test_cleanup_handles_all_runs_beyond_history_limit_and_locked_cli_schedule(self):
        folder=self.seed('schedule','FAILED','schedule')
        with schedule_lock(folder):self.assertEqual(self.app.cleanup({'mode':'finished'})['runs'],0)
        self.assertEqual(self.app.cleanup({'mode':'finished'})['runs'],1)
        for i in range(501): self.seed('old'+str(i),'FAILED')
        self.assertEqual(self.app.cleanup({'mode':'failed'})['runs'],502)
        for value in ('runs/../pysas.py','runs/../../','../outside','runner/inbox',''):
            self.assertIsNone(ui_storage.run_folder(self.root,value),value)
    def test_storage_counts_files_and_bundle_copy_uses_original_bytes(self):
        folder=self.seed('good','SUCCESS')
        total=ui_storage.storage_usage(self.app)['bytes']
        self.assertGreaterEqual(total,sum(p.stat().st_size for p in folder.iterdir()))
        bundle=self.app.storage/'artifacts/bundle/source.txt';bundle.parent.mkdir(parents=True);bundle.write_bytes(b'\xff\xfe')
        self.app.commands['bundle']=dict(download='bundle/source.txt')
        with patch.object(ui.windows_clipboard,'copy_file') as copy:
            self.app.copy_file(command='bundle');copy.assert_called_once_with(bundle)

if __name__=='__main__':unittest.main()

import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import pysas_ui as ui
import pysas

class HistoryProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        shutil.copy2(Path(__file__).parents[1]/'pysas.py',self.root/'pysas.py');self.app=ui.Workbench(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_names_are_metadata_and_history_preserves_start_on_resume(self):
        folder=self.root/'runs'/'old';folder.mkdir(parents=True)
        (folder/'status.txt').write_text('status=FAILED\nstarted=2020-01-01T00:00:00\nelapsed_seconds=40\n')
        self.app.rename_run({'path':'runs/old','name':'Quarter end'})
        self.app.commands['resume']=dict(id='resume',started=2000000000,action='continue',name='x',path='runs/old',status='RUNNING',elapsed_base=40,tasks={})
        portable=self.app.history()
        portable[0]['path']='./runs/old'  # equivalent portable path must overlay native Windows history too
        self.app.list_cache['history']=(float('inf'),portable)
        with patch.object(self.app,'cached_listing',side_effect=lambda name,loader,ttl:self.app.list_cache['history'][1] if name=='history' else []):
            record=self.app.state()['history'][0]
        self.assertEqual(record['name'],'Quarter end')
        self.assertEqual(record['started'],datetime(2020,1,1).timestamp())
        self.assertEqual(record['active_started'],2000000000)
        self.assertEqual(record['elapsed_base'],40)
        self.assertTrue(folder.exists())
    def test_recent_paths_are_bounded_and_move_to_front(self):
        for n in range(12):
            folder=self.root/str(n);folder.mkdir();self.app.update_bundle_paths({'path':str(folder)})
        settings=self.app.update_bundle_paths({'path':str(self.root/'5')})
        self.assertEqual(len(settings['paths']),10)
        self.assertEqual(settings['paths'][0],str(self.root/'5'))
        self.assertEqual(settings['paths'].count(str(self.root/'5')),1)
    def test_bundle_report_counts_and_verifies_before_mutation(self):
        from argparse import Namespace
        (self.root/'a.sas').write_text('old')
        args=Namespace(root=str(self.root),output=None,recursive=False)
        pysas.bundle_pack(args)
        (self.root/'a.sas').write_text('changed')
        with patch.object(pysas,'bundle_report') as report:
            pysas.bundle_unpack(Namespace(root=str(self.root),bundle=None,no_backup=False))
            self.assertEqual(report.call_args.args[0]['changed'],1)
            self.assertEqual(report.call_args.args[0]['deleted'],0)
            self.assertTrue(Path(report.call_args.args[0]['backup']).is_dir())
        (self.root/'codebase.sasbundle.txt').write_text('invalid')
        with self.assertRaises(ValueError):pysas.bundle_unpack(Namespace(root=str(self.root),bundle=None,no_backup=False))
        self.assertEqual((self.root/'a.sas').read_text(),'old\n')

    def test_export_allows_new_commands_but_freezes_backup_contents(self):
        import threading, time, zipfile, ui_storage
        from ui_data import export_backup
        entered, release=threading.Event(),threading.Event()
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return export_backup(*args,**kwargs)
        with patch.object(ui_storage,'export_backup',slow):
            job=self.app.exports.start('all');self.assertTrue(entered.wait(2))
            identifier=self.app.launch({'action':'bundle-pack'})['id']
            release.set()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and (self.app.exports.working() or self.app.processes):time.sleep(.02)
        self.assertEqual(self.app.exports.get(job['id'])['status'],'READY')
        with zipfile.ZipFile(self.root/self.app.exports.get(job['id'])['path']) as archive:
            self.assertFalse(any(identifier in name for name in archive.namelist()))

"""Preferences and nonblocking refresh regression checks."""
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from pysas_ui import Workbench
from ui_data import export_backup, restore_backup

class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        shutil.copy2(Path(__file__).parents[1] / 'pysas.py', self.root / 'pysas.py')
        self.app = Workbench(self.root)
    def tearDown(self): self.temp.cleanup()

    def test_refresh_keeps_measurement_and_does_not_duplicate_scans(self):
        started, release = threading.Event(), threading.Event()
        count = []
        def scan():
            count.append(1); started.set(); release.wait(2)
            return {'bytes': 20}
        self.app.list_cache['storage'] = (0, {'bytes': 10})
        self.assertEqual(self.app.cached_listing('storage', scan, 1)['bytes'], 10)
        self.assertTrue(started.wait(1))
        for _ in range(3):
            self.app.invalidate_lists()
            self.assertEqual(self.app.cached_listing('storage', scan, 1)['bytes'], 10)
        self.assertEqual(len(count), 1)
        release.set()
        for _ in range(100):
            if 'storage' not in self.app.cache_loading: break
            time.sleep(.01)
        self.assertEqual(self.app.list_cache['storage'][1]['bytes'], 20)

    def test_preferences_validate_inputs_and_do_not_start_on_save(self):
        (self.root/'a.egp').write_bytes(b'project')
        with patch.object(self.app, 'launch') as launch:
            saved=self.app.update_preferences({'default_egp':'a.egp','watcher':{'workers':10,'auto_start':True}})
            launch.assert_not_called()
            self.app.start_saved_watcher()
            launch.assert_called_once()
        self.assertEqual(saved['default_egp'],str(self.root/'a.egp'))
        self.assertEqual(Workbench(self.root).preferences(),saved)
        with self.assertRaises(ValueError): self.app.update_preferences({'default_egp':'../outside.egp'})
        with self.assertRaises(ValueError): self.app.update_preferences({'watcher':{'workers':33}})

    def test_configs_restore_disables_autostart_and_missing_project(self):
        self.app.update_preferences({'watcher':{'workers':7,'auto_start':True}})
        stream,_=export_backup(self.app, configs_only=True)
        try:
            stream.seek(0, 2)
            length=stream.tell();stream.seek(0)
            restore_backup(self.app, stream, length)
        finally: stream.close()
        self.assertFalse(self.app.preferences()['watcher']['auto_start'])
        self.assertEqual(self.app.preferences()['watcher']['workers'],7)

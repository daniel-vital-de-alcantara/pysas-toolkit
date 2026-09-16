from pathlib import Path
import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from windows_app import app_id
from pysas_ui import LocalServer


class LifecycleTests(unittest.TestCase):
    def test_workspace_identity_is_stable_and_distinct(self):
        self.assertEqual(app_id(ROOT), app_id(ROOT / '.'))
        self.assertNotEqual(app_id(ROOT), app_id(ROOT / 'another version'))
        self.assertTrue(app_id(ROOT).startswith('PySAS.Workbench.'))

    def test_close_stops_watcher_and_waits_for_active_jobs(self):
        app = SimpleNamespace(lock=threading.RLock(), processes={'watcher': object(), 'job': object()},
                              commands={'watcher': {'action': 'watch'}, 'job': {'action': 'run'}}, stop=Mock())
        server = SimpleNamespace(app=app, shutdown=Mock())
        thread = threading.Thread(target=LocalServer.request_close, args=(server,))
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while not app.stop.called and time.monotonic() < deadline: time.sleep(.01)
            app.stop.assert_called_once_with('watcher')
            self.assertTrue(app.closing)
            server.shutdown.assert_not_called()
        finally:
            app.processes.clear()
            thread.join(3)
        server.shutdown.assert_called_once()
        LocalServer.request_close(server)
        server.shutdown.assert_called_once()


@unittest.skipUnless(sys.platform == 'win32', 'Windows window and pythonw integration')
class WindowsTests(unittest.TestCase):
    def test_real_window_has_pysas_identity_and_icon(self):
        from ctypes import wintypes as W
        from windows_app import brand_window, window_property, process_windows
        import os
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, ctypes.c_void_p]
        user.CreateWindowExW.restype = W.HWND
        user.DestroyWindow.argtypes = [W.HWND]
        user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user.SendMessageW.restype = W.LPARAM
        hwnd = user.CreateWindowExW(0, 'STATIC', 'PySAS regression window', 0x10cf0000, 0, 0, 200, 100, None, None, None, None)
        self.assertTrue(hwnd)
        try:
            self.assertIn(hwnd, process_windows(os.getpid()))
            brand_window(hwnd, ROOT, ROOT / 'ui/icon.ico')
            self.assertEqual(window_property(hwnd, 5), app_id(ROOT))
            self.assertTrue(user.SendMessageW(hwnd, 0x7f, 0, 0))
            self.assertTrue(user.SendMessageW(hwnd, 0x7f, 1, 0))
        finally:
            user.DestroyWindow(hwnd)

    def test_pythonw_server_starts_without_console_and_quits(self):
        self.run_hidden_server(['--no-browser'])

    def test_real_browser_window_starts_and_closes_with_hidden_server(self):
        from ui_support import app_browser_candidates
        if not app_browser_candidates():
            self.skipTest('Edge/Chrome not installed')
        self.run_hidden_server([])

    def test_hidden_server_launches_sas_worker_and_cscript_in_real_hidden_console(self):
        self.run_hidden_server(['--no-browser'], worker_probe=True)

    def run_hidden_server(self, options, worker_probe=False):
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copy2(ROOT / 'pysas.py', root / 'pysas.py')
            if worker_probe:
                (root / 'job.sas').write_text('data test; run;')
                (root / 'project.egp').touch()
                # Exercise the production execute_eg Popen and a real cscript.exe.
                # Only replace the SAS COM script, unavailable on hosted CI.
                fixture = ROOT / 'tests' / 'fixtures' / 'console_probe_engine.py'
                with (root / 'pysas.py').open('a', encoding='utf-8') as output:
                    output.write("\n" + fixture.read_text(encoding='utf-8'))
            ready = root / 'ready'
            process = subprocess.Popen([str(pythonw), str(ROOT / 'pysas_ui.py'), '--workspace', str(root),
                                        '--ready-file', str(ready), *options], creationflags=subprocess.DETACHED_PROCESS)
            try:
                deadline = time.monotonic() + 50
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(.1)
                log = root / '.pysas-ui/launcher.log'
                self.assertTrue(ready.exists(), log.read_text() if log.exists() else 'No startup log')
                if not options:
                    from windows_app import process_windows, window_property
                    identities = []
                    for hwnd in process_windows(None):
                        try:
                            identities.append(window_property(hwnd, 5))
                        except OSError:
                            pass
                    self.assertIn(app_id(root), identities, log.read_text())
                url = ready.read_text()
                with urlopen(url + '/api/state', timeout=5) as response:
                    state = json.load(response)
                if worker_probe:
                    headers = {'Content-Type': 'application/json', 'X-PySAS-Token': state['token']}
                    request = Request(url + '/api/launch', data=json.dumps({'action': 'run', 'program': 'job.sas', 'template': 'project.egp'}).encode(), headers=headers)
                    with urlopen(request, timeout=10) as response:
                        identifier = json.load(response)['id']
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        with urlopen(url + '/api/state', timeout=5) as response:
                            state = json.load(response)
                        item = next(c for c in state['commands'] if c['id'] == identifier)
                        if item['status'] != 'RUNNING':
                            break
                        time.sleep(.1)
                    console = (root / '.pysas-ui' / (identifier + '.txt')).read_text(encoding='utf-8')
                    self.assertEqual(item['status'], 'SUCCESS', console)
                    self.assertTrue(item['runtime']['console'])
                    probe = json.loads((root / 'console-probe.json').read_text())
                    self.assertTrue(probe['console_window'])
                    self.assertFalse(probe['visible'])
                    self.assertTrue(probe['console_input'])
                    self.assertGreaterEqual(probe['console_processes'], 2, probe)
                    self.assertTrue(any('cscript.exe' in name.lower() for name in probe['process_images']), probe)
                req = Request(url + '/api/quit', data=b'{}', headers={'Content-Type': 'application/json', 'X-PySAS-Token': state['token']})
                with urlopen(req, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(process.wait(timeout=20), 0)
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()


if __name__ == '__main__': unittest.main()

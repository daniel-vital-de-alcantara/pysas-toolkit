"""Local uploads and Windows keep-awake support for the optional UI."""
from __future__ import annotations
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

UPLOAD_LIMIT = 512 * 1024 * 1024
UPLOAD_EXTENSIONS = {'.sas', '.egp', '.xlsx', '.csv', '.txt', '.log', '.sasbundle'}


def receive_upload(folder, name, stream, length):
    if not name or Path(name).name != name or '/' in name or '\\' in name or name.startswith('.') or ':' in name:
        raise ValueError('Choose a plain filename, without folders.')
    if Path(name).suffix.lower() not in UPLOAD_EXTENSIONS:
        raise ValueError('Supported uploads: SAS, EGP, XLSX, CSV, TXT, LOG and SASBUNDLE files.')
    if not 0 <= length <= UPLOAD_LIMIT:
        raise ValueError('Each file must be 512 MB or smaller.')
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError('The upload folder does not exist.')
    target = folder / name
    if target.exists() or target.is_symlink():
        raise FileExistsError('A file named ' + name + ' already exists. Rename it or choose another folder.')
    temp = folder / ('.pysas-upload-' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as handle:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Upload was interrupted; the incomplete file was discarded.')
                handle.write(chunk)
                remaining -= len(chunk)
        if target.exists() or target.is_symlink():
            raise FileExistsError('A file with this name already exists.')
        temp.rename(target)
    finally:
        temp.unlink(missing_ok=True)
    return {'name': name, 'path': str(target), 'size': length}


class KeepAwake:
    def __init__(self, set_state=None):
        self.supported = os.name == 'nt' or set_state is not None
        self.set_state = set_state
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.enabled = False
        self.error = ''

    def status(self):
        return {'supported': self.supported, 'enabled': self.enabled, 'error': self.error}

    def set(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Keep-awake must be true or false.')
        if enabled and not self.supported:
            raise ValueError('Keep PC awake is available on Windows.')
        with self.lock:
            if not enabled:
                self.stop_event.set()
                if self.thread:
                    self.thread.join(timeout=3)
                return self.status()
            if self.enabled:
                return self.status()
            if self.thread and self.thread.is_alive():
                raise ValueError('Keep-awake is still shutting down. Try again.')
            self.stop_event = threading.Event()
            ready = threading.Event()
            self.error = ''
            def run():
                function = self.set_state
                try:
                    if function is None:
                        import ctypes
                        function = ctypes.windll.kernel32.SetThreadExecutionState
                        function.argtypes = [ctypes.c_uint]
                        function.restype = ctypes.c_uint
                    if not function(0x80000003):
                        raise OSError('Windows did not accept the keep-awake request.')
                    self.enabled = True
                    ready.set()
                    self.stop_event.wait()
                except Exception as exc:
                    self.error = str(exc)
                finally:
                    if self.enabled and function is not None:
                        function(0x80000000)
                    self.enabled = False
                    ready.set()
            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()
            if not ready.wait(timeout=3):
                self.stop_event.set()
                raise ValueError('Windows did not respond to the keep-awake request.')
            if self.error:
                raise ValueError(self.error)
            return self.status()

    def close(self):
        self.set(False)


def app_browser_candidates(environ=None, which=None):
    """Find stable Edge/Chrome installs without changing the default browser."""
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    candidates = []
    for vendor, executable in [('Microsoft/Edge', 'msedge.exe'), ('Google/Chrome', 'chrome.exe')]:
        for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            directory = environ.get(variable)
            if directory:
                candidates.append(Path(directory) / vendor / 'Application' / executable)
        discovered = which(executable)
        if discovered:
            candidates.append(Path(discovered))
    return list(dict.fromkeys(path for path in candidates if path.is_file()))


def launch_app_window(url, profile, candidates=None, popen=None):
    """Open the local workbench without browser tabs or an address bar."""
    from urllib.parse import urlsplit
    address = urlsplit(url)
    if address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port:
        raise ValueError('App windows must open the local workbench address.')
    profile = Path(profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    candidates = app_browser_candidates() if candidates is None else candidates
    popen = subprocess.Popen if popen is None else popen
    for executable in candidates:
        try:
            return popen([str(executable), '--app=' + url, '--user-data-dir=' + str(profile),
                          '--disable-background-mode', '--no-first-run', '--no-default-browser-check', '--window-size=1360,900'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
    return None

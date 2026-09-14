"""Local uploads and Windows keep-awake support for the optional UI."""
from __future__ import annotations
import os
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

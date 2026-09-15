"""Windows taskbar identity for the optional browser-hosted PySAS window."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import hashlib
from functools import lru_cache
from pathlib import Path
import uuid
import subprocess
import sys


def app_id(workspace):
    key = str(Path(workspace).resolve()).casefold().encode('utf-8')
    return 'PySAS.Workbench.' + hashlib.sha256(key).hexdigest()[:16]


class GUID(C.Structure):
    _fields_ = [('data', C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class PropertyKey(C.Structure):
    _fields_ = [('fmtid', GUID), ('pid', W.DWORD)]


class ValueUnion(C.Union):
    _fields_ = [('text', C.c_wchar_p), ('padding', C.c_byte * (16 if C.sizeof(C.c_void_p) == 8 else 8))]


class PropVariant(C.Structure):
    _fields_ = [('vt', C.c_ushort), ('reserved', C.c_ushort * 3), ('value', ValueUnion)]


def window_property(hwnd, property_id, value=None):
    """Read/write a window's AppUserModel string property through IPropertyStore."""
    shell = C.WinDLL('shell32', use_last_error=True)
    ole = C.WinDLL('ole32')
    initialized = ole.CoInitializeEx(None, 2) >= 0
    store = C.c_void_p()
    iid = GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
    key = PropertyKey(GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), property_id)
    shell.SHGetPropertyStoreForWindow.argtypes = [W.HWND, C.POINTER(GUID), C.POINTER(C.c_void_p)]
    shell.SHGetPropertyStoreForWindow.restype = C.c_long
    hr = shell.SHGetPropertyStoreForWindow(hwnd, C.byref(iid), C.byref(store))
    if hr < 0:
        if initialized: ole.CoUninitialize()
        raise OSError('Cannot access window taskbar properties: ' + hex(hr & 0xffffffff))
    table = C.cast(store, C.POINTER(C.POINTER(C.c_void_p))).contents
    def call(index, *types):
        return C.WINFUNCTYPE(C.c_long, C.c_void_p, *types)(table[index])
    prop = PropVariant()
    try:
        if value is None:
            hr = call(5, C.POINTER(PropertyKey), C.POINTER(PropVariant))(store, C.byref(key), C.byref(prop))
            if hr < 0: raise OSError('Cannot read window taskbar property')
            answer = prop.value.text if prop.vt == 31 else None
            ole.PropVariantClear(C.byref(prop))
            return answer
        prop.vt = 31  # VT_LPWSTR; buffer is owned by ctypes for this call.
        prop.value.text = value
        hr = call(6, C.POINTER(PropertyKey), C.POINTER(PropVariant))(store, C.byref(key), C.byref(prop))
        if hr < 0: raise OSError('Cannot set window taskbar property')
    finally:
        call(2)(store)  # IUnknown.Release
        if initialized: ole.CoUninitialize()


def process_windows(pid):
    user = C.WinDLL('user32', use_last_error=True)
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    result = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    @callback_type
    def collect(hwnd, unused):
        owner = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, C.byref(owner))
        if (pid is None or owner.value == pid) and user.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.EnumWindows(collect, 0)
    return result


@lru_cache(maxsize=16)
def load_icon(icon, size):
    user = C.WinDLL('user32', use_last_error=True)
    user.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
    user.LoadImageW.restype = W.HANDLE
    handle = user.LoadImageW(None, str(icon), 1, size, size, 0x10)
    if not handle: raise OSError('Cannot load PySAS taskbar icon')
    return handle


def brand_window(hwnd, workspace, icon):
    user = C.WinDLL('user32', use_last_error=True)
    user.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
    user.LoadImageW.restype = W.HANDLE
    user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
    user.SendMessageTimeoutW.restype = W.LPARAM
    # Identity is specific to this workspace, separating different extracted versions too.
    launcher = Path(__file__).resolve().parent / "pysas_ui.py"
    window_property(hwnd, 2, subprocess.list2cmdline([str(Path(sys.executable).with_name("pythonw.exe")), str(launcher), "--workspace", str(Path(workspace).resolve())]))
    window_property(hwnd, 3, 'PySAS Workbench')
    window_property(hwnd, 4, str(Path(icon).resolve()))
    window_property(hwnd, 5, app_id(workspace))
    for kind, size in ((0, 16), (1, 32)):
        handle = load_icon(str(icon), size)
        if not handle: raise OSError('Cannot load PySAS taskbar icon')
        result = C.c_size_t()
        user.SendMessageTimeoutW(hwnd, 0x80, kind, handle, 2, 2000, C.byref(result))


def close_windows(pid):
    user = C.WinDLL('user32', use_last_error=True)
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    for hwnd in process_windows(pid):
        user.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE, only this app's browser process.

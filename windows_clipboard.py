"""Copy an existing file using the Windows shell clipboard, like Explorer Copy."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import struct
import threading
import time

_LOCK = threading.Lock()


def file_drop_payload(path):
    # DROPFILES: DWORD offset, POINT (two LONGs), BOOL fNC, BOOL fWide.
    # Fixed Windows layout (20 bytes), followed by a UTF-16 file list.
    name = str(path)
    if not name or '\0' in name:
        raise ValueError('Invalid clipboard filename.')
    return struct.pack('<IiiII', 20, 0, 0, 0, 1) + (name + '\0\0').encode('utf-16-le')


def copy_file(path):
    if os.name != 'nt':
        raise ValueError('Copy file is available on Windows. Use Download on this computer.')
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('The selected file no longer exists.')
    with _LOCK:
        _copy_windows(path)


def _copy_windows(path):
    user = C.WinDLL('user32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                    C.c_int, C.c_int, C.c_int, C.c_int,
                                    W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
    user.CreateWindowExW.restype = W.HWND
    user.DestroyWindow.argtypes = [W.HWND]; user.DestroyWindow.restype = W.BOOL
    user.OpenClipboard.argtypes = [W.HWND]; user.OpenClipboard.restype = W.BOOL
    user.CloseClipboard.argtypes = []; user.CloseClipboard.restype = W.BOOL
    user.EmptyClipboard.argtypes = []; user.EmptyClipboard.restype = W.BOOL
    user.SetClipboardData.argtypes = [W.UINT, W.HANDLE]; user.SetClipboardData.restype = W.HANDLE
    user.RegisterClipboardFormatW.argtypes = [W.LPCWSTR]; user.RegisterClipboardFormatW.restype = W.UINT
    kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]; kernel.GetModuleHandleW.restype = W.HMODULE
    kernel.GlobalAlloc.argtypes = [W.UINT, C.c_size_t]; kernel.GlobalAlloc.restype = W.HGLOBAL
    kernel.GlobalLock.argtypes = [W.HGLOBAL]; kernel.GlobalLock.restype = C.c_void_p
    kernel.GlobalUnlock.argtypes = [W.HGLOBAL]; kernel.GlobalUnlock.restype = W.BOOL
    kernel.GlobalFree.argtypes = [W.HGLOBAL]; kernel.GlobalFree.restype = W.HGLOBAL
    # OpenClipboard(NULL) followed by EmptyClipboard leaves no owner and can
    # make SetClipboardData fail. Use a hidden message-only window on this thread.
    hwnd = user.CreateWindowExW(0, 'STATIC', 'PySAS file clipboard', 0, 0, 0, 0, 0,
                                -3, None, kernel.GetModuleHandleW(None), None)
    if not hwnd:
        raise C.WinError(C.get_last_error())
    allocated = []
    opened = False
    try:
        effect_format = user.RegisterClipboardFormatW('Preferred DropEffect')
        if not effect_format:
            raise C.WinError(C.get_last_error())
        for format_id, payload in ((15, file_drop_payload(path)),  # CF_HDROP
                                   (effect_format, struct.pack('<I', 1))):  # DROPEFFECT_COPY
            handle = kernel.GlobalAlloc(0x42, len(payload))  # GMEM_MOVEABLE | GMEM_ZEROINIT
            if not handle:
                raise C.WinError(C.get_last_error())
            allocated.append([format_id, handle])
            address = kernel.GlobalLock(handle)
            if not address:
                raise C.WinError(C.get_last_error())
            try:
                C.memmove(address, payload, len(payload))
            finally:
                kernel.GlobalUnlock(handle)
        deadline = time.monotonic() + 1.5
        while not user.OpenClipboard(hwnd):
            if time.monotonic() >= deadline:
                raise OSError('The Windows clipboard is busy. Try Copy file again.')
            time.sleep(.05)
        opened = True
        if not user.EmptyClipboard():
            raise C.WinError(C.get_last_error())
        for entry in allocated:
            if not user.SetClipboardData(*entry):
                raise C.WinError(C.get_last_error())
            entry[1] = None  # Ownership transfers to Windows; never free it ourselves.
    finally:
        if opened:
            user.CloseClipboard()
        for _, handle in allocated:
            if handle:
                kernel.GlobalFree(handle)
        user.DestroyWindow(hwnd)

# Appended to a workspace engine by the Windows integration test only.
VBS = r'''Option Explicit
Dim fso, folder, ready, gate, file, i
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.Arguments(1))
ready = folder & "\bridge-ready"
gate = folder & "\bridge-finish"
Set file = fso.CreateTextFile(ready, True)
file.Close
For i = 1 To 200
  If fso.FileExists(gate) Then Exit For
  WScript.Sleep 50
Next
If Not fso.FileExists(gate) Then WScript.Quit 42
WScript.Echo "Console bridge completed"
'''
_console_probe_execute = execute_eg

def execute_eg(*args):
    import ctypes
    from ctypes import wintypes as W
    def probe():
        ready = ROOT_DIR / 'bridge-ready'
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetConsoleWindow.restype = W.HWND
        kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(W.DWORD), W.DWORD]
        kernel.GetStdHandle.argtypes = [W.DWORD]
        kernel.GetStdHandle.restype = W.HANDLE
        kernel.GetConsoleMode.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
        kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        kernel.OpenProcess.restype = W.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
        kernel.CloseHandle.argtypes = [W.HANDLE]
        user = ctypes.WinDLL('user32')
        user.IsWindowVisible.argtypes = [W.HWND]
        hwnd = kernel.GetConsoleWindow()
        mode = W.DWORD()
        console_input = bool(kernel.GetConsoleMode(kernel.GetStdHandle(-10 & 0xffffffff), ctypes.byref(mode)))
        pids = (W.DWORD * 64)()
        count = kernel.GetConsoleProcessList(pids, 64)
        images = []
        for pid in list(pids)[:min(count, 64)]:
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    size = W.DWORD(32768)
                    name = ctypes.create_unicode_buffer(size.value)
                    if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                        images.append(name.value)
                finally:
                    kernel.CloseHandle(handle)
        (ROOT_DIR / 'console-probe.json').write_text(json.dumps(dict(console_window=bool(hwnd), visible=bool(user.IsWindowVisible(hwnd)), console_input=console_input, console_processes=count, process_images=images)))
        (ROOT_DIR / 'bridge-finish').touch()
    observer = threading.Thread(target=probe)
    observer.start()
    try:
        return _console_probe_execute(*args)
    finally:
        observer.join(10)

from pathlib import Path
import ctypes as C
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

from windows_clipboard import copy_file, file_drop_payload

ROOT = Path(__file__).resolve().parents[1]


class FileClipboardTests(unittest.TestCase):
    def test_unicode_file_list_has_windows_layout_and_double_terminator(self):
        name = 'C:\\Runs\\café 年度\\job.log'
        payload = file_drop_payload(name)
        self.assertEqual(struct.unpack('<IiiII', payload[:20]), (20, 0, 0, 0, 1))
        self.assertEqual(payload[20:].decode('utf-16-le'), name+'\0\0')
        with self.assertRaises(ValueError): file_drop_payload('bad\0name')

    @unittest.skipIf(os.name == 'nt', 'Non-Windows behavior')
    def test_unsupported_platform_does_not_fall_back_to_copying_text(self):
        with self.assertRaisesRegex(ValueError, 'Windows'):
            copy_file(ROOT/'README.md')

    @unittest.skipUnless(os.name == 'nt', 'Real Windows shell clipboard')
    def test_other_process_receives_file_after_writer_exits_without_text_conversion(self):
        # Tests run on an isolated Windows CI desktop. The consumer is .NET,
        # independent of our ctypes producer, and runs after its window exits.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'café 年度 result.xlsx'
            contents = bytes(range(256))*4
            path.write_bytes(contents)
            producer = subprocess.run([sys.executable, '-c',
                'from windows_clipboard import copy_file; import sys; copy_file(sys.argv[1])', str(path)],
                cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(producer.returncode, 0, producer.stderr)
            user = C.WinDLL('user32', use_last_error=True)
            kernel = C.WinDLL('kernel32', use_last_error=True)
            try:
                consumer = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command',
                    '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '
                    'Add-Type -AssemblyName System.Windows.Forms; '
                    '$f=[System.Windows.Forms.Clipboard]::GetFileDropList(); '
                    '[pscustomobject]@{files=@($f); text=[System.Windows.Forms.Clipboard]::ContainsText()} | ConvertTo-Json -Compress'],
                    capture_output=True, encoding='utf-8', timeout=20)
                self.assertEqual(consumer.returncode, 0, consumer.stderr)
                received = json.loads(consumer.stdout.lstrip('\ufeff'))
                self.assertEqual(received['files'], [str(path.resolve())])
                self.assertFalse(received['text'])
                self.assertEqual(path.read_bytes(), contents)
                user.RegisterClipboardFormatW.argtypes = [C.c_wchar_p]
                user.RegisterClipboardFormatW.restype = C.c_uint
                user.GetClipboardData.argtypes = [C.c_uint]; user.GetClipboardData.restype = C.c_void_p
                kernel.GlobalLock.argtypes = [C.c_void_p]; kernel.GlobalLock.restype = C.c_void_p
                kernel.GlobalUnlock.argtypes = [C.c_void_p]
                self.assertTrue(user.OpenClipboard(None))
                try:
                    handle = user.GetClipboardData(user.RegisterClipboardFormatW('Preferred DropEffect'))
                    self.assertTrue(handle)
                    address = kernel.GlobalLock(handle)
                    self.assertTrue(address)
                    try: self.assertEqual(C.c_uint32.from_address(address).value, 1)
                    finally: kernel.GlobalUnlock(handle)
                finally: user.CloseClipboard()
            finally:
                if user.OpenClipboard(None):
                    user.EmptyClipboard(); user.CloseClipboard()

from pathlib import Path
import io
import tempfile
import threading
import unittest
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_support import KeepAwake, receive_upload


class UploadTests(unittest.TestCase):
    def test_complete_upload_collision_and_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receive_upload(root, 'job.sas', io.BytesIO(b'run;'), 4)
            self.assertEqual((root / 'job.sas').read_bytes(), b'run;')
            with self.assertRaises(FileExistsError):
                receive_upload(root, 'job.sas', io.BytesIO(b'edit'), 4)
            with self.assertRaises(ValueError):
                receive_upload(root, 'partial.sas', io.BytesIO(b'x'), 8)
            self.assertFalse((root / 'partial.sas').exists())
            self.assertFalse(list(root.glob('*.tmp')))
            self.assertEqual((root / 'job.sas').read_bytes(), b'run;')

    def test_upload_rejects_paths_and_executable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ['../evil.sas', 'sub/evil.sas', 'sub\\evil.sas', 'pysas.py', '.hidden.sas', 'stream:sas.txt']:
                with self.assertRaises(ValueError, msg=name):
                    receive_upload(Path(directory), name, io.BytesIO(), 0)


class KeepAwakeTests(unittest.TestCase):
    def test_enable_disable_and_cleanup_use_same_thread(self):
        calls = []
        def set_state(flags):
            calls.append((threading.get_ident(), flags)); return 1
        awake = KeepAwake(set_state)
        self.assertTrue(awake.set(True)['enabled'])
        awake.set(True)
        self.assertEqual(len(calls), 1)
        awake.close()
        self.assertFalse(awake.status()['enabled'])
        self.assertEqual([flags for _, flags in calls], [0x80000003, 0x80000000])
        self.assertEqual(calls[0][0], calls[1][0])

    def test_windows_rejection_is_reported(self):
        awake = KeepAwake(lambda flags: 0)
        with self.assertRaisesRegex(ValueError, 'did not accept'):
            awake.set(True)
        self.assertFalse(awake.status()['enabled'])


if __name__ == '__main__': unittest.main()

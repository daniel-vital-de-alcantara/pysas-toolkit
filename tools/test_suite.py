"""Run the normal suite, exposing failure tracebacks as GitHub check annotations."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def annotation(text):
    return text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, traceback in result.failures + result.errors:
        print('::error title=PySAS test failure::' + annotation(str(test) + '\n' + traceback), flush=True)
    sys.exit(0 if result.wasSuccessful() else 1)

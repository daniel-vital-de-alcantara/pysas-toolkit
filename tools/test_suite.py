"""Run the normal suite, exposing failure tracebacks as GitHub check annotations."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]


def annotation(text):
    return text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    # Keep the reporter outside unittest: abrupt exits/encoding errors in tests
    # must still leave a readable annotation on the public check.
    print('::notice::Starting isolated Python test suite', flush=True)
    try:
        with tempfile.TemporaryFile() as output:
            isolation = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            result = subprocess.run([sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                                    cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=900,
                                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, **isolation)
            output.seek(0); text = output.read().decode('utf-8', errors='replace')
        print(text, flush=True)
        if result.returncode:
            print('::error title=PySAS test failure::' + annotation(text[-45000:]), flush=True)
        sys.exit(0 if result.returncode == 0 else 1)
    except Exception:
        print('::error title=PySAS test runner failure::' + annotation(traceback.format_exc()), flush=True)
        raise

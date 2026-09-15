"""Start a hidden Windows server, exiting the launcher only after its window opens."""
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    root = Path(__file__).resolve().parent
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise RuntimeError('This Python installation has no pythonw.exe. Use START_PYSAS_CONSOLE.bat.')
    storage = root / '.pysas-ui'; storage.mkdir(exist_ok=True)
    ready = storage / ('ready-' + uuid.uuid4().hex)
    log = storage / 'launcher.log'
    with log.open('ab') as output:
        process = subprocess.Popen([str(pythonw), str(root / 'pysas_ui.py'), '--ready-file', str(ready), *sys.argv[1:]],
                                   cwd=root, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   creationflags=subprocess.DETACHED_PROCESS)
    try:
        for _ in range(600):
            if ready.is_file():
                print('PySAS is open. This launcher can close.')
                return 0
            if process.poll() is not None:
                raise RuntimeError('PySAS could not start. See ' + str(log))
            time.sleep(.1)
        raise RuntimeError('The app has not confirmed startup. See ' + str(log) + '. Do not launch another copy yet.')
    finally:
        ready.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc))
        sys.exit(1)

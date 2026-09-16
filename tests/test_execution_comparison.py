"""Regression cases from the 0.3.2/UI hang investigation; no SAS server required."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pysas_ui as ui
from ui_worker import load_engine


class ExecutionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy2(ROOT / 'pysas.py', self.root / 'pysas.py')
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        self.app.awake.close()
        self.temp.cleanup()

    def test_schedule_defaults_to_ten_workers(self):
        from types import SimpleNamespace
        with patch.object(ui, 'os', SimpleNamespace(name='nt')):
            _, args = self.app.arguments({'action': 'schedule'})
            self.assertEqual(args[args.index('--workers') + 1], '10')
            with self.assertRaises(ValueError):
                self.app.arguments({'action': 'schedule', 'workers': '0'})
            _, args = self.app.arguments({'action': 'schedule', 'workers': '3'})
            self.assertEqual(args[args.index('--workers') + 1], '3')

    def test_scheduler_has_one_engine_even_if_old_browser_sends_engine_selection(self):
        from unittest.mock import Mock
        for old_value in [None, '0.3.2', 'current']:
            data = {'action': 'schedule', 'engine': old_value}
            with patch.object(self.app, 'arguments', return_value=('schedule', ['schedule'])), patch.object(ui.subprocess, 'Popen', return_value=Mock()) as launch, patch.object(ui.threading, 'Thread'):
                identifier = self.app.launch(data)['id']
            self.assertEqual(Path(launch.call_args.args[0][3]).name, 'pysas.py')
            self.assertIsNone(launch.call_args.kwargs['stdin'])
            item = self.app.commands[identifier]
            self.app.event(item, dict(event='plan', tasks=[dict(task_id='setup', program='setup', always_run=True)]))
            self.assertEqual(item['tasks']['setup']['status'], 'ALWAYS_RUN_DEFINITION')
        self.app.processes.clear()

    def test_ui_watcher_stop_uses_control_file_and_finishes_active_job(self):
        (self.root / 'pysas.py').write_text("""import concurrent.futures, time
from pathlib import Path
VERSION = 'fake'
def execute_eg(*a): return (0, '')
def run_job(source):
    time.sleep(.6)
    return dict(name=source.name, status='SUCCESS', elapsed=.6, run_dir=source.parent)
def scheduler_task(*a): pass
def load_schedule(*a): return []
def write_summary(*a): pass
def main(args):
    executor = concurrent.futures.ThreadPoolExecutor(1)
    executor.submit(run_job, Path(__file__).with_name('test.sas'))
    try:
        while True: time.sleep(.05)
    except KeyboardInterrupt:
        return 130
    finally:
        executor.shutdown(wait=True)
""", encoding='utf-8')
        with patch.object(self.app, 'arguments', return_value=('watch', ['runner', 'watch'])):
            identifier = self.app.launch({'action': 'watch'})['id']
        process = self.app.processes[identifier]
        try:
            self.assertIsNone(process.stdin)
            deadline = time.monotonic() + 10
            while not self.app.commands[identifier]['tasks'] and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(self.app.commands[identifier]['tasks'])
            self.app.stop(identifier)
            self.assertEqual(process.wait(timeout=10), 130)
            while identifier in self.app.processes and time.monotonic() < deadline:
                time.sleep(.02)
            item = self.app.commands[identifier]
            self.assertEqual(item['status'], 'STOPPED')
            self.assertEqual(next(iter(item['tasks'].values()))['status'], 'SUCCESS')
        finally:
            if process.poll() is None:
                process.kill(); process.wait()

    def test_cli_can_use_workbook_workers_and_explicit_ui_default(self):
        engine = load_engine(ROOT / 'pysas.py')
        self.assertIsNone(engine.parser().parse_args(['schedule']).workers)
        self.assertEqual(engine.parser().parse_args(['schedule', '--workers', '10']).workers, 10)

    def test_progress_records_stage_on_running_task_without_creating_setup_jobs(self):
        item = dict(id='progress', tasks={})
        self.app.event(item, dict(event='start', key='job', name='Realised', time=100))
        self.app.event(item, dict(event='progress', key='job', time=105, phase='preparing', progress='Appending shared setup: Libraries'))
        self.app.event(item, dict(event='progress', key='job', time=107, phase='executing', progress='Running: Realised'))
        self.assertEqual(list(item['tasks']), ['job'])
        task = item['tasks']['job']
        self.assertEqual(task['phase'], 'executing')
        self.assertEqual(task['started'], 100)
        self.assertEqual(task['phase_started'], 107)

    def test_bridge_progress_waits_for_complete_lines_and_ignores_normal_output(self):
        engine = load_engine(ROOT / 'pysas.py')
        log = self.root / 'console.txt'
        log.write_bytes(b'ordinary output\nPYSAS_STAGE|preparing|Appending lib\nPYSAS_STAGE|execut')
        with patch.object(engine, 'report_progress') as report:
            offset, pending = engine.forward_bridge_progress(log, 0, b'', self.root)
            report.assert_called_once_with(self.root, 'preparing', 'Appending lib')
            with log.open('ab') as output:
                output.write(b'ing|Running Realised\r\n')
            engine.forward_bridge_progress(log, offset, pending, self.root)
            self.assertEqual(report.call_args.args, (self.root, 'executing', 'Running Realised'))

    def test_protected_source_is_rejected_before_eg_launch(self):
        engine = load_engine(ROOT / 'pysas.py')
        engine.ROOT_DIR = self.root
        source = self.root / 'protected.sas'
        source.write_bytes(b'\x00MSMAMARPCRYPT' + bytes(100))
        with patch.object(engine, 'execute_eg') as execute:
            with self.assertRaisesRegex(ValueError, 'encrypted/protected'):
                engine.run_job(source, self.root/'p.egp', False, None, False)
        execute.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'encrypted/protected'):
            self.app.preview('protected.sas')

    def test_worker_finishes_even_when_ui_reader_is_blocked(self):
        # Enough output and events to fill Windows/POSIX pipes; hold the UI lock.
        (self.root / 'pysas.py').write_text('''from pathlib import Path
VERSION = "fake"
def run_job(source, *a, **k):
    return dict(name=source.name, status="SUCCESS", elapsed=0, run_dir=source.parent)
def scheduler_task(*a): pass
def load_schedule(*a): pass
def execute_eg(*a): pass
def write_summary(*a): pass
def main(args):
    for i in range(1500):
        print("x" * 1000)
        run_job(Path(__file__).with_name("job.sas"))
    return 0
''', encoding='utf-8')
        with self.app.lock:
            identifier = self.app.launch({'action': 'bundle-verify'})['id']
            process = self.app.processes[identifier]
            try:
                self.assertEqual(process.wait(timeout=15), 0)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
                self.fail('SAS worker depended on the UI draining output')
            self.assertGreater((self.app.storage / (identifier+'.txt')).stat().st_size, 1000000)
        deadline = time.monotonic() + 15
        while identifier in self.app.processes and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertNotIn(identifier, self.app.processes)
        self.assertEqual(self.app.commands[identifier]['status'], 'SUCCESS')

    def test_history_write_failure_does_not_leave_finished_worker_running(self):
        from types import SimpleNamespace
        item = dict(id='failedsave', action='schedule', started=time.time(), status='RUNNING', tasks={})
        self.app.commands[item['id']] = item
        process = SimpleNamespace(poll=lambda: 0, wait=lambda: 0, stdin=io.StringIO())
        self.app.processes[item['id']] = process
        events = self.root / 'events.jsonl'
        events.write_text(json.dumps(dict(event='start', key='A', time=time.time()))+'\n'+json.dumps(dict(event='finish', key='A', time=time.time(), status='SUCCESS'))+'\n')
        with patch.object(self.app, 'save', side_effect=OSError('history is locked')):
            self.app.monitor_worker(item['id'], process, events)
        self.assertEqual(item['status'], 'SUCCESS')
        self.assertEqual(item['tasks']['A']['status'], 'SUCCESS')
        self.assertNotIn(item['id'], self.app.processes)
        self.assertIn('history', item['message'])

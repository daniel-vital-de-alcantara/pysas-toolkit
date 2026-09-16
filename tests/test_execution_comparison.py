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

    def test_original_engine_is_byte_identical_to_published_032(self):
        self.assertEqual(hashlib.sha256((ROOT / 'pysas_0_3_2.py').read_bytes()).hexdigest(),
                         '27a21be8e39a87823b481e00d8f1e0e4bfba7add9995c9a70ea4310fa668dd33')

    def test_schedule_default_does_not_override_workbook_parallelism(self):
        from types import SimpleNamespace
        with patch.object(ui, 'os', SimpleNamespace(name='nt')):
            _, args = self.app.arguments({'action': 'schedule'})
            self.assertNotIn('--workers', args)
            _, args = self.app.arguments({'action': 'schedule', 'workers': '0'})
            self.assertNotIn('--workers', args)
            _, args = self.app.arguments({'action': 'schedule', 'workers': '3'})
            self.assertEqual(args[args.index('--workers') + 1], '3')

    def test_scheduler_defaults_to_original_engine_and_current_is_explicit(self):
        from unittest.mock import Mock
        for engine, filename in [(None, 'pysas_0_3_2.py'), ('current', 'pysas.py')]:
            data = {'action': 'schedule'}
            if engine:
                data['engine'] = engine
            with patch.object(self.app, 'arguments', return_value=('schedule', ['schedule'])), patch.object(ui.subprocess, 'Popen', return_value=Mock()) as launch, patch.object(ui.threading, 'Thread'):
                identifier = self.app.launch(data)['id']
            self.assertEqual(Path(launch.call_args.args[0][3]).name, filename)
            self.assertIsNone(launch.call_args.kwargs['stdin'])
            item = self.app.commands[identifier]
            self.assertEqual(item['engine'], engine or '0.3.2')
            self.app.event(item, dict(event='plan', tasks=[dict(task_id='setup', program='setup', always_run=True)]))
            self.assertEqual(item['tasks']['setup']['status'], 'PENDING' if engine is None else 'ALWAYS_RUN_DEFINITION')
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

    def test_original_and_current_schedule_have_explicitly_different_setup_semantics(self):
        (self.root / 'book.xlsx').touch()
        (self.root / 'project.egp').touch()
        import argparse
        for filename, expected in [('pysas_0_3_2.py', ['setup', 'job']), ('pysas.py', ['job'])]:
            engine = load_engine(ROOT / filename)
            engine.ROOT_DIR = self.root
            tasks = [dict(task_id=name, program=name, always_run=name == 'setup', skip=False,
                          depends_on=[] if name == 'setup' else ['setup'], max_parallel=1,
                          row_start=1, row_end=3, stop_process_on_error=False) for name in ['setup', 'job']]
            calls = []
            def execute(task, *_):
                calls.append(task['task_id'])
                if filename == 'pysas.py':
                    self.assertEqual([t['task_id'] for t in task['_always_run']], ['setup'])
                else:
                    self.assertNotIn('_always_run', task)
                return dict(task, status='SUCCESS', elapsed=0)
            with patch.object(engine, 'load_schedule', return_value=tasks), patch.object(engine, 'scheduler_task', execute), patch.object(engine, 'write_summary'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(engine.schedule_run(argparse.Namespace(workbook=str(self.root/'book.xlsx'), project=str(self.root/'project.egp'), workers=None, no_notify=True)), 0)
            self.assertEqual(calls, expected)

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

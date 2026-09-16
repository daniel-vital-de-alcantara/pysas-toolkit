"""Dependency barriers and cancellation of a whole schedule, including launch races."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_worker import load_engine, observe
import pysas_ui as ui


def task(name, deps=(), skip=False):
    return dict(task_id=name, program=name, depends_on=list(deps), skip=skip, always_run=False,
                max_parallel=None, stop_process_on_error=False, stop_program_on_error=False,
                section='', row_start=None, row_end=None)


class ScheduleControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = load_engine(ROOT/'pysas.py')
        self.engine.ROOT_DIR = self.root
        (self.root/'Schedule.xlsx').touch(); (self.root/'project.egp').touch()
        self.args = argparse.Namespace(workbook=str(self.root/'Schedule.xlsx'), project=str(self.root/'project.egp'),
                                       workers=10, no_notify=True, cancel_file=str(self.root/'schedule.stop'))
        (self.root/"pysas.py").touch()
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        self.app.processes.clear()
        self.app.awake.close()
        self.temp.cleanup()

    def test_skipped_chains_wait_for_every_ancestor_in_any_workbook_order(self):
        cases = [([task('A'), task('B', ['A'], True), task('C', ['B'])], {'A'}, {'A', 'C'}),
                 ([task('C', ['S2']), task('S2', ['S1'], True), task('S1', ['A'], True), task('A')], {'A'}, {'A', 'C'}),
                 ([task('C', ['S2']), task('S2', ['S1', 'E'], True), task('S1', ['A'], True), task('A'), task('E')], {'A', 'E'}, {'A', 'E', 'C'})]
        for definitions, roots, expected in cases:
            with self.subTest(definitions=definitions):
                release = threading.Event(); coordinator_waiting = threading.Event()
                scheduled, summary, results = [], [], []
                executor = self.engine.concurrent.futures.ThreadPoolExecutor
                real_submit = executor.submit
                real_wait = self.engine.concurrent.futures.wait
                def submit(pool, function, definition, *args):
                    scheduled.append(definition['task_id'])
                    return real_submit(pool, function, definition, *args)
                def wait(*args, **kwargs):
                    coordinator_waiting.set()
                    return real_wait(*args, **kwargs)
                def execute(definition, *_):
                    if definition['task_id'] in roots:
                        if not release.wait(5): raise RuntimeError('Test gate timed out')
                    return dict(definition, status='SUCCESS', elapsed=.01)
                with patch.object(self.engine, 'load_schedule', return_value=definitions), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary', side_effect=lambda _, rows: summary.extend(rows)), patch.object(executor, 'submit', submit), patch.object(self.engine.concurrent.futures, 'wait', wait), contextlib.redirect_stdout(io.StringIO()):
                    runner = threading.Thread(target=lambda: results.append(self.engine.schedule_run(self.args)))
                    runner.start()
                    try:
                        self.assertTrue(coordinator_waiting.wait(3))
                        self.assertEqual(set(scheduled), roots, 'A skipped task let a descendant start early')
                    finally:
                        release.set(); runner.join(8)
                self.assertFalse(runner.is_alive())
                self.assertEqual(results, [0])
                self.assertEqual(set(scheduled), expected)
                for row in summary:
                    self.assertEqual(row['status'], 'SKIPPED_SUCCESS' if row['skip'] else 'SUCCESS')

    def test_failure_or_file_cancellation_propagates_through_skipped_rows(self):
        definitions = [task('A'), task('S1', ['A'], True), task('S2', ['S1'], True), task('C', ['S2'])]
        for failure in ('FAILED', 'CANCELLED'):
            with self.subTest(failure=failure):
                summary, called = [], []
                def execute(definition, *_):
                    called.append(definition['task_id'])
                    return dict(definition, status=failure, elapsed=.01)
                with patch.object(self.engine, 'load_schedule', return_value=definitions), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary', side_effect=lambda _, rows: summary.extend(rows)), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.engine.schedule_run(self.args), 1)
                self.assertEqual(called, ['A'])
                self.assertEqual([r['status'] for r in summary], [failure]+['BLOCKED_DEPENDENCY']*3)

    def test_schedule_cancel_stops_queue_and_reaches_all_active_tasks(self):
        self.args.workers = 2
        definitions = [task(str(i)) for i in range(12)]
        both_started = threading.Event(); summary, called, result = [], [], []
        guard = threading.Lock()
        def execute(definition, *_):
            with guard:
                called.append(definition['task_id'])
                if len(called) == 2: both_started.set()
            control = Path(definition['_cancel_file'])
            deadline = time.monotonic()+5
            while not control.exists() and time.monotonic()<deadline:
                threading.Event().wait(.01)
            if not control.exists(): raise RuntimeError('Schedule cancellation never reached task')
            return dict(definition, status='CANCELLED', elapsed=.01)
        with patch.object(self.engine, 'load_schedule', return_value=definitions), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary', side_effect=lambda _, rows: summary.extend(rows)), contextlib.redirect_stdout(io.StringIO()):
            runner = threading.Thread(target=lambda: result.append(self.engine.schedule_run(self.args))); runner.start()
            try:
                self.assertTrue(both_started.wait(3))
            finally:
                Path(self.args.cancel_file).touch(); runner.join(8)
        self.assertEqual(result, [130])
        self.assertEqual(called, ['0', '1'])
        self.assertEqual([r['status'] for r in summary], ['CANCELLED']*12)
        self.assertEqual(self.app.history()[0]['status'], 'STOPPED')

    def test_cancel_of_last_active_task_reports_stopped_not_failed(self):
        def execute(definition, *_):
            Path(definition['_cancel_file']).touch()
            return dict(definition, status='CANCELLED', elapsed=.01)
        with patch.object(self.engine, 'load_schedule', return_value=[task('A')]), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.schedule_run(self.args), 130)

    def test_cancel_before_start_prevents_any_eg_launch(self):
        Path(self.args.cancel_file).touch()
        with patch.object(self.engine.subprocess, 'Popen') as launch:
            rc, text = self.engine.execute_eg('RUNPROJECT', self.root/'project.egp', self.root/'setup.xml', 'A', 0, 0, self.root/'tasks/A', False, cancel_file=self.args.cancel_file)
        self.assertEqual(rc, 130)
        self.assertIn('before Enterprise Guide', text)
        launch.assert_not_called()

    def test_ui_stop_is_scoped_and_handles_task_starting_after_request(self):
        for identifier, action in [('one', 'schedule'), ('two', 'continue'), ('watcher', 'watch')]:
            self.app.commands[identifier] = dict(id=identifier, action=action, status='RUNNING',
                control_file=str(self.root/(identifier+'.stop')), tasks={'A':dict(status='RUNNING')})
            self.app.processes[identifier] = object()
        self.app.stop('one'); self.app.stop('one')
        self.assertTrue((self.root/'one.stop').exists())
        self.assertFalse((self.root/'two.stop').exists()); self.assertFalse((self.root/'watcher.stop').exists())
        self.assertEqual(self.app.commands['one']['tasks']['A']['status'], 'CANCELLING')
        self.app.event(self.app.commands['one'], dict(event='start', key='late', name='late', time=10))
        self.assertEqual(self.app.commands['one']['tasks']['late']['status'], 'CANCELLING')
        self.assertEqual(self.app.commands['two']['status'], 'RUNNING')
        self.app.stop('two')
        self.assertTrue((self.root/'two.stop').exists())

    def test_skip_waiting_and_resolving_are_visible_without_waiting_for_summary(self):
        item = dict(id='skip', action='schedule', status='RUNNING', tasks={})
        self.app.event(item, dict(event='plan', tasks=[task('B', ['A'], True)]))
        self.assertEqual(item['tasks']['B']['status'], 'PENDING')
        with patch('ui_worker.emit', side_effect=lambda event_type, **values: self.app.event(item, dict(event=event_type, time=10, **values))), contextlib.redirect_stdout(io.StringIO()):
            observe(self.engine)
            self.engine.report_task_result(dict(task('B', ['A'], True), status='SKIPPED_SUCCESS', elapsed=0, message='Dependencies complete'))
        self.assertEqual(item['tasks']['B']['status'], 'SKIPPED_SUCCESS')
        self.assertIsNone(item['tasks']['B']['started'])


if __name__ == '__main__': unittest.main()

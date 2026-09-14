from __future__ import annotations
import argparse
import contextlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_worker import load_engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = load_engine(ROOT / 'pysas.py')
        self.engine.ROOT_DIR = self.root

    def tearDown(self):
        self.temp.cleanup()

    def test_initialization_is_prepended_in_order_and_override_is_preserved(self):
        init = self.root / 'shared'; init.mkdir()
        inbox = self.root / 'queue'; inbox.mkdir()
        (init / '_20_macros.sas').write_text('macro_code;')
        (init / '_10_libraries.sas').write_text('library_code;')
        (inbox / '_30_extra.sas').write_text('inbox_code;')
        job = inbox / 'job.sas'; job.write_text('job_code;')
        text = self.engine.compose_sas(job, self.root / 'results', init_dir=init, extra_init_dir=inbox)
        self.assertLess(text.index('library_code;'), text.index('macro_code;'))
        self.assertLess(text.index('macro_code;'), text.index('inbox_code;'))
        self.assertLess(text.index('inbox_code;'), text.index('job_code;'))
        override = self.root / 'override.sas'; override.write_text('override_code;')
        text = self.engine.compose_sas(job, self.root / 'results', override, init, inbox)
        self.assertIn('override_code;', text)
        self.assertNotIn('library_code;', text)
        self.assertEqual(len(self.engine.init_files(folder=init, extra_folder=init)), 2)

    def test_watcher_does_not_claim_underscore_files(self):
        inbox = self.root / 'queue'; inbox.mkdir()
        init = self.root / 'shared'; init.mkdir()
        (init / '_00_base.sas').write_text('base_code;')
        shared = inbox / '_10_shared.sas'; shared.write_text('shared_code;')
        (inbox / 'job.sas').write_text('job_code;')
        project = self.root / 'project.egp'; project.write_text('fake')
        seen = []
        finished = threading.Event()
        def fake_job(source, project, tables, lib, notify, runs, name, init_dir, extra_init_dir):
            self.assertEqual(source.parent.parent, inbox.resolve() / '.pysas-claimed')
            seen.append((name, self.engine.compose_sas(source, runs, lib, init_dir, extra_init_dir)))
            finished.set()
            return {'status': 'SUCCESS', 'run_dir': runs / 'job'}
        cycles = 0
        def tick(_):
            nonlocal cycles
            cycles += 1
            if cycles >= 2:
                self.assertTrue(finished.wait(2))
                raise KeyboardInterrupt()
        args = argparse.Namespace(template=str(project), lib=None, workers=1, poll=.5,
                                  no_notify=True, tables=False, inbox=str(inbox), init_dir=str(init))
        with patch.object(self.engine, 'run_job', fake_job), patch.object(self.engine.time, 'sleep', tick), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.runner_watch(args), 130)
        self.assertEqual([x[0] for x in seen], ['job.sas'])
        self.assertIn('base_code;', seen[0][1]); self.assertIn('shared_code;', seen[0][1])
        self.assertTrue(shared.exists())

    def run_schedule(self, tasks, failure, raises=False):
        book = self.root / 'Schedule.xlsx'; book.write_text('fake')
        project = self.root / 'project.egp'; project.write_text('fake')
        observed, summary = [], []
        def execute(task, *_):
            observed.append(task['task_id'])
            if task['task_id'] == failure and raises:
                raise OSError('COM startup failed')
            return {**task, 'status': 'FAILED' if task['task_id'] == failure else 'SUCCESS', 'elapsed': .01}
        args = argparse.Namespace(workbook=str(book), project=str(project), workers=1, no_notify=True)
        with patch.object(self.engine, 'load_schedule', return_value=tasks), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary', side_effect=lambda path, results: summary.extend(results)), contextlib.redirect_stdout(io.StringIO()):
            rc = self.engine.schedule_run(args)
        return rc, observed, {r['task_id']: r['status'] for r in summary}

    @staticmethod
    def task(identifier, deps=(), always=False, stop=False, skip=False):
        return {'task_id': identifier, 'program': identifier, 'depends_on': list(deps),
                'always_run': always, 'stop_process_on_error': stop, 'skip': skip,
                'max_parallel': 1, 'row_start': None, 'row_end': None}

    def test_cleanup_runs_after_stop_on_error_and_stopped_dependency(self):
        tasks = [self.task('cleanup', ['B'], always=True), self.task('B', ['A']), self.task('A', stop=True)]
        rc, observed, statuses = self.run_schedule(tasks, 'A')
        self.assertEqual(rc, 1)
        self.assertEqual(observed, ['A', 'cleanup'])
        self.assertEqual(statuses['B'], 'STOPPED_ON_ERROR')
        self.assertEqual(statuses['cleanup'], 'SUCCESS')

    def test_cleanup_runs_after_failed_transitive_dependency_in_reverse_order(self):
        tasks = [self.task('cleanup', ['B'], always=True), self.task('B', ['A']), self.task('A')]
        _, observed, statuses = self.run_schedule(tasks, 'A')
        self.assertEqual(observed, ['A', 'cleanup'])
        self.assertEqual(statuses['B'], 'BLOCKED_DEPENDENCY')

    def test_cleanup_runs_after_worker_exception(self):
        tasks = [self.task('A', stop=True), self.task('cleanup', ['A'], always=True)]
        _, observed, statuses = self.run_schedule(tasks, 'A', raises=True)
        self.assertEqual(observed, ['A', 'cleanup'])
        self.assertEqual(statuses['A'], 'FAILED')
        self.assertEqual(statuses['cleanup'], 'SUCCESS')

    def test_explicit_skip_is_still_respected(self):
        tasks = [self.task('A'), self.task('cleanup', ['A'], always=True, skip=True)]
        _, observed, statuses = self.run_schedule(tasks, 'A')
        self.assertEqual(observed, ['A'])
        self.assertEqual(statuses['cleanup'], 'SKIPPED_SUCCESS')

    def test_continuation_reruns_always_run_tasks(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest('openpyxl optional locally')
        previous = self.root / 'previous'; previous.mkdir()
        (previous / 'project.egp').write_text('fake')
        (previous / 'run_summary.csv').write_text('task_id,status\nA,SUCCESS\ncleanup,SUCCESS\n')
        book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'Schedule'
        headers = sorted(self.engine.REQUIRED_COLUMNS); sheet.append(headers)
        tasks = [self.task('A'), self.task('cleanup', ['A'], always=True)]
        for task in tasks:
            sheet.append([','.join(task.get(h, [])) if h == 'depends_on' else task.get(h) for h in headers])
        book.save(previous / 'Schedule.xlsx')
        captured = []
        def resume(args):
            captured.extend(self.engine.load_schedule(Path(args.workbook)))
            return 0
        with patch.object(self.engine, 'schedule_run', resume):
            self.engine.schedule_continue(argparse.Namespace(run_dir=str(previous), workers=1, no_notify=True))
        self.assertTrue(captured[0]['skip'])
        self.assertFalse(captured[1]['skip'])


if __name__ == '__main__': unittest.main()

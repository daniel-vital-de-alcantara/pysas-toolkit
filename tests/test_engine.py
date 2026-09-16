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

    def test_excel_boolean_flags_accept_numeric_one(self):
        for value in (True, 1, 1.0, '1', '1.0', 'TRUE', 'yes', 'x'):
            self.assertTrue(self.engine.truthy(value), repr(value))
        for value in (False, 0, 0.0, '0', '0.0', '', None, 'FALSE', 2):
            self.assertFalse(self.engine.truthy(value), repr(value))

    def test_initialization_is_prepended_in_order_and_override_is_preserved(self):
        init = self.root / 'shared'; init.mkdir()
        inbox = self.root / 'queue'; inbox.mkdir()
        (init / '_20_macros.SAS').write_text('macro_code;')
        (init / '_10_libraries.sas').write_text('library_code;')
        (inbox / '_30_extra.sas').write_text('inbox_code;')
        job = inbox / 'job.SAS'; job.write_text('job_code;')
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
        shared = inbox / '_10_shared.SAS'; shared.write_text('shared_code;')
        (inbox / 'job.SAS').write_text('job_code;')
        (inbox / 'second.sAs').write_text('second_code;')
        (inbox / '_20_options.sAs').write_text('options_code;')
        project = self.root / 'project.egp'; project.write_text('fake')
        seen = []
        finished = threading.Event()
        def fake_execute(mode, project, source, name, first, last, run_dir, tables):
            self.assertEqual(mode, 'RUNFILE')
            seen.append((name, source.read_text(encoding='utf-8')))
            if len(seen) == 2:
                finished.set()
            return 0, ''
        cycles = 0
        def tick(_):
            nonlocal cycles
            cycles += 1
            if finished.wait(.02):
                raise KeyboardInterrupt()
            if cycles > 200:
                self.fail('Watcher did not submit both jobs')
        args = argparse.Namespace(template=str(project), lib=None, workers=1, poll=.5,
                                  no_notify=True, tables=False, inbox=str(inbox), init_dir=str(init))
        with patch.object(self.engine, 'execute_eg', fake_execute), patch.object(self.engine.time, 'sleep', tick), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.runner_watch(args), 130)
        self.assertEqual([x[0] for x in seen], ['job.SAS', 'second.sAs'])
        for _, text in seen:
            self.assertIn('base_code;', text)
            self.assertIn('shared_code;', text)
            self.assertIn('options_code;', text)
        self.assertTrue(shared.exists())

    def run_schedule(self, tasks, failure, raises=False):
        book = self.root / 'Schedule.xlsx'; book.write_text('fake')
        project = self.root / 'project.egp'; project.write_text('fake')
        observed, summary = [], []
        def execute(task, *_):
            observed.append(task['task_id'])
            self.assertEqual(task['_always_run'], [t for t in tasks if t['always_run'] and not t['skip']])
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
                'max_parallel': None, 'row_start': None, 'row_end': None}

    def test_ten_jobs_run_in_parallel_with_three_shared_definitions(self):
        book = self.root/'Schedule.xlsx'; book.touch()
        project = self.root/'project.egp'; project.touch()
        setups = [self.task(f'setup{i}', always=True) for i in range(3)]
        tasks = setups + [self.task(f'job{i}') for i in range(12)]
        guard = threading.Lock()
        ready = threading.Event()
        release = threading.Event()
        running = 0
        peak = 0
        submitted = []
        result = []
        def execute(task, *_):
            nonlocal running, peak
            with guard:
                submitted.append(task['task_id'])
                running += 1
                peak = max(peak, running)
                if running == 10:
                    ready.set()
            self.assertEqual(task['_always_run'], setups)
            release.wait(5)
            with guard:
                running -= 1
            return dict(task, status='SUCCESS', elapsed=.01)
        args = argparse.Namespace(workbook=str(book), project=str(project), workers=None, no_notify=True)
        with patch.object(self.engine, 'load_schedule', return_value=tasks), patch.object(self.engine, 'scheduler_task', execute), patch.object(self.engine, 'write_summary'), contextlib.redirect_stdout(io.StringIO()):
            runner = threading.Thread(target=lambda: result.append(self.engine.schedule_run(args)))
            runner.start()
            try:
                self.assertTrue(ready.wait(3), 'Default did not allow ten simultaneous tasks')
            finally:
                release.set()
                runner.join(5)
        self.assertFalse(runner.is_alive())
        self.assertEqual(result, [0])
        self.assertEqual(peak, 10)
        self.assertEqual(set(submitted), {f'job{i}' for i in range(12)})

    def test_setup_is_applied_to_every_program_but_never_scheduled_alone(self):
        tasks = [self.task('lib', always=True), self.task('macros', always=True),
                 self.task('A', ['lib']), self.task('B', ['A'])]
        rc, observed, statuses = self.run_schedule(tasks, None)
        self.assertEqual(rc, 0)
        self.assertEqual(observed, ['A', 'B'])
        self.assertEqual(statuses['lib'], 'ALWAYS_RUN_DEFINITION')
        self.assertEqual(statuses['macros'], 'ALWAYS_RUN_DEFINITION')

    def test_setup_does_not_override_stop_or_failed_dependencies(self):
        for stop, expected in [(True, 'STOPPED_ON_ERROR'), (False, 'BLOCKED_DEPENDENCY')]:
            tasks = [self.task('lib', always=True), self.task('B', ['A']), self.task('A', stop=stop)]
            rc, observed, statuses = self.run_schedule(tasks, 'A', raises=True)
            self.assertEqual(rc, 1)
            self.assertEqual(observed, ['A'])
            self.assertEqual(statuses['B'], expected)
            self.assertEqual(statuses['lib'], 'ALWAYS_RUN_DEFINITION')

    def test_setup_stop_process_applies_to_target_failure(self):
        tasks = [self.task('lib', always=True, stop=True), self.task('A'), self.task('B')]
        rc, observed, statuses = self.run_schedule(tasks, 'A')
        self.assertEqual((rc, observed, statuses['B']), (1, ['A'], 'STOPPED_ON_ERROR'))

    def test_scheduler_passes_ordered_setup_and_line_ranges_to_bridge(self):
        project = self.root / 'project.egp'; project.write_text('fake')
        task = self.task('A')
        first = self.task('Libraries & macros', always=True)
        first.update(row_start=2, row_end=7)
        task['_always_run'] = [first, self.task('Options', always=True)]
        def execute(mode, project, setup_path, program, first, last, run_dir, tables, **kwargs):
            self.assertEqual(mode, 'RUNPROJECT')
            nodes = self.engine.ET.parse(setup_path).getroot().findall('program')
            self.assertEqual([dict(n.attrib) for n in nodes], [
                {'name': 'Libraries & macros', 'first': '2', 'last': '7', 'section': ''},
                {'name': 'Options', 'first': '0', 'last': '0', 'section': ''}])
            self.assertEqual(program, 'A')
            return 0, ''
        with patch.object(self.engine, 'execute_eg', execute):
            self.assertEqual(self.engine.scheduler_task(task, project, self.root / 'tasks')['status'], 'SUCCESS')

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

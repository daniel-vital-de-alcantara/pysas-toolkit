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
                'max_parallel': 1, 'row_start': None, 'row_end': None}

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

    def test_scheduler_passes_ordered_setup_and_line_ranges_to_bridge(self):
        project = self.root / 'project.egp'; project.write_text('fake')
        task = self.task('A')
        first = self.task('Libraries & macros', always=True)
        first.update(row_start=2, row_end=7)
        task['_always_run'] = [first, self.task('Options', always=True)]
        def execute(mode, project, setup_path, program, first, last, run_dir, tables):
            self.assertEqual(mode, 'RUNPROJECT')
            nodes = self.engine.ET.parse(setup_path).getroot().findall('program')
            self.assertEqual([dict(n.attrib) for n in nodes], [
                {'name': 'Libraries & macros', 'first': '2', 'last': '7'},
                {'name': 'Options', 'first': '0', 'last': '0'}])
            self.assertEqual(program, 'A')
            return 0, ''
        with patch.object(self.engine, 'execute_eg', execute):
            self.assertEqual(self.engine.scheduler_task(task, project, self.root / 'tasks')['status'], 'SUCCESS')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows VBScript bridge')
    def test_vbscript_reads_utf8_and_prepends_sliced_setup_in_same_submission(self):
        import subprocess
        source = self.root / 'source.sas'; source.write_text('libname café;\noptions mprint;\ndata result;', encoding='utf-8')
        helper = self.engine.VBS[self.engine.VBS.index('Function ReadAll'):self.engine.VBS.index('Function CleanName')]
        harness = r'''
Class CodeItem
  Public Name, Text
End Class
Class Collection
  Public Count, Entry
  Public Function Item(index)
    Set Item = Entry
  End Function
End Class
Class ProjectStub
  Public CodeCollection
End Class
Dim project, collection, entry, answer
Set project = New ProjectStub
Set collection = New Collection
Set entry = New CodeItem
entry.Name = "setup"
entry.Text = ReadAll(WScript.Arguments(0))
Set collection.Entry = entry
collection.Count = 1
Set project.CodeCollection = collection
answer = ProgramText(project, "SETUP.SAS", 1, 2) & ProgramText(project, "setup", 3, 3)
If InStr(answer, "caf" & ChrW(233)) = 0 Then WScript.Quit 30
If answer <> entry.Text & vbCrLf Then
  If Replace(answer, vbCrLf, vbLf) <> entry.Text & vbLf Then WScript.Quit 31
End If
WScript.Echo "PASS"
'''
        script = self.root / 'bridge.vbs'; script.write_text(helper + harness, encoding='utf-16')
        result = subprocess.run(['cscript.exe', '//nologo', str(script), str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)

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

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pysas
import pysas_ui


class ScheduleLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'pysas.py').touch()
        self.run = self.root/'runs'/'test__schedule'; self.run.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def task(self, key, text=None, encoding='utf-8', **values):
        folder = self.run/'tasks'/key
        (folder/'logs').mkdir(parents=True)
        if text is not None: (folder/'logs'/'same-program.log').write_bytes(text.encode(encoding))
        return dict(task_id=key, program='same-program.sas', status='SUCCESS', elapsed=2.5,
                    task_dir=folder, section='', depends_on=[], row_start=None, row_end=None, message='') | values

    def test_full_sas_logs_and_console_are_grouped_in_workbook_order(self):
        second = self.task('second', 'ERROR: second failed\n', status='SAS_ERROR', row_start=10, row_end=20)
        first = self.task('first', 'NOTE: first succeeded\n', section='Realised')
        (first['task_dir']/'console.txt').write_text('PYSAS_STAGE|executing|Running first\nPYSAS_STAGE|complete|Finished\n', encoding='utf-8')
        rows = [first, second]
        log = pysas.write_schedule_log(self.run, rows).read_text(encoding='utf-8')
        self.assertLess(log.index('TASK 1/2: first'), log.index('TASK 2/2: second'))
        self.assertIn('Selection: section Realised', log)
        self.assertIn('Selection: rows 10 to 20', log)
        self.assertIn('Elapsed: 2.5 seconds', log)
        self.assertEqual(log.count('NOTE: first succeeded'), 1)
        self.assertEqual(log.count('ERROR: second failed'), 1)
        self.assertIn('Automation console: console.txt', log)
        self.assertIn('Running first\nFinished\n', log)
        self.assertNotIn('PYSAS_STAGE|', log)
        self.assertEqual((first['task_dir']/'logs'/'same-program.log').read_text(), 'NOTE: first succeeded\n')

    def test_large_legacy_and_unicode_logs_are_not_truncated(self):
        long_text = 'NOTE: line\n'*60000 + 'x'*300000 + '\nInformação — preço €\nLAST LINE\n'
        rows = [self.task('legacy', long_text, encoding='cp1252'), self.task('unicode', 'NOTE: 中文 café\n', encoding='utf-16')]
        log = pysas.write_schedule_log(self.run, rows).read_text(encoding='utf-8')
        self.assertIn(long_text, log)
        self.assertIn('NOTE: 中文 café', log)
        self.assertNotIn('\ufffd', log)

    def test_stopped_skipped_and_setup_rows_explain_absent_logs(self):
        rows = [self.task('setup', status='ALWAYS_RUN_DEFINITION'), self.task('skip', status='SKIPPED_SUCCESS'),
                self.task('blocked', status='BLOCKED_DEPENDENCY'), self.task('cancel', status='CANCELLED')]
        (rows[-1]['task_dir']/'console.txt').write_text('Stopped by user.\n')
        log = pysas.write_schedule_log(self.run, rows).read_text(encoding='utf-8')
        for row in rows: self.assertIn('Status: '+row['status'], log)
        self.assertIn("Shared setup is included in each target's SAS log.", log)
        self.assertEqual(log.count('No SAS log was produced'), 3)
        self.assertIn('Stopped by user.', log)

    def test_unreadable_input_does_not_discard_other_logs(self):
        rows = [self.task('a', 'a'), self.task('b', 'b')]
        original = pysas.append_schedule_log_file
        def copy(output, path, **kwargs):
            if path.parent.parent.name == 'a': raise PermissionError('test lock')
            return original(output, path, **kwargs)
        with patch.object(pysas, 'append_schedule_log_file', copy):
            log = pysas.write_schedule_log(self.run, rows).read_text(encoding='utf-8')
        self.assertIn('Could not read same-program.log: test lock', log)
        self.assertIn('\nb\n', log)
        self.assertFalse(list(self.run.glob('.schedule-log-*.tmp')))

    def test_summary_exposes_download_and_inspector_file(self):
        app = pysas_ui.Workbench(self.root)
        try:
            row = self.task('a', 'NOTE: evidence\n')
            pysas.write_schedule_log(self.run, [row])
            item = dict(id='test', tasks={})
            app.event(item, dict(event='summary', path=str(self.run), tasks=[row]))
            self.assertEqual(item['schedule_log'], 'runs/test__schedule/schedule.log')
            detail = app.details('runs/test__schedule')
            self.assertIn('schedule.log', [file['name'] for file in detail['files']])
        finally:
            app.awake.close()


if __name__ == '__main__': unittest.main()

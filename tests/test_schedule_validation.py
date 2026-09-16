from pathlib import Path
import tempfile
import unittest
import sys
try:
    import openpyxl
except ImportError:
    openpyxl = None
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pysas


@unittest.skipIf(openpyxl is None, 'openpyxl not installed')
class ScheduleValidationTests(unittest.TestCase):
    def load(self, records, duplicate_header=False):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Schedule.xlsx'
            book = openpyxl.Workbook(); ws = book.active
            headers = sorted(pysas.REQUIRED_COLUMNS)
            if duplicate_header: headers.append('section')
            ws.append(headers)
            for record in records:
                task = dict(task_id='task', program='Realised', section='', row_start=None,
                            row_end=None, skip=0, always_run=0, max_parallel=None, depends_on='',
                            stop_program_on_error=0, stop_process_on_error=0) | record
                ws.append([task[h] for h in headers])
            book.save(path); book.close()
            return pysas.load_schedule(path)

    def test_named_selection_accepts_zero_bounds_like_terminal(self):
        tasks = self.load([dict(section='Realised', row_start=0, row_end=0)])
        self.assertEqual(tasks[0]['section'], 'Realised')
        self.assertIsNone(tasks[0]['row_start'])
        self.assertIsNone(tasks[0]['row_end'])

    def test_invalid_selection_or_graph_fails_before_any_submission(self):
        cases = [([dict(section='Realised', row_start=1)], 'section or row range'),
                 ([dict(row_start=-1)], 'row_start'),
                 ([dict(row_end=-2)], 'row_end'),
                 ([dict(row_start=5, row_end=2)], 'row_start'),
                 ([dict(program='')], 'program is required'),
                 ([dict(max_parallel=0)], 'max_parallel'),
                 ([dict(depends_on='missing')], 'unknown dependencies'),
                 ([dict(depends_on='task')], 'Circular dependency'),
                 ([dict(task_id='A', depends_on='B'), dict(task_id='B', depends_on='a')], 'Circular dependency'),
                 ([dict(task_id='A'), dict(task_id='B', depends_on='A,a')], 'duplicates')]
        for records, error in cases:
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, error):
                self.load(records)

    def test_duplicate_column_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, 'duplicate column'):
            self.load([{}], duplicate_header=True)

    def test_terminal_max_parallel_option_still_works(self):
        self.assertEqual(pysas.parser().parse_args(['schedule', '--max-parallel', '4']).workers, 4)


if __name__ == '__main__': unittest.main()

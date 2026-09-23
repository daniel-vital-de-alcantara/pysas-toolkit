from __future__ import annotations
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import pysas_ui as ui
from ui_data import archive_folder, duration_history, estimate_task, estimate_schedule, FORMAT


class SavedDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'pysas.py').write_text('# test')
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def backup(self):
        stream, _ = self.app.backup()
        with stream: return stream.read()

    def seed(self):
        folder = self.root / 'runs' / 'schedule'
        (folder / 'tasks/A/logs').mkdir(parents=True)
        (folder / 'tasks/A/logs/log.log').write_text('NOTE: café finished', encoding='utf-8')
        (folder / 'schedule.log').write_text('full log')
        item = dict(id='original', name='test', args=[], action='schedule', started=100, status='SUCCESS', path='runs/schedule', schedule_log='runs/schedule/schedule.log', tasks={'A': dict(name='A', status='SUCCESS', elapsed=15, path='runs/schedule/tasks/A')})
        self.app.commands[item['id']] = item
        self.app.save(item)
        (self.app.storage / 'original.txt').write_text('console')
        (self.app.storage / 'app-profile').mkdir()
        (self.app.storage / 'app-profile/cookie').write_text('not portable')
        ui.atomic_json(self.app.storage / 'folders.json', self.app.folders())
        ui.atomic_json(self.app.storage / 'bundle-paths.json', {'paths': [str(self.root)], 'last': str(self.root)})
        return item

    def test_round_trip_to_new_pc_preserves_logs_and_remaps_paths(self):
        self.seed()
        data = self.backup()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertNotIn('.pysas-ui/app-profile/cookie', z.namelist())
            self.assertNotIn('pysas.py', z.namelist())
        dest = self.root / 'new-version'; dest.mkdir()
        (dest / 'pysas.py').write_text('# new engine')
        target = ui.Workbench(dest)
        result = target.backup(io.BytesIO(data), len(data))
        self.assertEqual(result['runs'], 1)
        self.assertEqual((dest / 'runs/schedule/tasks/A/logs/log.log').read_text(encoding='utf-8'), 'NOTE: café finished')
        restored = ui.Workbench(dest)
        self.assertEqual(len(restored.commands), 1)
        item = next(iter(restored.commands.values()))
        self.assertNotEqual(item['id'], 'original')
        self.assertEqual(Path(item['schedule_log']), Path('runs/schedule/schedule.log'))
        self.assertEqual(restored.folders()['inputs'], str(dest))
        self.assertEqual(restored.bundle_settings()['last'], str(dest))
        self.assertEqual((dest / 'pysas.py').read_text(), '# new engine')

    def test_collision_preserves_original_and_remaps_imported_task_paths(self):
        original = self.seed()
        data = self.backup()
        self.app.backup(io.BytesIO(data), len(data))
        imported = next(c for c in self.app.commands.values() if c['id'] != original['id'])
        self.assertNotEqual(imported['path'], original['path'])
        self.assertTrue((self.root / imported['tasks']['A']['path'] / 'logs/log.log').is_file())
        self.assertTrue((self.root / original['path']).is_dir())
        self.assertEqual((self.app.storage / (imported['id'] + '.txt')).read_text(), 'console')

    def test_windows_manifest_and_unavailable_external_folders(self):
        self.seed()
        data = self.backup()
        def windows(m):
            m['workspace'] = r'C:\Old\PySAS'
            m['folders'] = {'inputs': r'C:\Old\PySAS', 'init': r'Z:\unavailable', 'inbox': r'C:\Old\PySAS\runner\inbox'}
            m['commands'][0]['tasks']['A']['path'] = r'runs\schedule\tasks\A'
            m['commands'][0]['status'] = 'RUNNING'
            return m
        data = self.rewrite(data, transform=windows)
        result = self.app.backup(io.BytesIO(data), len(data))
        self.assertIn('init', result['missing_folders'])
        imported = next(c for c in self.app.commands.values() if c['id'] != 'original')
        self.assertEqual(imported['status'], 'UNKNOWN')
        self.assertTrue((self.root / imported['tasks']['A']['path']).is_dir())
        self.assertEqual(self.app.folders()['inputs'], str(self.root))

    @staticmethod
    def rewrite(data, extra=None, transform=None):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, 'w') as target:
            for i in source.infolist():
                content = source.read(i)
                if i.filename == 'manifest.json' and transform:
                    content = json.dumps(transform(json.loads(content))).encode()
                target.writestr(i, content)
            if extra: target.writestr(extra, b'bad')
        return out.getvalue()

    def test_rejects_traversal_application_overwrite_and_symlink(self):
        self.seed(); data = self.backup()
        names = ['runs/../../pysas.py', 'pysas.py', 'runs/x/CON.txt', 'runs/x/foo:bar', 'runs/x/a\\b']
        link = zipfile.ZipInfo('runs/x/link'); link.create_system = 3; link.external_attr = 0o120777 << 16
        for name in [*names, link]:
            with self.subTest(name=name):
                bad = self.rewrite(data, extra=name)
                with self.assertRaises(ValueError): self.app.backup(io.BytesIO(bad), len(bad))
        self.assertEqual(len(self.app.commands), 1)

    def test_failed_restore_rolls_back_moved_runs_and_settings(self):
        self.seed(); data = self.backup()
        before = (self.app.storage / 'folders.json').read_bytes()
        with patch.object(self.app, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.app.backup(io.BytesIO(data), len(data))
        self.assertEqual(len(list((self.root / 'runs').iterdir())), 1)
        self.assertEqual((self.app.storage / 'folders.json').read_bytes(), before)
        self.assertEqual(len(self.app.commands), 1)

    def test_active_commands_block_export_and_import(self):
        self.seed(); data = self.backup()
        self.app.commands['original']['status'] = 'RUNNING'
        with self.assertRaisesRegex(ValueError, 'Finish active'): self.app.backup()
        with self.assertRaisesRegex(ValueError, 'Finish active'): self.app.backup(io.BytesIO(data), len(data))

    def test_folder_zip_contains_every_file_beyond_inspector_limit(self):
        self.seed()
        folder = self.root / 'runs/schedule'
        for i in range(1005): (folder / f'{i}.txt').write_text(str(i))
        stream, name = archive_folder(self.root, 'runs/schedule')
        with stream, zipfile.ZipFile(stream) as z:
            self.assertEqual(len(z.namelist()), 1007)
            self.assertEqual(z.read('schedule/1004.txt'), b'1004')
        self.assertEqual(name, 'schedule.zip')
        for path in ('', 'runs', '../', '.pysas-ui'):
            with self.assertRaises(ValueError): archive_folder(self.root, path)


class TimingTests(unittest.TestCase):
    @staticmethod
    def samples(*values):
        return [dict(key=(name, section, first, last), seconds=seconds, time=i) for i, (name, section, first, last, seconds) in enumerate(values)]

    def test_median_and_exact_selection_no_failed_or_skipped_samples(self):
        samples = self.samples(('a.sas', '', 1, 10, 10), ('a.sas', '', 1, 10, 20), ('a.sas', '', 1, 10, 900), ('a.sas', 'other', 0, 0, 100))
        result = estimate_task(dict(program='A.SAS', row_start=1, row_end=10), samples)
        self.assertEqual(result['seconds'], 20)
        self.assertEqual(result['samples'], 3)
        self.assertIsNone(estimate_task(dict(program='a.sas', row_start=2, row_end=10), samples)['seconds'])
        with tempfile.TemporaryDirectory() as folder:
            command = dict(started=10, tasks={status: dict(name='a.sas', status=status, elapsed=20, path=status) for status in ('SUCCESS', 'FAILED', 'CANCELLED', 'SKIPPED_SUCCESS')})
            self.assertEqual(len(duration_history(Path(folder), [command])), 1)

    def test_schedule_dependency_skip_barrier_parallelism_and_shared_setup(self):
        samples = self.samples(('a', '', 0, 0, 60), ('c', '', 0, 0, 120), ('d', '', 0, 0, 200))
        tasks = [dict(task_id='init', program='lib', always_run=True), dict(task_id='a', program='a', depends_on=['init']), dict(task_id='b', program='b', skip=True, depends_on=['a']), dict(task_id='c', program='c', depends_on=['b']), dict(task_id='d', program='d')]
        result = estimate_schedule(tasks, 10, samples)
        self.assertEqual(result['seconds'], 200)
        self.assertEqual(result['unknown'], 0)
        self.assertEqual(estimate_schedule(tasks, 1, samples)['seconds'], 380)
        self.assertEqual(len(result['tasks']), 4)

    def test_partial_estimate_is_lower_bound_and_no_history_is_unknown(self):
        samples = self.samples(('a', '', 0, 0, 18000))
        tasks = [dict(task_id='a', program='a'), dict(task_id='b', program='unknown', depends_on=['a'])]
        result = estimate_schedule(tasks, 10, samples)
        self.assertEqual(result['seconds'], 18000)
        self.assertEqual(result['unknown'], 1)
        self.assertIsNone(estimate_schedule(tasks, 10, [])['seconds'])

    def test_reads_old_cli_workbook_scope_and_watcher_status_without_duplicates(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); folder = root / 'runs/old'; folder.mkdir(parents=True)
            wb = openpyxl.Workbook(); ws = wb.active
            from pysas import REQUIRED_COLUMNS
            columns = sorted(REQUIRED_COLUMNS); ws.append(columns)
            values = dict(task_id='a', program='program', section='Realised')
            ws.append([values.get(c) for c in columns])
            wb.save(folder / 'schedule.xlsx'); wb.close()
            (folder / 'run_summary.csv').write_text('task_id,program,status,elapsed\na,program,SUCCESS,90\n')
            job = root / 'runner/runs/watcher'; job.mkdir(parents=True)
            (job / 'status.txt').write_text('source=job.sas\nstatus=SUCCESS\nelapsed_seconds=120\n')
            command = dict(started=10, tasks={'a': dict(name='program', section='Realised', status='SUCCESS', elapsed=90, path='runs/old/tasks/a')})
            samples = duration_history(root, [command])
            self.assertEqual(len(samples), 2)
            self.assertEqual(estimate_task(dict(program='program', section='Realised'), samples)['seconds'], 90)
            self.assertEqual(estimate_task(dict(name='job.sas'), samples)['seconds'], 120)
            disk_only = duration_history(root, [])
            self.assertEqual(estimate_task(dict(program='program', section='Realised'), disk_only)['seconds'], 90)

    def test_original_032_split_duration_columns_and_watcher_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            schedule = root / 'runs/terminal032'; schedule.mkdir(parents=True)
            (schedule / 'run_summary.csv').write_text('task_id,program,status,section,start,end,duration_hours,duration_minutes,duration_seconds\na,Realised,SUCCESS,,20,80,2,30,15\n')
            file = root / 'runner/runs/terminal032'; file.mkdir(parents=True)
            (file / 'status.txt').write_text('source=job.sas\nstatus=SUCCESS\nstarted=2026-09-01T09:00:00\nfinished=2026-09-01T10:15:30\n')
            samples = duration_history(root, [])
            self.assertEqual(estimate_task(dict(program='Realised', row_start=20, row_end=80), samples)['seconds'], 9015)
            self.assertEqual(estimate_task(dict(name='job.sas'), samples)['seconds'], 4530)


if __name__ == '__main__': unittest.main()

"""Execute both bridges on Windows using the user's real Rich-terminal reference.

Only EG COM is substituted. VBScript parsing, XML/ANSI/UTF-8 IO, code selection,
server binding, cscript process completion and (in the UI case) worker events are real.
"""
from pathlib import Path
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pysas as engine
import pysas_ui as ui


def substitute_com(bridge, reference=False):
    stub = (ROOT/'tests/fixtures/scheduler_com_stub.vbs').read_text()
    bridge = bridge.replace('Option Explicit', 'Option Explicit\n' + stub, 1)
    for version in ('8.1', '7.1'):
        bridge = bridge.replace(f'CreateObject("SASEGObjectModel.Application.{version}")', 'New ApplicationStub')
    # VBScript classes cannot implement IEnumVARIANT; expose the same items
    # through a Variant array. Both bridges' matching/selection is unchanged.
    bridge = bridge.replace("In project.CodeCollection\n", "In project.CodeCollection.AllItems\n")
    return bridge


def definition(name='Realised.sas', **values):
    return dict(task_id=values.pop('task_id', name), program=name, depends_on=[],
                always_run=False, skip=False, row_start=None, row_end=None, section='',
                stop_program_on_error=False, stop_process_on_error=False, max_parallel=None) | values


def marked(section, contents):
    return f'NOT_SELECTED_TOP;\n* (please do not delete) section_start: {section};\n{contents}\n* (please do not delete) section_end: {section};\nNOT_SELECTED_BOTTOM;'


@unittest.skipUnless(sys.platform == 'win32', 'Real Windows cscript comparison against supplied 0.3.2')
class SchedulerParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = substitute_com((ROOT/'tests/fixtures/reference_032_scheduler.vbs').read_text(), True)
        self.current = substitute_com(engine.VBS)
        self.programs = [('Libraries', marked('Setup', 'libname café;'), 'SETUP_SERVER'),
                         ('Macros', 'ignore;\n%macro shared; %mend;\nignore;', 'MACRO_SERVER'),
                         ('Options', 'options mprint;', 'OPTIONS_SERVER'),
                         ('Realised.sas', marked('Realised', 'data realised;\n set table;\nrun;'), 'TARGET_SERVER')]
        self.setups = [definition('Libraries', section='Setup', always_run=True),
                       definition('Macros', row_start=2, row_end=2, always_run=True),
                       definition('Options', always_run=True)]

    def tearDown(self):
        self.temp.cleanup()

    def project(self, **attrs):
        root = ET.Element('project', **(dict(expected_server='TARGET_SERVER', log='NOTE: completed') | attrs))
        for name, text, server in self.programs:
            ET.SubElement(root, 'program', name=name, server=server).text = text
        path = self.root/'project.egp'
        ET.ElementTree(root).write(path, encoding='utf-8')
        return path

    def compare(self, task, setups=None, attrs=None):
        setups = self.setups if setups is None else setups
        project = self.project(**(attrs or {}))
        original = self.root/'original'; original.mkdir()
        shutil.copy2(project, original/project.name)
        script = self.root/'reference.vbs'; script.write_text(self.reference, encoding='utf-16')
        def selection(t):
            first, last = t['row_start'], t['row_end']
            return '' if not first and not last else f'{first or ""}:{last or ""}'
        (original/'always_run.tsv').write_text('\n'.join('\t'.join([t['program'], selection(t), t['section']]) for t in setups), encoding='cp1252')
        stop = task['stop_program_on_error'] or any(t['stop_program_on_error'] for t in setups)
        result = subprocess.run([str(engine.cscript_path()), '//nologo', str(script), project.name,
                                 task['program'], selection(task), str(int(stop)), 'target', task['section'], 'always_run.tsv'],
                                cwd=original, capture_output=True, timeout=20)
        with patch.object(engine, 'VBS', self.current), contextlib.redirect_stdout(io.StringIO()) as output:
            current = engine.scheduler_task(dict(task, task_id='target', _always_run=setups), project, self.root/'current')
        task_dir = self.root/'current/target'
        status = {0:'SUCCESS', 22:'SAS_ERROR'}.get(result.returncode, 'FAILED')
        self.assertEqual(current['status'], status, result.stdout.decode(errors='replace') + '\n' + engine.read_text(task_dir/'console.txt'))
        reference_code = list((original/'code').glob('*.sas'))
        current_code = list((task_dir/'code').glob('*.sas'))
        self.assertEqual(len(current_code), len(reference_code))
        if reference_code:
            # Byte encoding differs deliberately: UI saves UTF-8 instead of ANSI.
            reference_text = engine.read_text(reference_code[0])
            self.assertEqual(engine.read_text(current_code[0]), reference_text)
        else:
            reference_text = ''
        for run in (original, task_dir):
            self.assertEqual((run/'executed.txt').exists(), bool(reference_code))
            if (run/'executed.txt').exists():
                self.assertEqual((run/'executed.txt').read_text(), 'TARGET_SERVER')
        return current, reference_text, output.getvalue(), result.returncode

    def test_three_shared_definitions_and_target_section_match_actual_032(self):
        result, code, progress, _ = self.compare(definition(section='rEaLiSeD'))
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertNotIn('NOT_SELECTED', code)
        self.assertIn('libname café;', code)
        self.assertEqual(code.count('/* ALWAYS_RUN_ITEM:'), 3)
        self.assertEqual(progress.count('Appending shared setup:'), 3)
        self.assertIn('Running: Realised.sas (section rEaLiSeD)', progress)
        self.assertTrue(code.endswith('/* SCHEDULED_TARGET_END */'))

    def test_inclusive_rows_and_target_stop_flag(self):
        result, code, progress, _ = self.compare(definition(row_start=3, row_end=5, stop_program_on_error=True))
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertNotIn('NOT_SELECTED', code)
        self.assertTrue(code.startswith('options iomlogautoflush errorabend errorcheck=strict;'))
        self.assertIn('rows 3 to 5', progress)

    def test_setup_stop_flag_applies_to_whole_submission(self):
        self.setups[1]['stop_program_on_error'] = True
        _, code, _, _ = self.compare(definition(section='Realised'))
        self.assertTrue(code.startswith('options iomlogautoflush errorabend errorcheck=strict;'))

    def test_full_program_without_setup(self):
        result, code, _, _ = self.compare(definition(), [])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertIn('NOT_SELECTED', code)
        self.assertNotIn('ALWAYS_RUN_INITIALIZATION_START', code)

    def test_open_ended_range(self):
        _, code, _, _ = self.compare(definition(row_start=3), [])
        self.assertTrue(code.startswith('options iomlogautoflush;'))
        self.assertNotIn('NOT_SELECTED_TOP', code)
        self.assertIn('NOT_SELECTED_BOTTOM', code)

    def test_missing_section_fails_before_run(self):
        result, code, _, rc = self.compare(definition(section='missing'))
        self.assertEqual((result['status'], code, rc), ('FAILED', '', 24))

    def test_duplicate_section_fails_before_run(self):
        name, text, server = self.programs[-1]
        self.programs[-1] = name, text+'\n* (please do not delete) section_start: Realised;', server
        _, code, _, rc = self.compare(definition(section='Realised'))
        self.assertEqual((code, rc), ('', 24))

    def test_range_beyond_program_fails_before_run(self):
        _, code, _, rc = self.compare(definition(row_start=3, row_end=999))
        self.assertEqual((code, rc), ('', 18))

    def test_section_and_range_conflict_fails_before_run(self):
        _, code, _, rc = self.compare(definition(section='Realised', row_start=3))
        self.assertEqual((code, rc), ('', 23))

    def test_duplicate_program_fails_before_run(self):
        self.programs.append(self.programs[-1])
        _, code, _, rc = self.compare(definition())
        self.assertEqual((code, rc), ('', 29))

    def test_run_error_still_saves_log_and_finishes(self):
        result, _, _, rc = self.compare(definition(section='Realised'), attrs={'run_error':'1'})
        self.assertEqual((result['status'], rc), ('FAILED', 20))
        self.assertTrue((self.root/'current/target/logs/Realised.log').is_file())

    def test_log_save_failure_cannot_report_success(self):
        result, _, _, rc = self.compare(definition(section='Realised'), attrs={'log_error':'1'})
        self.assertEqual((result['status'], rc), ('FAILED', 21))

    def test_sas_errors_are_reported_even_after_com_execution_error(self):
        result, _, _, rc = self.compare(definition(section='Realised'), attrs={'run_error':'1', 'log':'ERROR: simulated SAS failure'})
        self.assertEqual((result['status'], rc), ('SAS_ERROR', 22))

    def test_watcher_inherits_template_server(self):
        self.programs = [('Seed', 'seed;', 'TARGET_SERVER')]
        source = self.root/'file.sas'; source.write_text('data x;run;')
        with patch.object(engine, 'VBS', self.current), contextlib.redirect_stdout(io.StringIO()):
            rc, console = engine.execute_eg('RUNFILE', self.project(), source, 'file.sas', 0, 0, self.root, False)
        self.assertEqual(rc, 0, console)
        self.assertEqual((self.root/'executed.txt').read_text(), 'TARGET_SERVER')

    def test_ui_file_parameters_execute_after_init_and_survive_success(self):
        (self.root/'pysas.py').write_text((ROOT/'pysas.py').read_text(encoding='utf-8') + '\nVBS = ' + repr(self.current), encoding='utf-8')
        self.programs = [('Seed', 'seed;', 'TARGET_SERVER')]
        project = self.project()
        (self.root/'_libs.sas').write_text('library_token;', encoding='utf-8')
        source = self.root/'extract.sas'; source.write_text('job_token;', encoding='utf-8')
        app = ui.Workbench(self.root)
        try:
            identifier = app.launch(dict(action='run', program=str(source), template=str(project), use_parameters=True, parameters_name='_cases.sas', parameters_text='%let city=café;'))['id']
            exit_code = app.processes[identifier].wait(timeout=30)
            deadline = time.monotonic()+10
            while identifier in app.processes and time.monotonic()<deadline: time.sleep(.05)
            item = app.commands[identifier]
            console = (app.storage/(identifier+'.txt')).read_text(encoding='utf-8')
            self.assertEqual(exit_code, 0, console)
            self.assertEqual(item['status'], 'SUCCESS', console)
            task = next(iter(item['tasks'].values()))
            folder = self.root/task['path']
            code = engine.read_text(next((folder/'code').glob('*.sas')))
            self.assertLess(code.index('library_token;'), code.index('%let city=café;'))
            self.assertLess(code.index('%let city=café;'), code.index('job_token;'))
            self.assertEqual((folder/'parameters/_cases.sas').read_text(encoding='utf-8'), '%let city=café;')
        finally:
            for process in list(app.processes.values()):
                if process.poll() is None: process.kill(); process.wait()
            app.awake.close()

    def test_ui_schedule_completes_with_real_bridge_and_three_setup_sections(self):
        import openpyxl
        # The real UI worker imports this single engine; only EG COM is replaced.
        (self.root/'pysas.py').write_text((ROOT/'pysas.py').read_text(encoding='utf-8') + '\nVBS = ' + repr(self.current), encoding='utf-8')
        project = self.project()
        book = openpyxl.Workbook(); ws = book.active; ws.title = 'Schedule'
        headers = sorted(engine.REQUIRED_COLUMNS); ws.append(headers)
        for task in self.setups + [definition(section='Realised', task_id='target')]:
            ws.append([','.join(task[h]) if h=='depends_on' else task[h] for h in headers])
        workbook = self.root/'Schedule.xlsx'; book.save(workbook); book.close()
        app = ui.Workbench(self.root)
        try:
            identifier = app.launch(dict(action='schedule', workbook=str(workbook), project=str(project)))['id']
            process = app.processes[identifier]
            self.assertEqual(process.wait(timeout=30), 0)
            deadline = time.monotonic()+10
            while identifier in app.processes and time.monotonic()<deadline: time.sleep(.05)
            item = app.commands[identifier]
            self.assertEqual(item['status'], 'SUCCESS', (self.root/".pysas-ui"/(identifier+".txt")).read_text(encoding="utf-8"))
            self.assertEqual(item['tasks']['target']['status'], 'SUCCESS')
            self.assertEqual(Path(item['schedule_log']), Path(item['path'])/'schedule.log')
            self.assertIn('NOTE: completed', (self.root/item['schedule_log']).read_text(encoding='utf-8'))
            self.assertEqual(item['tasks']['target']['section'], 'Realised')
            self.assertEqual(len(item['tasks']['target']['setup']), 3)
            for task in self.setups:
                self.assertEqual(item['tasks'][task['task_id']]['status'], 'ALWAYS_RUN_DEFINITION')
            self.assertIn('Running: Realised.sas (section Realised)', (self.root/".pysas-ui"/(identifier+".txt")).read_text(encoding="utf-8"))
        finally:
            for process in list(app.processes.values()):
                if process.poll() is None: process.kill(); process.wait()
            app.awake.close()

    def test_ui_stops_whole_schedule_and_preserves_other_schedule(self):
        import openpyxl
        (self.root/'pysas.py').write_text((ROOT/'pysas.py').read_text(encoding='utf-8') + '\nVBS = ' + repr(self.current), encoding='utf-8')
        project = self.project(delay='30000')
        def workbook(name, identifiers):
            book = openpyxl.Workbook(); ws = book.active; ws.title = 'Schedule'
            headers = sorted(engine.REQUIRED_COLUMNS); ws.append(headers)
            for identifier in identifiers:
                row = definition(task_id=identifier, section='Realised')
                ws.append([','.join(row[h]) if h=='depends_on' else row[h] for h in headers])
            path = self.root/name; book.save(path); book.close()
            return path
        main_book = workbook('Schedule.xlsx', ['A', 'B', 'C', 'D'])
        other_book = workbook('Other.xlsx', ['Other'])
        other_project = self.root/'other.egp'
        document = ET.parse(project); document.getroot().set('delay', '1500'); document.write(other_project, encoding='utf-8')
        app = ui.Workbench(self.root)
        def await_started(identifier, keys):
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                tasks = app.commands[identifier]['tasks']
                if all(key in tasks and tasks[key].get('path') and (self.root/tasks[key]['path']/'executed.txt').exists() for key in keys): return
                time.sleep(.05)
            self.fail('Automation did not reach Run: ' + (self.root/'.pysas-ui'/(identifier+'.txt')).read_text(encoding='utf-8'))
        try:
            chosen = app.launch(dict(action='schedule', workbook=str(main_book), project=str(project), workers=2))['id']
            chosen_process = app.processes[chosen]
            await_started(chosen, ['A', 'B'])
            other = app.launch(dict(action='schedule', workbook=str(other_book), project=str(other_project)))['id']
            other_process = app.processes[other]
            await_started(other, ['Other'])
            app.stop(chosen)
            self.assertEqual(app.commands[chosen]['status'], 'STOPPING')
            self.assertFalse(Path(app.commands[other]['control_file']).exists())
            self.assertEqual(chosen_process.wait(timeout=20), 130)
            self.assertEqual(other_process.wait(timeout=15), 0)
            deadline = time.monotonic()+10
            while app.processes and time.monotonic()<deadline: time.sleep(.05)
            item = app.commands[chosen]
            self.assertEqual(item['status'], 'STOPPED')
            self.assertIn('Status: CANCELLED', (self.root/item['schedule_log']).read_text(encoding='utf-8'))
            self.assertEqual({t['status'] for t in item['tasks'].values()}, {'CANCELLED'})
            self.assertFalse(any((self.root/item['path']/'tasks'/key/'executed.txt').exists() for key in ['C', 'D']))
            self.assertEqual(app.commands[other]['status'], 'SUCCESS')
            self.assertEqual(app.commands[other]['tasks']['Other']['status'], 'SUCCESS')
            self.assertEqual(next(row for row in app.history() if row['path']==item['path'])['status'], 'STOPPED')
        finally:
            for identifier in list(app.processes):
                try: app.stop(identifier)
                except ValueError: pass
            for process in list(app.processes.values()):
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            app.awake.close()


if __name__ == '__main__': unittest.main()

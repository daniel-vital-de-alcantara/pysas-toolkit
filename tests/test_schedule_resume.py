import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import openpyxl
from ui_worker import load_engine
import pysas_ui as ui

ROOT=Path(__file__).resolve().parents[1]

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.engine=load_engine(ROOT/'pysas.py');self.engine.ROOT_DIR=self.root
        (self.root/'pysas.py').write_text('# fixture')
        (self.root/'project.egp').write_text('fixture')
        book=openpyxl.Workbook();sheet=book.active
        headers=sorted(self.engine.REQUIRED_COLUMNS);sheet.append(headers)
        for key,deps,always in [('setup','',1),('A','',0),('B','A',0),('C','B',0)]:
            row=dict(task_id=key,program=key,depends_on=deps,always_run=always,stop_process_on_error=0,skip=0)
            sheet.append([row.get(h) for h in headers])
        book.save(self.root/'Schedule.xlsx');book.close()
        self.args=argparse.Namespace(workbook=str(self.root/'Schedule.xlsx'),project=str(self.root/'project.egp'),workers=1,no_notify=True)
        self.now=1800000000.;self.fail='B';self.called=[]

    def tearDown(self):self.temp.cleanup()

    def execute(self,task,project,task_root):
        self.called.append(task['task_id'])
        self.assertEqual([t['task_id'] for t in task['_always_run']],['setup'])
        folder=task_root/self.engine.safe_name(task['task_id']);(folder/'logs').mkdir(parents=True)
        failed=task['task_id']==self.fail
        (folder/'logs/task.log').write_text(('ERROR: old failure ' if failed else 'NOTE: success ')+task['task_id'])
        self.now+=10
        return dict(task,status='SAS_ERROR' if failed else 'SUCCESS',elapsed=10,task_dir=folder,message='')

    def test_two_resumes_keep_one_folder_each_task_once_and_exclude_pause(self):
        with patch.object(self.engine,'scheduler_task',self.execute),patch.object(self.engine.time,'time',lambda:self.now),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.engine.schedule_run(self.args),1)
            run=next(p for p in (self.root/'runs').iterdir() if not p.name.startswith('.'))
            self.now+=50000;self.fail='C';self.called=[]
            args=argparse.Namespace(run_dir=str(run),workers=1,no_notify=True)
            self.assertEqual(self.engine.schedule_continue(args),1)
            self.assertEqual(self.called,['B','C'])
            self.now+=50000;self.fail=None;self.called=[]
            self.assertEqual(self.engine.schedule_continue(args),0)
        self.assertEqual(self.called,['C'])
        state=json.loads((run/'schedule_state.json').read_text())
        self.assertEqual(state['elapsed'],50)
        self.assertEqual(len(state['attempts']),3)
        self.assertEqual(len([p for p in (self.root/'runs').iterdir() if not p.name.startswith('.')]),1)
        log=(run/'schedule.log').read_text()
        for key in ('A','B','C'):self.assertEqual(log.count('NOTE: success '+key),1)
        self.assertNotIn('ERROR: old failure',log)
        self.assertIn('3 parts',log)
        self.assertIn('50.0 seconds',log)
        self.assertIn('ERROR: old failure B',(run/'attempts/part-001/tasks/B/logs/task.log').read_text())
        self.assertEqual({p.name for p in (run/'tasks').iterdir()},{'A','B','C'})
        self.assertTrue(all(not t['skip'] for t in self.engine.load_schedule(run/'Schedule.xlsx')))

    def test_another_process_cannot_continue_locked_schedule(self):
        with patch.object(self.engine,'scheduler_task',self.execute),contextlib.redirect_stdout(io.StringIO()): self.engine.schedule_run(self.args)
        run=next(p for p in (self.root/'runs').iterdir() if not p.name.startswith('.'))
        with self.engine.schedule_lock(run),self.assertRaisesRegex(ValueError,'already running'):
            self.engine.schedule_continue(argparse.Namespace(run_dir=str(run),workers=1,no_notify=True))

    def test_ui_uses_cumulative_schedule_time_and_reports_retained_paths(self):
        app=ui.Workbench(self.root)
        try:
            item=dict(id='test',tasks={},started=1000,action='continue')
            app.event(item,dict(event='schedule-state',path=str(self.root/'runs/x'),schedule_state={'elapsed':20,'attempts':[{'status':'FAILED'},{'status':'RUNNING','started':5000}]}))
            self.assertEqual(item['elapsed_base'],20)
            self.assertEqual(item['started'],5000)
            app.event(item,dict(event='schedule-state',path=str(self.root/'runs/x'),schedule_state={'elapsed':35,'attempts':[{'status':'FAILED'},{'status':'SUCCESS'}]}))
            self.assertEqual(item['schedule_elapsed'],35)
        finally: app.awake.close()

if __name__=='__main__': unittest.main()

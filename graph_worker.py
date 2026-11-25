"""Dependency orchestration for frozen Run stream tasks, using engine.py once/task."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import sys
import time
import traceback

from engine import run_sas
import stream_worker


def execute(folder, runner=run_sas, event_sink=None):
    event_sink=event_sink or stream_worker.emit
    folder=Path(folder).resolve()
    plan=json.loads((folder/'task-graph-plan.json').read_text(encoding='utf-8'))
    definitions=plan['tasks']; tasks={t['task_id']:dict(t,status='PENDING',elapsed=0,message='') for t in definitions}
    started=plan.get('started') or time.time();control=os.environ.get('PYSAS_UI_CONTROL_FILE');stopped=False
    def stopping():return bool(control and Path(control).is_file())
    def finish(task,status,message):
        task.update(status=status,message=message)
        event_sink('finish',key=task['task_id'],name=task['program'],kind='task',status=status,elapsed=task['elapsed'],message=message)
    def run(definition):
        key=definition['task_id']
        finished=False
        def events(event,**values):
            nonlocal finished
            if event=='stream-result':return
            if event=='finish':finished=True
            values.update(key=key,name=definition['program'],kind='task',stream_task=True,setup=definition['setup'])
            event_sink(event,**values)
        path=folder/definition['path']
        try:
            stream_worker.execute(path,runner,event_sink=events,control_file=control)
            result=json.loads((path/'stream-result.json').read_text(encoding='utf-8'))
            return dict(status=result['status'],elapsed=result['elapsed_seconds'],message='; '.join(result['errors']),emitted=finished)
        except Exception as exc:
            traceback.print_exc();return dict(status='FAILED',elapsed=0,message=str(exc),emitted=False)
    event_sink('plan',tasks=definitions)
    with ThreadPoolExecutor(max_workers=plan['workers'],thread_name_prefix='graph-task') as pool:
        running={}
        while any(t['status']=='PENDING' for t in tasks.values()) or running:
            stopped=stopped or stopping()
            for task in tasks.values():
                if task['status']!='PENDING':continue
                parents=[tasks[key]['status'] for key in task['depends_on']]
                if stopped:finish(task,'CANCELLED','Graph stopped before this task started.')
                elif any(s not in {'PENDING','RUNNING','SUCCESS'} for s in parents):finish(task,'BLOCKED_DEPENDENCY','A prerequisite did not finish successfully.')
                elif all(s=='SUCCESS' for s in parents) and len(running)<plan['workers']:
                    if stopping():stopped=True;finish(task,'CANCELLED','Graph stopped before this task started.');continue
                    task['status']='RUNNING';running[pool.submit(run,task)]=task
            if running:
                done,_=wait(running,timeout=.1,return_when=FIRST_COMPLETED)
                for future in done:
                    task=running.pop(future);result=future.result();emitted=result.pop('emitted');task.update(result)
                    # A worker exception before a normal stream finish still has a final event.
                    if not emitted:event_sink('finish',key=task['task_id'],name=task['program'],kind='task',path=str(folder/task['path']),
                                             status=task['status'],elapsed=task['elapsed'],message=task['message'])
            elif any(t['status']=='PENDING' for t in tasks.values()):
                # Frozen plans are acyclic; corrupt plans must fail rather than spin.
                for task in tasks.values():
                    if task['status']=='PENDING':finish(task,'BLOCKED_DEPENDENCY','No runnable prerequisite chain remains.')
    elapsed=time.time()-started
    status='CANCELLED' if stopped else 'SUCCESS' if all(t['status']=='SUCCESS' for t in tasks.values()) else 'FAILED'
    fields=['task_id','program','status','elapsed','message']
    with (folder/'run_summary.csv').open('w',encoding='utf-8',newline='') as output:
        writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(tasks.values())
    with (folder/'run.log').open('w',encoding='utf-8') as output:
        output.write(f'PySAS graph: {plan["name"]}\nStatus: {status}\nElapsed: {elapsed:.1f}s\n')
        output.write('Each task is one engine.py submission. Shared setup is prepended to each task.\nFailed prerequisites block descendants; independent branches can finish.\n')
        if plan['mode']=='task':output.write('Manual task run: dependency execution was intentionally omitted.\n')
        if plan['mode']=='selection':
            output.write('Selected-task run: '+', '.join(plan['selected_task_ids'])+'. Only dependencies inside this selection are scheduled.\n')
        if plan.get('external_prerequisites'):
            output.write('Unselected prerequisites were assumed available, not submitted:\n')
            for edge in plan['external_prerequisites']:output.write('  '+edge['from']+' -> '+edge['to']+'\n')
        for task in tasks.values():
            output.write('\n\n=== '+task['task_id']+' · '+task['program']+' · '+task['status']+' ===\n')
            log=folder/task['path']/'run.log'
            output.write(log.read_text(encoding='utf-8') if log.is_file() else task['message'])
    (folder/'status.txt').write_text(f'source={plan["name"]}\nstatus={status}\nstarted={datetime.fromtimestamp(started,timezone.utc).isoformat()}\nelapsed_seconds={elapsed}\n',encoding='utf-8')
    (folder/'graph-result.json').write_text(json.dumps(dict(status=status,elapsed=elapsed,tasks=list(tasks.values())),ensure_ascii=False,indent=2),encoding='utf-8')
    event_sink('summary',path=str(folder),tasks=[dict(t,task_dir=str(folder/t['path'])) for t in tasks.values()])
    event_sink('graph-result',path=str(folder),status=status,elapsed=elapsed,message='Graph stopped.' if stopped else 'All tasks finished.' if status=='SUCCESS' else 'Some tasks failed or were blocked. Inspect the task logs.')
    return 0 if status=='SUCCESS' else 130 if status=='CANCELLED' else 1


if __name__=='__main__':
    try:sys.exit(execute(sys.argv[1]))
    except Exception:traceback.print_exc();sys.exit(1)

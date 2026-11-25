"""One bounded scheduler for graph containers and frozen Run stream submissions."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

from engine import run_sas
import stream_worker


def execute(folder, runner=run_sas, event_sink=None):
    event_sink=event_sink or stream_worker.emit;folder=Path(folder).resolve()
    plan=json.loads((folder/'task-graph-plan.json').read_text(encoding='utf-8'))
    definitions=[dict(t,parent_id=None if t.get('parent_id')==plan.get('root_parent') else t.get('parent_id')) for t in plan['tasks']]
    tasks={t['task_id']:dict(t,status='PENDING',elapsed=0,message='',started=None) for t in definitions}
    started=plan.get('started') or time.time();control=os.environ.get('PYSAS_UI_CONTROL_FILE');stopped=False
    groups={key:t for key,t in tasks.items() if t.get('kind')=='graph'}
    children={key:[t for t in tasks.values() if t.get('parent_id')==key] for key in [None,*groups]}
    cancelled_groups=set();progress={}
    def terminal(task):return task['status'] not in {'PENDING','RUNNING'}
    def ancestors(task):
        result=[];key=task.get('parent_id')
        while key is not None:
            if key in result or key not in tasks:raise ValueError('Invalid containing graph in the frozen plan.')
            result.append(key);key=tasks[key].get('parent_id')
        return result
    ancestry={key:ancestors(t) for key,t in tasks.items()}
    def stopping():return bool(control and Path(control).is_file())
    def finish(task,status,message):
        task.update(status=status,message=message,elapsed=time.time()-task['started'] if task.get('started') else 0)
        if task['task_id'] in groups:
            for child in children[task['task_id']]:
                if child['status']=='PENDING':finish(child,'CANCELLED' if status=='CANCELLED' else 'BLOCKED_DEPENDENCY',message)
            artifacts(folder/task['path'],children[task['task_id']],task['program'],status,task['elapsed'],task.get('started') or started)
        event_sink('finish',key=task['task_id'],name=task['program'],kind=task.get('kind','task'),path=str(folder/task['path']),status=status,elapsed=task['elapsed'],message=message)
    def run(definition):
        key=definition['task_id'];finished=False
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
    def artifacts(base,records,name,status,elapsed,start,*,root=False):
        fields=['task_id','program','status','elapsed','message','path','kind','parent_id']
        with (base/'run_summary.csv').open('w',encoding='utf-8',newline='') as output:
            writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore');writer.writeheader()
            writer.writerows(dict(t,path=(folder/t['path']).relative_to(base).as_posix()) for t in records)
        with (base/'run.log').open('w',encoding='utf-8') as output:
            output.write(f'PySAS graph: {name}\nStatus: {status}\nElapsed: {elapsed:.1f}s\n')
            output.write('Each source task is one engine.py submission. Shared setup is prepended from outer to inner graphs.\nFailed prerequisites block descendants; independent branches can finish.\n')
            if root:
                if plan['mode']=='task':output.write('Manual task run: prerequisite execution outside this card was intentionally omitted.\n')
                if plan['mode']=='selection':output.write('Selected-task run: '+', '.join(plan['selected_task_ids'])+'. Only dependencies inside this selection are scheduled.\n')
                if plan.get('graph_path'):output.write('Graph level: '+' / '.join(plan['graph_path'])+'\n')
                if plan.get('external_prerequisites'):
                    output.write('Unselected prerequisites were assumed available, not submitted:\n')
                    for edge in plan['external_prerequisites']:output.write('  '+edge['from']+' -> '+edge['to']+'\n')
            for task in records:
                output.write('\n\n=== '+task['task_id']+' · '+task['program']+' · '+task['status']+' ===\n')
                log=folder/task['path']/'run.log'
                if log.is_file():
                    with log.open(encoding='utf-8') as source:shutil.copyfileobj(source,output,length=1024*1024)
                else:output.write(task['message'])
        (base/'status.txt').write_text(f'source={name}\nstatus={status}\nstarted={datetime.fromtimestamp(start,timezone.utc).isoformat()}\nelapsed_seconds={elapsed}\n',encoding='utf-8')
        (base/'graph-result.json').write_text(json.dumps(dict(status=status,elapsed=elapsed,tasks=records),ensure_ascii=False,indent=2),encoding='utf-8')
    event_sink('plan',tasks=definitions)
    with ThreadPoolExecutor(max_workers=plan['workers'],thread_name_prefix='graph-task') as pool:
        running={}
        while any(not terminal(t) for t in tasks.values()) or running:
            stopped=stopped or stopping();changed=False
            for key,group in groups.items():
                if (folder/group['path']/'_cancel.request').is_file():cancelled_groups.add(key)
            # A container only finishes after every direct child is terminal.
            # No executor slot is held while waiting on a nested graph.
            for key,group in reversed(list(groups.items())):
                if group['status']!='RUNNING':continue
                complete=sum(terminal(child) for child in children[key])
                if progress.get(key)!=complete:
                    progress[key]=complete;event_sink('progress',key=key,phase='Running graph',progress=f'{complete}/{len(children[key])} cards finished')
                if all(terminal(child) for child in children[key]):
                    cancelled=stopped or key in cancelled_groups or any(a in cancelled_groups for a in ancestry[key])
                    status='CANCELLED' if cancelled else 'SUCCESS' if all(c['status']=='SUCCESS' for c in children[key]) else 'FAILED'
                    finish(group,status,'Nested graph stopped.' if cancelled else 'All inner tasks finished.' if status=='SUCCESS' else 'An inner task failed, was cancelled or was blocked.')
                    changed=True
            used={key:sum(key in ancestry[t['task_id']] for t in running.values()) for key in groups}
            for task in tasks.values():
                key=task['task_id'];cancelled=stopped or key in cancelled_groups or any(a in cancelled_groups for a in ancestry[key])
                if task['status']=='RUNNING' and key not in groups:
                    if cancelled:(folder/task['path']/'_cancel.request').touch(exist_ok=True)
                    continue
                if task['status']!='PENDING':continue
                parent=tasks.get(task.get('parent_id'))
                if cancelled:finish(task,'CANCELLED','Stopped before this card started.');changed=True;continue
                if parent and parent['status']!='RUNNING':
                    if terminal(parent):finish(task,'BLOCKED_DEPENDENCY','The containing graph did not start successfully.');changed=True
                    continue
                parents=[tasks[p]['status'] for p in task['depends_on']]
                if any(s not in {'PENDING','RUNNING','SUCCESS'} for s in parents):
                    finish(task,'BLOCKED_DEPENDENCY','A prerequisite did not finish successfully.');changed=True;continue
                if not all(s=='SUCCESS' for s in parents):continue
                if key in groups:
                    task.update(status='RUNNING',started=time.time());changed=True
                    (folder/task['path']/'run.log').write_text('Nested graph: '+task['program']+'\nRunning inner tasks…\n',encoding='utf-8')
                    event_sink('start',key=key,name=task['program'],kind='graph',path=str(folder/task['path']))
                elif len(running)<plan['workers'] and all(used[a]<groups[a]['workers'] for a in ancestry[key]):
                    if stopping():stopped=True;finish(task,'CANCELLED','Graph stopped before this task started.');changed=True;continue
                    task.update(status='RUNNING',started=time.time());running[pool.submit(run,task)]=task;changed=True
                    for a in ancestry[key]:used[a]+=1
            if running:
                done,_=wait(running,timeout=.1,return_when=FIRST_COMPLETED)
                for future in done:
                    task=running.pop(future);result=future.result();emitted=result.pop('emitted');task.update(result);changed=True
                    if not emitted:event_sink('finish',key=task['task_id'],name=task['program'],kind='task',path=str(folder/task['path']),status=task['status'],elapsed=task['elapsed'],message=task['message'])
            elif not changed and any(not terminal(t) for t in tasks.values()):
                # A corrupt frozen plan cannot leave an idle scheduler spinning.
                for task in tasks.values():
                    if task['status']=='PENDING':finish(task,'BLOCKED_DEPENDENCY','No runnable prerequisite chain remains.')
                if not any(t['status']=='PENDING' for t in tasks.values()) and not groups:break
    elapsed=time.time()-started
    status='CANCELLED' if stopped else 'SUCCESS' if all(t['status']=='SUCCESS' for t in tasks.values()) else 'FAILED'
    for key,group in reversed(list(groups.items())):
        if not (folder/group['path']/'graph-result.json').is_file():artifacts(folder/group['path'],children[key],group['program'],group['status'],group['elapsed'],group.get('started') or started)
    artifacts(folder,children[None],plan['name'],status,elapsed,started,root=True)
    # The root result also retains descendants for history and diagnostic tooling.
    (folder/'graph-result.json').write_text(json.dumps(dict(status=status,elapsed=elapsed,tasks=list(tasks.values())),ensure_ascii=False,indent=2),encoding='utf-8')
    event_sink('summary',path=str(folder),tasks=[dict(t,task_dir=str(folder/t['path'])) for t in tasks.values()])
    event_sink('graph-result',path=str(folder),status=status,elapsed=elapsed,message='Graph stopped.' if stopped else 'All tasks finished.' if status=='SUCCESS' else 'Some tasks failed or were blocked. Inspect the task logs.')
    return 0 if status=='SUCCESS' else 130 if status=='CANCELLED' else 1


if __name__=='__main__':
    try:sys.exit(execute(sys.argv[1]))
    except Exception:traceback.print_exc();sys.exit(1)

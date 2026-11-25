"""Immediate run registration and background preparation; one existing worker per run."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
import uuid

import ui_stream

SAS_ACTIONS={'run','watch','schedule','continue','stream','server-refresh','task-graph'}
ACTIONS=SAS_ACTIONS|{'bundle-pack','bundle-unpack','bundle-verify','egp-inspect','egp-extract','egp-pack'}


class Launches:
    def __init__(self,app):
        self.app=app;self.pending={};self.pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='run-preparation')
    def working(self):
        with self.app.lock:return bool(self.pending)
    def close(self):self.pool.shutdown(wait=True,cancel_futures=False)
    def start(self,data):
        if not isinstance(data,dict) or data.get('action') not in ACTIONS:raise ValueError('Choose a supported run or project action.')
        if data['action']=='stream' and not isinstance(data.get('stream'),dict):raise ValueError('Choose a Run stream definition.')
        if data['action']=='task-graph' and not isinstance(data.get('graph'),dict):raise ValueError('Choose a task graph definition.')
        if data['action'] in SAS_ACTIONS and os.name!='nt':raise ValueError('SAS execution requires Windows with Enterprise Guide.')
        request=json.loads(json.dumps(data));action=request['action']
        name=(request.get('stream',{}).get('name') if action=='stream' else request.get('display_name') or request.get('program') or request.get('workbook') or request.get('run_dir')) or action.replace('-',' ')
        if action=='task-graph':
            name=request.get('display_name') or request['graph'].get('name') or 'Graph'
            if request.get('task_id') and not request.get('display_name'):name=(name+' · '+str(request['task_id']))[:120]
        key=uuid.uuid4().hex;started=time.time()
        item=dict(id=key,action=action,name=str(name),default_name=str(name),display_name=request.get('display_name',''),status='RUNNING',preparing=True,phase='Preparing run',started=started,finished=None,args=[],tasks={},message='Preparing run…',can_cancel_file=True)
        if action.startswith('bundle-'): item['code_root']=str(Path(request.get('code_root') or self.app.root).expanduser().resolve())
        if action=='task-graph':item.update(graph_id=request['graph'].get('id'),graph_task_id=request.get('task_id'))
        item['tasks']['_preparing']=dict(key='_preparing',name=item['name'],kind='preparation',status='RUNNING',started=started,message='Preparing run…',can_cancel_file=False)
        with self.app.lock:
            if getattr(self.app,'closing',False):raise ValueError('PySAS is closing.')
            if self.app.storage_busy and not self.app.exports.working():raise ValueError('Wait for the saved-data operation to finish.')
            if len(self.pending)>=32:raise ValueError('Many runs are preparing. Wait for one to finish.')
            if action.startswith('bundle-') and any(c.get('action','').startswith('bundle-') and c.get('status') in {'RUNNING','STOPPING'} and os.path.normcase(c.get('code_root') or str(self.app.root))==os.path.normcase(item['code_root']) for c in self.app.commands.values()):raise ValueError('This folder already has an active bundle operation.')
            if action=='watch' and any(c.get('action')=='watch' and c.get('status') in {'RUNNING','STOPPING'} for c in self.app.commands.values()):raise ValueError('The watcher is already running.')
            if action=='task-graph' and any(c.get('action')=='task-graph' and c.get('graph_id')==item['graph_id'] and c.get('status') in {'RUNNING','STOPPING'} and (not item['graph_task_id'] or not c.get('graph_task_id') or c['graph_task_id']==item['graph_task_id']) for c in self.app.commands.values()):raise ValueError('This graph or task is already running. Stop it or wait for it to finish.')
            if action=='continue':
                import ui_storage
                previous=self.app.run_folder(request.get('run_dir'))
                if previous:
                    if previous in ui_storage.protected_runs(self.app) or self.app.exports.protects(previous):raise ValueError('This schedule is already running or its ZIP is preparing.')
                    item['resume_path']=self.app.relative(previous)
                    owner=next((c for c in sorted(self.app.commands.values(),key=lambda c:c['started'],reverse=True) if self.app.history_key(c.get('path'))==self.app.history_key(item['resume_path'])),None)
                    if owner:request['display_name']=owner.get('display_name') or owner['name'];item['name']=request['display_name'];item['tasks']['_preparing']['name']=item['name']
            self.pending[key]=threading.Event();self.app.commands[key]=item;self.app.save(item);response=json.loads(json.dumps(item))
        self.pool.submit(self.prepare,key,request)
        return {'id':key,'command':response}
    def cancel(self,key):
        with self.app.lock:
            event=self.pending.get(key)
            if not event or not self.app.commands[key].get('preparing'):return False
            event.set();item=self.app.commands[key];item.update(status='STOPPING',message='Cancelling preparation…')
            for task in item['tasks'].values():task.update(status='CANCELLING',message=item['message'])
            self.app.save(item)
            return True
    def cancelled(self,key):
        with self.app.lock:return self.pending[key].is_set()
    def progress(self,key,message):
        with self.app.lock:
            item=self.app.commands[key]
            if item['status']!='RUNNING':return
            item['message']=message
            for task in item['tasks'].values():task['message']=message
    def prepare(self,key,request):
        app=self.app
        try:
            folder=app.storage/'artifacts'/key;folder.mkdir(parents=True,exist_ok=True)
            spec=folder/'launch'/'request.json';spec.parent.mkdir(exist_ok=True)
            from pysas_ui import atomic_json
            atomic_json(spec,request)
            with app.lock:
                item=app.commands[key];item['launch_request']=app.relative(spec);app.save(item)
            if self.cancelled(key):raise InterruptedError('Cancelled before submission.')
            if request['action']=='stream':
                # Preserve retry choices even when refresh fails, then freeze the
                # refreshed known paths/current shared WORK for the actual worker.
                request['stream']=ui_stream.refresh_document(app,request.get('stream'))
                atomic_json(spec,request)
            if self.cancelled(key):raise InterruptedError('Cancelled before submission.')
            app.launch(request,reserved_id=key)
        except Exception as exc:
            with app.lock:
                item=app.commands[key]
                # A worker-start failure may already have written its run evidence.
                item.update(preparing=False,status='CANCELLED' if isinstance(exc,InterruptedError) else 'FAILED',finished=time.time(),message=str(exc))
                item['elapsed']=item['finished']-item['started']
                for task in item['tasks'].values():
                    if task.get('status') in {'RUNNING','CANCELLING','PENDING'}:task.update(status=item['status'],message=str(exc),elapsed=item['elapsed'],finished=item['finished'])
                with (app.storage/(key+'.txt')).open('a',encoding='utf-8') as output:output.write('Preparation '+item['status']+': '+str(exc)+'\n')
                app.save(item)
        finally:
            with app.lock:self.pending.pop(key,None)
    def replay(self,data):
        app=self.app;key=data.get('command');path=data.get('path')
        with app.lock:
            item=app.commands.get(key) if key else next((c for c in sorted(app.commands.values(),key=lambda c:c['started'],reverse=True) if app.history_key(c.get('path'))==app.history_key(path) and path),None)
            if item and item.get('status') in {'RUNNING','STOPPING'}:raise ValueError('This run is still active.')
            item=json.loads(json.dumps(item)) if item else None
        if data.get('mode')=='continue':
            folder=app.run_folder(path or (item or {}).get('path'))
            if not folder or not (folder/'schedule_state.json').is_file():raise ValueError('Choose an interrupted schedule to continue.')
            if (item or {}).get('action') not in {None,'schedule','continue'}:raise ValueError('Only schedules can be continued.')
            args=(item or {}).get('args',[]);workers=args[args.index('--workers')+1] if '--workers' in args else 10
            return self.start(dict(action='continue',run_dir=app.relative(folder),workers=data.get('workers') or workers))
        if item and item.get('launch_request'):
            spec=app.resolve(item['launch_request'])
            if spec.stat().st_size>20*1024**2:raise ValueError('Saved launch configuration is too large.')
            request=json.loads(spec.read_text(encoding='utf-8'))
            if request['action']=='continue':
                original=next((c for c in sorted(app.commands.values(),key=lambda c:c['started']) if c.get('action')=='schedule' and app.history_key(c.get('path'))==app.history_key(item.get('path') or item.get('resume_path'))),None)
                if original:return self.replay({'command':original['id'],'mode':'again'})
                raise ValueError('This continuation has no original schedule configuration. Choose the workbook in Run.')
            request.pop('plan_revision',None)
            if item.get('display_name'):
                request['display_name']=item['display_name']
                if request['action']=='stream':request['stream']['name']=item['display_name']
                if request['action']=='task-graph' and not request.get('task_id'):request['graph']['name']=item['display_name']
            return self.start(request)
        folder=app.run_folder(path or (item or {}).get('path'))
        if folder and (folder/'stream-plan.json').is_file():
            document=json.loads((folder/'stream-plan.json').read_text(encoding='utf-8'))['document']
            for ref,_ in ui_stream.asset_refs(document):ref['path']=app.relative(folder/ref['path'])
            return self.start(dict(action='stream',stream=document))
        if item and item.get('action') in {'run','schedule'}:
            args=item.get('args',[]);request={'action':item['action']}
            for flag in ('workbook','project','template','lib','workers'):
                option='--'+flag
                if option in args and args.index(option)+1<len(args):request[flag]=args[args.index(option)+1]
            if item['action']=='run':
                if len(args)>2 and args[2]!='--init-dir':request['program']=args[2]
                else:
                    candidates=[arg for arg in args[2:] if arg.lower().endswith('.sas') and arg not in {request.get('lib')}]
                    if candidates:request['program']=candidates[-1]
                plan=item.get('execution_plan',{})
                target=next((f['path'] for f in plan.get('files',[]) if f['role']=='program'),None)
                if target:request['program']=target
                request['initialization_mode']='override' if request.get('lib') else 'shared'
                request['tables']='--tables' in args
                if '--parameters' in args:
                    parameter=app.input_path(args[args.index('--parameters')+1]);request.update(use_parameters=True,parameters_name=parameter.name,parameters_text=parameter.read_text(encoding='utf-8'))
            if item.get('display_name'):request['display_name']=item['display_name']
            return self.start(request)
        raise ValueError('This older run has no saved launch configuration. Open Run to choose its inputs again.')

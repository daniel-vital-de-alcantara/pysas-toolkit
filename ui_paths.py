"""Portable UI data locations, independent of the installed app and CLI defaults."""
from pathlib import Path, PurePosixPath
import json
import shutil

CONFIGS = {'folders.json','bundle-paths.json','shared-work.json','preferences.json','parameters-settings.json'}

def locations(root, saved=None):
    file=root/'.pysas-locations.json'
    if saved is None: saved=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    result={}
    for key in ('tasks','settings'):
        value=saved.get(key,key)
        if not isinstance(value,str) or not value.strip():raise ValueError('Invalid '+key+' data location.')
        p=Path(value).expanduser();result[key]=(p if p.is_absolute() else root/p).resolve()
    a,b=result.values()
    if root.is_relative_to(a) or root.is_relative_to(b) or a==b or a.is_relative_to(b) or b.is_relative_to(a):
        raise ValueError('Tasks and settings must be separate folders, not the app folder or inside each other.')
    return result

def resolve(app,value):
    value=str(value).replace('\\','/')
    if value.startswith('/') or Path(value).is_absolute():
        path=Path(value).expanduser().resolve()
        if not any(path.is_relative_to(base) for base in (app.root,app.tasks,app.settings)):
            raise ValueError('Choose a file inside the workspace or configured data folders.')
        local=path.relative_to(app.root).as_posix() if path.is_relative_to(app.root) else ''
        if any(local==source or local.startswith(source+'/') for source in getattr(app,'legacy_moves',{})):
            value=local
        else:return path
    for source,target in getattr(app,'legacy_moves',{}).items():
        if value==source or value.startswith(source+'/'):
            value=target+value[len(source):];break
    parts=PurePosixPath(value).parts
    if '..' in parts:raise ValueError('Choose a path inside the configured folder.')
    base=app.tasks if parts[:1]==('tasks',) else app.settings if parts[:1]==('settings',) else app.storage if parts[:1]==('.pysas-ui',) else app.root
    suffix=parts[1:] if base!=app.root else parts
    path=base.joinpath(*suffix).resolve()
    if not path.is_relative_to(base):raise ValueError('Path points outside its configured folder.')
    return path

def relative(app,path):
    path=Path(path).resolve()
    for base,prefix in ((app.storage,'.pysas-ui'),(app.tasks,'tasks'),(app.settings,'settings'),(app.root,'')):
        if path.is_relative_to(base):return (Path(prefix)/path.relative_to(base)).as_posix()
    return ''

def initialize(app):
    saved=locations(app.root);app.tasks=saved['tasks'];app.settings=saved['settings']
    app.storage=app.tasks/'.workbench'
    app.legacy_moves={}
    app.migration=None
    for p in (app.tasks/'files',app.tasks/'schedules',app.settings,app.storage):p.mkdir(parents=True,exist_ok=True)
    mapping=app.storage/'legacy-runs.json'
    if mapping.exists(): app.legacy_moves=json.loads(mapping.read_text(encoding='utf-8'))
    # First upgrade: keep old files intact and copy only missing configuration and
    # command artifacts. Old run folders stay readable in place; restored backups
    # and all newly executed runs use the new Tasks folder.
    legacy=app.root/'.pysas-ui'
    if legacy.is_dir() and not (app.storage/'legacy-imported.json').exists():
        for name in CONFIGS:
            if (legacy/name).is_file() and not (app.settings/name).exists():shutil.copy2(legacy/name,app.settings/name)
        for folder,destination in ((legacy/'parameters',app.settings/'parameters'),(legacy/'artifacts',app.storage/'artifacts')):
            if folder.is_dir():
                from ui_data import safe_files
                for source in safe_files(folder):
                    target=destination/source.relative_to(folder)
                    if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        for source in legacy.iterdir():
            if source.is_symlink() or not source.is_file() or source.name in CONFIGS or source.suffix not in {'.json','.txt','.jsonl'}:continue
            if not (app.storage/source.name).exists():shutil.copy2(source,app.storage/source.name)
        (app.storage/'legacy-imported.json').write_text('{}',encoding='utf-8')


def lock_folder(folder):
    """One writer across installations pointing at the same portable folder."""
    import os
    folder.mkdir(parents=True, exist_ok=True)
    handle=(folder/'.pysas.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0:handle.write(b'0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError('Another PySAS app is using this tasks or settings folder. Close that app before opening this installation.')
    return handle


def start_legacy_import(app):
    """Copy completed legacy runs into Tasks; publish the mapping only after success."""
    import contextlib
    import threading
    import uuid
    from pysas import schedule_lock
    from ui_data import safe_files
    with app.lock:
        if app.processes or app.storage_busy or app.uploading or app.metadata_jobs.working():
            raise ValueError('Finish commands and stop the watcher before importing old runs.')
        app.storage_busy=True
        app.migration=dict(status='WORKING',message='Scanning legacy run folders',done=0,total=0,runs=0)
    def work():
        completed=[];old_commands=None;old_moves=dict(app.legacy_moves)
        stage=app.tasks/('.pysas-import-'+uuid.uuid4().hex)
        try:
            from ui_storage import protected_runs
            protected=protected_runs(app)
            rows=[h for h in app.history(limit=None) if h['path'].replace('\\','/').startswith(('runs/','runner/runs/')) and h['status'] not in {'RUNNING','STOPPING','UNKNOWN'} and app.run_folder(h['path']) not in protected]
            entries=[]
            for row in rows:
                source=app.root/row['path'];kind='schedules' if row['kind']=='schedule' else 'files'
                target=app.tasks/kind/source.name
                if target.exists():target=target.with_name(target.name+'_import_'+uuid.uuid4().hex[:8])
                entries.append((row,source,target,list(safe_files(source))))
            app.migration['total']=sum(p.stat().st_size for _,_,_,files in entries for p in files)
            moves={}
            for index,(row,source,target,files) in enumerate(entries):
                destination=stage/str(index);destination.mkdir(parents=True)
                with schedule_lock(source) if row['kind']=='schedule' else contextlib.nullcontext():
                    for file in files:
                        if file.name=='.schedule.lock':continue
                        out=destination/file.relative_to(source);out.parent.mkdir(parents=True,exist_ok=True)
                        with file.open('rb') as stream,out.open('xb') as output:
                            while True:
                                data=stream.read(1024*1024)
                                if not data:break
                                output.write(data)
                                with app.lock:
                                    app.migration['done']+=len(data);app.migration['message']='Copying '+row['name']
                        shutil.copystat(file,out)
                destination.rename(target);completed.append(target)
                moves[row['path'].replace('\\','/')]=relative(app,target).replace('\\','/')
            def remap(value):
                if isinstance(value,list):return [remap(v) for v in value]
                if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
                if not isinstance(value,str):return value
                normal=value.replace('\\','/');root=str(app.root).replace('\\','/')+'/'
                local=normal[len(root):] if normal.startswith(root) else normal
                for old,new in moves.items():
                    if local==old or local.startswith(old+'/'):return new+local[len(old):]
                return value
            with app.lock:
                old_commands=json.loads(json.dumps(app.commands))
                app.commands=remap(app.commands)
                for command in app.commands.values():app.save(command)
                app.legacy_moves.update(moves)
                temp=app.storage/'legacy-runs.tmp';temp.write_text(json.dumps(app.legacy_moves),encoding='utf-8');temp.replace(app.storage/'legacy-runs.json')
                app.invalidate_lists()
                app.migration.update(status='READY',runs=len(moves),message=f'Imported {len(moves)} completed runs into Tasks. Original folders were preserved; their duplicate history rows are hidden.')
        except Exception as exc:
            with app.lock:
                app.legacy_moves=old_moves
                if old_commands is not None:
                    app.commands=old_commands
                    for command in app.commands.values():app.save(command)
                for folder in completed:shutil.rmtree(folder)
                app.migration.update(status='FAILED',message=str(exc))
        finally:
            try:
                if stage.exists():shutil.rmtree(stage)
            except OSError as exc:
                with app.lock:app.migration['message'] += ' Temporary cleanup: '+str(exc)
            finally:
                with app.lock:app.storage_busy=False
    threading.Thread(target=work,daemon=True).start()
    return dict(app.migration)

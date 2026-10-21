"""Background ZIP exports, saved storage accounting, and explicit run cleanup."""
from __future__ import annotations
import contextlib
import json
import os
import re
from pathlib import Path
import shutil
import threading
import time
import uuid
from pysas import schedule_lock
from ui_data import export_backup, safe_files, write_archive

ACTIVE = {'RUNNING', 'STOPPING', 'CANCELLING', 'PENDING'}
FAILED = {'FAILED', 'SAS_ERROR', 'EXPORT_ERROR', 'TIMED_OUT', 'CONNECTION_LOST', 'CANCELLED', 'STOPPED', 'STOPPED_ON_ERROR', 'BLOCKED_DEPENDENCY'}
FINISHED = FAILED | {'SUCCESS', 'PARTIAL', 'SKIPPED_SUCCESS', 'SKIPPED_PREVIOUS'}


def run_folder(root, value, tasks=None):
    """Recognize new portable roots and legacy run folders without following links."""
    if not value: return None
    tasks = tasks or root/'tasks'
    value = str(value).replace('\\', '/')
    path = Path(value)
    if not path.is_absolute(): path = tasks.joinpath(*path.parts[1:]) if path.parts[:1] == ('tasks',) else root/path
    for base, prefix in ((tasks, ('files',)), (tasks, ('schedules',)), (root, ('runs',)), (root, ('runner','runs'))):
        try: parts = path.relative_to(base).parts
        except ValueError: continue
        count = len(prefix)+1
        if parts[:len(prefix)] != prefix or len(parts) < count or '..' in parts: continue
        folder = base.joinpath(*parts[:count])
        if any(p.is_symlink() for p in (folder,*folder.parents) if p.is_relative_to(base)): return None
        if folder.resolve().is_relative_to(base): return folder
    return None


def folder_size(folder):
    size = 0
    for path in safe_files(folder):
        try: size += path.stat().st_size
        except FileNotFoundError: pass
    return size


def storage_usage(app):
    return {'bytes': sum(folder_size(p) for p in (*[base for base,_ in app.run_bases()], app.storage/'artifacts', app.settings/'parameters', app.settings/'graphs', app.tasks/'graph-sources', app.tasks/'stream-sources')) + sum(p.stat().st_size for p in app.storage.glob('*') if p.is_file() and not p.is_symlink() and p.suffix in {'.txt', '.json', '.jsonl'}), 'export_bytes': folder_size(app.storage/'exports'), 'measured': time.time()}


class Exports:
    def __init__(self, app):
        self.app = app
        self.jobs = {}
        # Prepared downloads are session caches, excluded from portable backups.
        folder = app.storage/'exports'
        if folder.is_dir() and not folder.is_symlink(): shutil.rmtree(folder)

    def start(self, scope, relative=''):
        app = self.app
        if scope not in {'all', 'configs', 'run', 'project', 'task', 'command'}: raise ValueError('Choose saved data, configs, or a run folder.')
        with app.lock:
            if app.uploading: raise ValueError("Wait for file uploads to finish.")
            if app.storage_busy: raise ValueError('Wait for the current saved-data operation to finish.')
            if scope == 'all' and (app.processes or any(c.get('status') in ACTIVE for c in app.commands.values())):
                raise ValueError('Finish active commands and stop the watcher before exporting all saved data. Configs can be exported while jobs run.')
            folder = app.run_folder(relative) if scope == 'run' else app.resolve(relative) if scope == 'task' and app.run_folder(relative) else app.artifact_folder(relative) if scope == 'command' else app.extracted_project(relative) if scope == 'project' else None
            if scope == 'command' and folder and app.commands[folder.name].get('status') in ACTIVE: raise ValueError('Wait for this command to finish before creating its ZIP.')
            if scope == 'command' and not folder: raise ValueError('Choose a saved command artifact folder.')
            if scope == 'project' and not folder: raise ValueError('Choose a completed EGP extraction from Projects.')
            if scope == 'run' and (not folder or not folder.is_dir() or folder != app.resolve(relative)):
                raise ValueError('Choose an entire saved run folder.')
            if scope == 'task' and (not folder or not folder.is_dir()): raise ValueError('Choose an existing task folder.')
            if scope in {'run', 'task'} and app.run_folder(app.relative(folder)) in protected_runs(app): raise ValueError('Wait for this run to finish before creating its ZIP.')
            identifier = uuid.uuid4().hex
            job = dict(id=identifier, status='WORKING', scope=scope, path_source=app.relative(folder) if folder else '', started=time.time(), done=0, total=0, message='Scanning saved files')
            self.jobs[identifier] = job
            app.storage_busy = True
            # Capture metadata while locked; compression and filesystem walks run outside it.
            from ui_data import backup_manifest
            manifest = backup_manifest(app, scope == 'configs') if scope not in {'run', 'project', 'task', 'command'} else None
        def work():
            target = app.storage/'exports'/identifier/((folder.name+'.zip') if folder else ('PySAS-configs.zip' if scope == 'configs' else 'PySAS-saved-data.zip'))
            last = [0.0]
            def progress(done, total, message):
                if time.monotonic()-last[0] < .1 and done != total: return
                last[0] = time.monotonic()
                with app.lock: job.update(done=done, total=total, message=message)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if scope in {'run', 'project', 'task', 'command'}:
                    with target.open('w+b') as out:
                        write_archive(out, [(p, (Path(folder.name)/p.relative_to(folder)).as_posix()) for p in safe_files(folder) if p.name != '.schedule.lock'], progress)
                else:
                    stream, _ = export_backup(app, scope == 'configs', progress, target, manifest=manifest, before=job['started'])
                    stream.close()
                with app.lock: job.update(status='READY', message='ZIP ready', path=app.relative(target), bytes=target.stat().st_size)
            except Exception as exc:
                try: target.unlink(missing_ok=True)
                except OSError: pass
                with app.lock: job.update(status='FAILED', message=str(exc))
            finally:
                with app.lock: app.storage_busy = False
        threading.Thread(target=work, daemon=True).start()
        return dict(job)

    def working(self):
        return any(j['status'] == 'WORKING' for j in self.jobs.values())

    def protects(self, folder):
        return any(j['status'] == 'WORKING' and (j['scope'] == 'all' or (j['scope'] in {'run','task'} and self.app.run_folder(j['path_source']) == folder)) for j in self.jobs.values())

    def get(self, identifier):
        with self.app.lock:
            if identifier not in self.jobs: raise ValueError('Export not found. Prepare the ZIP again.')
            return dict(self.jobs[identifier])


def protected_runs(app):
    protected = set()
    for c in app.commands.values():
        # UNKNOWN may be an unmonitored worker after a crash; do not delete its output.
        held = any(j['status']=='WORKING' and j['scope']=='command' and Path(j['path_source']).name==c['id'] for j in app.exports.jobs.values())
        if c.get('status') in ACTIVE | {'UNKNOWN'} or held:
            if c.get('action') in {'schedule', 'continue', 'stream'}:
                folder = app.run_folder(c.get('path') or c.get('resume_path'))
                if folder: protected.add(folder)
            for t in c.get('tasks', {}).values():
                if t.get('status') in ACTIVE | {'UNKNOWN'} or held:
                    folder = app.run_folder(t.get('path'))
                    if folder: protected.add(folder)
    return protected


def cleanup_plan(app, mode):
    if mode not in {'failed', 'finished'}: raise ValueError('Choose failed runs or all finished runs.')
    wanted = FAILED if mode == 'failed' else FINISHED
    protected = protected_runs(app)
    statuses = {app.run_folder(h['path']): h['status'] for h in app.history(limit=None)}
    # Newest command wins when a schedule has several continuations.
    for c in sorted(app.commands.values(), key=lambda c: c.get('started', 0)):
        folder = app.run_folder(c.get('path'))
        if folder: statuses[folder] = c.get('status')
        for t in c.get('tasks', {}).values():
            folder = app.run_folder(t.get('path'))
            if folder and c.get('action') not in {'schedule', 'continue'}: statuses[folder] = t.get('status')
    folders = sorted(p for p, status in statuses.items() if p and p.is_dir() and p not in protected and status in wanted)
    unlocked = []
    for folder in folders:
        if folder.parent in {app.root/'runs',app.tasks/'schedules'}:
            try:
                with schedule_lock(folder): pass
            except (ValueError, OSError):
                protected.add(folder); continue
        unlocked.append(folder)
    folders = unlocked
    selected = set(folders)
    commands = []
    for identifier, c in app.commands.items():
        if c.get('status') not in FINISHED or not re.fullmatch(r'[a-zA-Z0-9_-]+', identifier): continue
        referenced = {app.run_folder(value) for value in [c.get('path'), *[t.get('path') for t in c.get('tasks', {}).values()]]} - {None}
        if referenced and referenced.issubset(selected): commands.append(identifier)
    extra = 0
    for identifier in commands:
        extra += folder_size(app.storage/'artifacts'/identifier)
        for suffix in ('.json', '.txt', '.events.jsonl', '.stop'):
            path = app.storage/(identifier+suffix)
            if path.is_file() and not path.is_symlink(): extra += path.stat().st_size
    return {'mode': mode, 'paths': [app.relative(p) for p in folders], 'commands': sorted(commands), 'runs': len(folders), 'bytes': sum(folder_size(p) for p in folders)+extra, 'protected': len(protected)}


def delete_runs(app, plan):
    """Revalidate the exact reviewed selection; rename each run before removing it."""
    current = cleanup_plan(app, plan['mode'])
    if current['paths'] != plan['paths'] or current['bytes'] != plan['bytes'] or current['commands'] != plan['commands']:
        raise ValueError('Saved runs changed. Review cleanup again before deleting.')
    removed = set()
    try:
        for relative in plan['paths']:
            folder = app.run_folder(relative)
            trash = folder.parent/('.pysas-cleanup-'+uuid.uuid4().hex)
            trash.parent.mkdir(parents=True, exist_ok=True)
            with schedule_lock(folder) if folder.parent in {app.root/'runs',app.tasks/'schedules'} else contextlib.nullcontext():
                folder.rename(trash)
                try: shutil.rmtree(trash)
                except OSError:
                    trash.rename(folder)
                    raise
            removed.add(relative)
    finally:
        for identifier, command in list(app.commands.items()):
            referenced = {app.relative(p) for p in [app.run_folder(value) for value in [command.get('path'), *[t.get('path') for t in command.get('tasks', {}).values()]]] if p}
            if identifier in plan['commands'] and referenced.issubset(removed):
                app.commands.pop(identifier)
                artifacts = app.storage/'artifacts'/identifier
                if artifacts.is_dir() and not artifacts.is_symlink(): shutil.rmtree(artifacts)
                for suffix in ('.json', '.txt', '.events.jsonl', '.stop'):
                    (app.storage/(identifier+suffix)).unlink(missing_ok=True)
            else:
                for key, task in list(command.get('tasks', {}).items()):
                    folder = app.run_folder(task.get('path'))
                    if folder and app.relative(folder) in removed: command['tasks'].pop(key)
                app.save(command)
        app.invalidate_lists()
    return {'runs': len(removed), 'bytes': plan['bytes']}

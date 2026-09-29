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
FAILED = {'FAILED', 'SAS_ERROR', 'CONNECTION_LOST', 'CANCELLED', 'STOPPED', 'STOPPED_ON_ERROR', 'BLOCKED_DEPENDENCY'}
FINISHED = FAILED | {'SUCCESS', 'PARTIAL', 'SKIPPED_SUCCESS', 'SKIPPED_PREVIOUS'}


def run_folder(root, value):
    """Return the top-level owned run, never a source/input or linked folder."""
    if not value: return None
    path = Path(value)
    path = path if path.is_absolute() else root / path
    try:
        relative = path.relative_to(root)
    except ValueError: return None
    parts = relative.parts
    if any(p in {'.', '..'} for p in parts): return None
    count = 2 if parts[:1] == ('runs',) else 3 if parts[:2] == ('runner', 'runs') else 0
    if not count or len(parts) < count: return None
    folder = root.joinpath(*parts[:count])
    if any(p.is_symlink() for p in [folder, *folder.parents] if p != root.parent): return None
    if not folder.resolve().is_relative_to(root): return None
    return folder


def folder_size(folder):
    size = 0
    for path in safe_files(folder):
        try: size += path.stat().st_size
        except FileNotFoundError: pass
    return size


def storage_usage(app):
    return {'bytes': sum(folder_size(p) for p in (app.root/'runs', app.root/'runner/runs', app.storage/'artifacts', app.storage/'parameters')) + sum(p.stat().st_size for p in app.storage.glob('*') if p.is_file() and not p.is_symlink() and p.suffix in {'.txt', '.json', '.jsonl'}), 'export_bytes': folder_size(app.storage/'exports'), 'measured': time.time()}


class Exports:
    def __init__(self, app):
        self.app = app
        self.jobs = {}
        # Prepared downloads are session caches, excluded from portable backups.
        folder = app.storage/'exports'
        if folder.is_dir() and not folder.is_symlink(): shutil.rmtree(folder)

    def start(self, scope, relative=''):
        app = self.app
        if scope not in {'all', 'configs', 'run'}: raise ValueError('Choose saved data, configs, or a run folder.')
        with app.lock:
            if app.uploading: raise ValueError("Wait for file uploads to finish.")
            if app.storage_busy: raise ValueError('Wait for the current saved-data operation to finish.')
            if scope == 'all' and (app.processes or any(c.get('status') in ACTIVE for c in app.commands.values())):
                raise ValueError('Finish active commands and stop the watcher before exporting all saved data. Configs can be exported while jobs run.')
            folder = run_folder(app.root, relative) if scope == 'run' else None
            if scope == 'run' and (not folder or not folder.is_dir() or folder != (app.root/relative).resolve()):
                raise ValueError('Choose an entire saved run folder.')
            if scope == 'run' and folder in protected_runs(app): raise ValueError('Wait for this run to finish before creating its ZIP.')
            identifier = uuid.uuid4().hex
            job = dict(id=identifier, status='WORKING', scope=scope, done=0, total=0, message='Scanning saved files')
            self.jobs[identifier] = job
            app.storage_busy = True
        def work():
            target = app.storage/'exports'/identifier/((folder.name+'.zip') if folder else ('PySAS-configs.zip' if scope == 'configs' else 'PySAS-saved-data.zip'))
            last = [0.0]
            def progress(done, total, message):
                if time.monotonic()-last[0] < .1 and done != total: return
                last[0] = time.monotonic()
                with app.lock: job.update(done=done, total=total, message=message)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if scope == 'run':
                    with target.open('w+b') as out:
                        write_archive(out, [(p, (Path(folder.name)/p.relative_to(folder)).as_posix()) for p in safe_files(folder) if p.name != '.schedule.lock'], progress)
                else:
                    stream, _ = export_backup(app, scope == 'configs', progress, target)
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

    def get(self, identifier):
        with self.app.lock:
            if identifier not in self.jobs: raise ValueError('Export not found. Prepare the ZIP again.')
            return dict(self.jobs[identifier])


def protected_runs(app):
    protected = set()
    for c in app.commands.values():
        # UNKNOWN may be an unmonitored worker after a crash; do not delete its output.
        if c.get('status') in ACTIVE | {'UNKNOWN'}:
            if c.get('action') in {'schedule', 'continue'}:
                folder = run_folder(app.root, c.get('path') or c.get('resume_path'))
                if folder: protected.add(folder)
            for t in c.get('tasks', {}).values():
                if t.get('status') in ACTIVE | {'UNKNOWN'}:
                    folder = run_folder(app.root, t.get('path'))
                    if folder: protected.add(folder)
    return protected


def cleanup_plan(app, mode):
    if mode not in {'failed', 'finished'}: raise ValueError('Choose failed runs or all finished runs.')
    wanted = FAILED if mode == 'failed' else FINISHED
    protected = protected_runs(app)
    statuses = {run_folder(app.root, h['path']): h['status'] for h in app.history(limit=None)}
    # Newest command wins when a schedule has several continuations.
    for c in sorted(app.commands.values(), key=lambda c: c.get('started', 0)):
        folder = run_folder(app.root, c.get('path'))
        if folder: statuses[folder] = c.get('status')
        for t in c.get('tasks', {}).values():
            folder = run_folder(app.root, t.get('path'))
            if folder and c.get('action') not in {'schedule', 'continue'}: statuses[folder] = t.get('status')
    folders = sorted(p for p, status in statuses.items() if p and p.is_dir() and p not in protected and status in wanted)
    unlocked = []
    for folder in folders:
        if folder.parent == app.root/'runs':
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
        referenced = {run_folder(app.root, value) for value in [c.get('path'), *[t.get('path') for t in c.get('tasks', {}).values()]]} - {None}
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
            folder = run_folder(app.root, relative)
            trash = app.storage/'cleanup'/uuid.uuid4().hex
            trash.parent.mkdir(parents=True, exist_ok=True)
            with schedule_lock(folder) if folder.parent == app.root/'runs' else contextlib.nullcontext():
                folder.rename(trash)
                try: shutil.rmtree(trash)
                except OSError:
                    trash.rename(folder)
                    raise
            removed.add(relative)
    finally:
        for identifier, command in list(app.commands.items()):
            referenced = {app.relative(p) for p in [run_folder(app.root, value) for value in [command.get('path'), *[t.get('path') for t in command.get('tasks', {}).values()]]] if p}
            if identifier in plan['commands'] and referenced.issubset(removed):
                app.commands.pop(identifier)
                artifacts = app.storage/'artifacts'/identifier
                if artifacts.is_dir() and not artifacts.is_symlink(): shutil.rmtree(artifacts)
                for suffix in ('.json', '.txt', '.events.jsonl', '.stop'):
                    (app.storage/(identifier+suffix)).unlink(missing_ok=True)
            else:
                for key, task in list(command.get('tasks', {}).items()):
                    folder = run_folder(app.root, task.get('path'))
                    if folder and app.relative(folder) in removed: command['tasks'].pop(key)
                app.save(command)
        app.invalidate_lists()
    return {'runs': len(removed), 'bytes': plan['bytes']}

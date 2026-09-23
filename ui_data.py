"""Portable run archives and historical duration estimates; no SAS execution."""
from __future__ import annotations
import csv
from datetime import datetime
import heapq
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import tempfile
import uuid
import zipfile

LIMIT = 10 * 1024**3
FORMAT = 'pysas-workbench-backup-1'

def portable(value):
    return str(value).replace('\\', '/').rstrip('/')


def safe_files(folder):
    if folder.is_symlink():
        return
    for base, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in sorted(names):
            p = Path(base) / name
            if not p.is_symlink() and p.is_file():
                yield p


def archive_folder(root, relative):
    folder = (root / relative).resolve()
    if not any(folder.is_relative_to(base) and folder != base for base in (root / 'runs', root / 'runner/runs')) or not folder.is_dir():
        raise ValueError('Choose a saved run folder.')
    out = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in safe_files(folder):
                z.write(p, (Path(folder.name) / p.relative_to(folder)).as_posix())
        out.seek(0)
        return out, folder.name + '.zip'
    except BaseException:
        out.close()
        raise


def export_backup(app):
    out = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            manifest = dict(format=FORMAT, workspace=str(app.root), folders=app.folders(),
                            bundle_settings=app.bundle_settings(), commands=list(app.commands.values()))
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            for base in (app.root / 'runs', app.root / 'runner/runs', app.storage / 'artifacts'):
                for p in safe_files(base):
                    z.write(p, p.relative_to(app.root).as_posix())
            for identifier in app.commands:
                p = app.storage / (identifier + '.txt')
                if p.is_file() and not p.is_symlink():
                    z.write(p, p.relative_to(app.root).as_posix())
        with zipfile.ZipFile(out) as check:
            if len(check.infolist()) > 200000 or sum(i.file_size for i in check.infolist()) > LIMIT or check.getinfo('manifest.json').file_size > 32 * 1024**2:
                raise ValueError('Saved data exceeds the 10 GB / 200,000 file backup limit. Download individual run folders instead.')
        out.seek(0)
        return out, 'PySAS-saved-data.zip'
    except BaseException:
        out.close()
        raise


def restore_backup(app, stream, length):
    if not 0 < length <= LIMIT:
        raise ValueError('Choose a PySAS backup ZIP up to 10 GB.')
    with tempfile.TemporaryDirectory(prefix='pysas-restore-', dir=app.storage) as temp:
        stage = Path(temp)
        archive = stage / 'upload.zip'
        with archive.open('wb') as f:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Backup upload was interrupted.')
                f.write(chunk)
                remaining -= len(chunk)
        try:
            z = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            raise ValueError('This is not a valid backup ZIP.') from exc
        with z:
            entries = z.infolist()
            if len(entries) > 200000 or sum(i.file_size for i in entries) > LIMIT:
                raise ValueError('Backup expands beyond the 10 GB / 200,000 file limit.')
            seen = set()
            for i in entries:
                name = i.filename
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith('/') or '\\' in name or ':' in name or any(p in {'.', '..'} or p.endswith((' ', '.')) for p in parts)
                    or any(re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', p) for p in parts)
                    or name.casefold() in seen or (i.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('Backup contains an unsafe or duplicate path.')
                seen.add(name.casefold())
                allowed = name == 'manifest.json' or (len(parts) >= 3 and parts[0] == 'runs') or (len(parts) >= 4 and parts[:2] == ('runner', 'runs')) or (len(parts) >= 4 and parts[:2] == ('.pysas-ui', 'artifacts')) or (len(parts) == 2 and parts[0] == '.pysas-ui' and re.fullmatch(r'[a-zA-Z0-9_-]+\.txt', parts[1]))
                if not allowed or i.is_dir():
                    raise ValueError('Backup contains an unsupported entry.')
            if 'manifest.json' not in seen or z.getinfo('manifest.json').file_size > 32 * 1024**2:
                raise ValueError('Backup manifest is missing or too large.')
            try:
                manifest = json.loads(z.read('manifest.json'))
            except (ValueError, UnicodeError) as exc:
                raise ValueError('Backup manifest is invalid.') from exc
            if not isinstance(manifest, dict):
                raise ValueError('Backup manifest must be an object.')
            if manifest.get('format') != FORMAT or not isinstance(manifest.get('commands'), list):
                raise ValueError('Choose a backup exported by PySAS Workbench.')
            # Extract only after every path and expansion limit is checked.
            unpacked = stage / 'data'
            z.extractall(unpacked)
            for info in entries:
                stamp = datetime(*info.date_time).timestamp()
                os.utime(unpacked / info.filename, (stamp, stamp))
        if not isinstance(manifest.get('workspace'), str) or not manifest['workspace']:
            raise ValueError('Backup has no source workspace.')
        for key in ('folders', 'bundle_settings'):
            if not isinstance(manifest.get(key), dict):
                raise ValueError('Backup settings are invalid.')
        if any(not isinstance(v, str) for v in manifest['folders'].values()):
            raise ValueError('Backup folder paths are invalid.')
        bundle = manifest['bundle_settings']
        if not isinstance(bundle.get('paths', []), list) or any(not isinstance(p, str) for p in bundle.get('paths', [])) or not isinstance(bundle.get('last', ''), str):
            raise ValueError('Backup bundle paths are invalid.')
        old_root = portable(manifest['workspace'])
        mappings = {}
        moves = []
        for prefix in ('runs', 'runner/runs'):
            base = unpacked / prefix
            if base.exists():
                for folder in base.iterdir():
                    destination = app.root / prefix / folder.name
                    if destination.exists():
                        destination = destination.with_name(folder.name + '_import_' + uuid.uuid4().hex[:8])
                    mappings[prefix + '/' + folder.name] = destination.relative_to(app.root).as_posix()
                    moves.append((folder, destination))
        ids = {}
        for item in manifest['commands']:
            if not isinstance(item, dict) or not isinstance(item.get('tasks', {}), dict) or not isinstance(item.get('args', []), list) or not isinstance(item.get('started'), (int, float)):
                raise ValueError('Backup command history is invalid.')
            if not isinstance(item.get('status'), str) or not isinstance(item.get('action'), str) or any(not isinstance(t, dict) or not isinstance(t.get('status'), str) for t in item.get('tasks', {}).values()):
                raise ValueError('Backup command status is invalid.')
            identifier = item.get('id', '')
            if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', identifier) or identifier in ids:
                raise ValueError('Backup has invalid command records.')
            ids[identifier] = uuid.uuid4().hex
        def remap(value):
            if isinstance(value, list): return [remap(v) for v in value]
            if isinstance(value, dict): return {k: remap(v) for k, v in value.items()}
            if not isinstance(value, str): return value
            normalized = portable(value)
            absolute = normalized.casefold() == old_root.casefold() or normalized.casefold().startswith(old_root.casefold() + '/')
            rel = normalized[len(old_root):].lstrip('/') if absolute else normalized
            for source, target in mappings.items():
                if rel == source or rel.startswith(source + '/'):
                    rel = target + rel[len(source):]
                    break
            return str(app.root / rel) if absolute else rel if rel != normalized or '\\' in value else value
        commands = []
        for original in manifest['commands']:
            item = remap(original)
            old_id = original['id']
            item['id'] = ids[old_id]
            item.pop('control_file', None)
            for record in [item, *item.get('tasks', {}).values()]:
                if record.get('status') in {'RUNNING', 'STOPPING', 'CANCELLING', 'PENDING'}:
                    record['status'] = 'UNKNOWN'
                record['can_cancel_file'] = False
            if item.get('download'):
                item['download'] = ids[old_id] + '/' + portable(item['download']).split('/', 1)[-1]
            commands.append(item)
            for src, dest in ((unpacked / '.pysas-ui' / (old_id + '.txt'), app.storage / (ids[old_id] + '.txt')),
                              (unpacked / '.pysas-ui/artifacts' / old_id, app.storage / 'artifacts' / ids[old_id])):
                if src.exists(): moves.append((src, dest))
        folders = remap(manifest.get('folders', {}))
        defaults = {'inputs': str(app.root), 'init': str(app.root), 'inbox': str(app.root / 'runner/inbox')}
        missing = []
        for key in defaults:
            if not Path(folders.get(key, '')).is_dir() or not folders.get(key):
                missing.append(key)
                folders[key] = defaults[key]
        settings = {'folders.json': folders, 'bundle-paths.json': remap(manifest.get('bundle_settings', {}))}
        previous = {name: (app.storage / name).read_bytes() if (app.storage / name).exists() else None for name in settings}
        completed = []
        try:
            for source, destination in moves:
                if not destination.resolve().is_relative_to(app.root):
                    raise ValueError('Destination contains a link outside the workspace.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                completed.append(destination)
            for item in commands:
                destination = app.storage / (item['id'] + '.json')
                completed.append(destination)
                app.save(item)
            for name, value in settings.items():
                (app.storage / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        except BaseException:
            for p in reversed(completed):
                if p.is_dir(): shutil.rmtree(p)
                else: p.unlink(missing_ok=True)
            for name, content in previous.items():
                p = app.storage / name
                if content is None: p.unlink(missing_ok=True)
                else: p.write_bytes(content)
            raise
        app.commands.update({c['id']: c for c in commands})
        app.invalidate_lists()
        return {'runs': len(mappings), 'commands': len(commands), 'missing_folders': missing}


def signature(task):
    name = portable(task.get('program') or task.get('name', '')).split('/')[-1].casefold()
    return (name, str(task.get('section') or '').strip().casefold(), int(task.get('row_start') or 0), int(task.get('row_end') or 0))


def duration_history(root, commands):
    """One sample per saved task; merge UI scope with older workbook snapshots."""
    from pysas import load_schedule
    samples = {}
    def add(task, identity, stamp):
        try:
            seconds = float(task.get('elapsed'))
            if task.get('status') != 'SUCCESS' or not math.isfinite(seconds) or seconds <= 0: return
            key = signature(task)
            samples[identity] = {'key': key, 'seconds': seconds, 'time': stamp}
        except (ValueError, TypeError): pass
    for command in commands:
        for task in command.get('tasks', {}).values():
            if task.get('path'):
                add(task, portable(task['path']), command.get('started', 0))
    for base, kind in ((root / 'runs', 'schedule'), (root / 'runner/runs', 'file')):
        if not base.exists(): continue
        for folder in base.iterdir():
            if not folder.is_dir() or folder.is_symlink(): continue
            try:
                stamp = folder.stat().st_mtime
                if kind == 'file':
                    status = dict(line.split('=', 1) for line in (folder / 'status.txt').read_text(encoding='utf-8').splitlines() if '=' in line)
                    elapsed = status.get('elapsed_seconds')
                    if elapsed is None and status.get('started') and status.get('finished'):
                        elapsed = (datetime.fromisoformat(status['finished']) - datetime.fromisoformat(status['started'])).total_seconds()
                    if status.get('started'): stamp = datetime.fromisoformat(status['started']).timestamp()
                    identity = folder.relative_to(root).as_posix()
                    if identity not in samples:
                        add(dict(name=status.get('source'), status=status.get('status'), elapsed=elapsed), identity, stamp)
                else:
                    with (folder / 'run_summary.csv').open(encoding='utf-8-sig', newline='') as f: rows = list(csv.DictReader(f))
                    stamp = (folder / 'run_summary.csv').stat().st_mtime
                    scopes = {}
                    for workbook in folder.glob('*.xlsx'):
                        if workbook.name == 'run_summary.xlsx': continue
                        try:
                            scopes = {t['task_id']: t for t in load_schedule(workbook)}
                            break
                        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile): continue
                    from pysas import safe_name
                    for row in rows:
                        if 'duration_hours' in row:
                            # Original 0.3.2 CSV splits elapsed time into h/m/s.
                            row['elapsed'] = sum(float(row.get(k) or 0) * multiplier for k, multiplier in (('duration_hours', 3600), ('duration_minutes', 60), ('duration_seconds', 1)))
                            row['row_start'], row['row_end'] = row.get('start'), row.get('end')
                        identity = (folder / 'tasks' / safe_name(row['task_id'])).relative_to(root).as_posix()
                        if identity not in samples and (row['task_id'] in scopes or 'row_start' in row):
                            add({**scopes.get(row['task_id'], {}), **row}, identity, stamp)
            except (OSError, ValueError, KeyError): continue
    return list(samples.values())


def index_samples(samples):
    if isinstance(samples, dict): return samples
    index = {}
    for sample in samples:
        index.setdefault(tuple(sample['key']), []).append(sample)
    return {key: sorted(values, key=lambda s: s['time'], reverse=True)[:10] for key, values in index.items()}


def estimate_task(task, samples):
    try:
        key = signature(task)
    except (ValueError, TypeError):
        key = None
    matches = index_samples(samples).get(key, [])
    return {'seconds': statistics.median(s['seconds'] for s in matches) if matches else None,
            'samples': len(matches), 'basis': 'Same program name and section/rows; recent successful runs. Code, data volume and server load may differ.'}


def estimate_schedule(tasks, workers, samples):
    samples = index_samples(samples)
    definitions = {str(t.get('task_id') or t.get('key')).casefold(): 0 for t in tasks if t.get('always_run') or t.get('status') == 'ALWAYS_RUN_DEFINITION'}
    tasks = [dict(t) for t in tasks if not t.get('always_run') and t.get('status') != 'ALWAYS_RUN_DEFINITION']
    for t in tasks:
        t['estimate'] = {'seconds': 0, 'samples': 0} if t.get('skip') or t.get('status') in {'SKIPPED_SUCCESS', 'SKIPPED_PREVIOUS'} else estimate_task(t, samples)
    pending = {str(t.get('task_id') or t.get('key')).casefold(): t for t in tasks}
    ends, heap, now = dict(definitions), [], 0.0
    workers = max(1, min(32, int(workers)))
    unknown = sum(t['estimate']['seconds'] is None for t in tasks)
    work = sum(t['estimate']['seconds'] or 0 for t in tasks)
    critical = dict(definitions)
    while pending or heap:
        ready = [k for k, t in pending.items() if all(str(d).casefold() in ends for d in t.get('depends_on', []))]
        for key in ready[:max(0, workers - len(heap))]:
            t = pending.pop(key)
            seconds = t['estimate']['seconds'] or 0
            critical[key] = seconds + max((critical.get(str(d).casefold(), 0) for d in t.get('depends_on', [])), default=0)
            heapq.heappush(heap, (now + seconds, key))
        if not heap:
            if pending: return {'seconds': None, 'unknown': len(pending), 'tasks': tasks}
            break
        now, key = heapq.heappop(heap)
        ends[key] = now
        while heap and heap[0][0] == now:
            _, key = heapq.heappop(heap)
            ends[key] = now
    known = any(t['estimate']['samples'] for t in tasks)
    return {'seconds': (max(work / workers, max(critical.values(), default=0)) if unknown else now) if known or not unknown else None,
            'unknown': unknown, 'tasks': tasks, 'workers': workers}

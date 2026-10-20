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
import ui_parameters

LIMIT = 10 * 1024**3
FORMAT = 'pysas-workbench-backup-1'

def portable(value):
    return str(value).replace('\\', '/').rstrip('/')


def safe_files(folder):
    if folder.is_symlink():
        return
    for base, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".schedule-locks" and not (Path(base) / d).is_symlink())
        for name in sorted(names):
            p = Path(base) / name
            if not p.is_symlink() and p.is_file():
                yield p


def archive_folder(root, relative, tasks=None):
    from ui_storage import run_folder
    folder = (root / relative).resolve()
    owned = run_folder(root, folder, tasks)
    if not owned or not folder.is_relative_to(owned) or not folder.is_dir():
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


def write_archive(out, entries, progress=None, manifest=None):
    """Preflight limits and report bytes while compressing, without buffering the ZIP in RAM."""
    entries = [(p, name, p.stat().st_size) for p, name in entries]
    total = sum(size for _, _, size in entries)
    if total > LIMIT or len(entries) > 199999:
        raise ValueError('Saved data exceeds the 10 GB / 200,000 file backup limit. Download individual run folders instead.')
    done = 0
    if progress: progress(done, total, 'Compressing files')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        if manifest is not None:
            raw = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
            if len(raw) > 32 * 1024**2: raise ValueError('Backup command history exceeds 32 MB.')
            if total + len(raw) > LIMIT: raise ValueError('Saved data including its manifest exceeds the 10 GB backup limit.')
            z.writestr('manifest.json', raw)
        for p, name, size in entries:
            info = zipfile.ZipInfo.from_file(p, name, strict_timestamps=False)
            info.compress_type = zipfile.ZIP_DEFLATED
            with p.open('rb') as source, z.open(info, 'w', force_zip64=True) as target:
                remaining = size
                while remaining:
                    chunk = source.read(min(1024*1024, remaining))
                    if not chunk: raise ValueError('A saved file changed while exporting. Please retry after it finishes.')
                    target.write(chunk); remaining -= len(chunk); done += len(chunk)
                    if progress: progress(done, total, 'Compressing ' + name)
    out.seek(0)


def backup_manifest(app, configs_only=False):
    return json.loads(json.dumps(dict(format=FORMAT, scope='configs' if configs_only else 'all', workspace=str(app.root), folders=app.folders(),
                        bundle_settings=app.bundle_settings(), commands=[] if configs_only else list(app.commands.values()),
                        parameters_settings=ui_parameters.settings(app.settings), shared_work=app.shared_work(), preferences=app.preferences())))


def export_backup(app, configs_only=False, progress=None, destination=None, *, manifest=None, before=None):
    out = open(destination, 'w+b') if destination else tempfile.TemporaryFile()
    try:
        if progress: progress(0, 0, 'Scanning saved files')
        manifest = manifest if manifest is not None else backup_manifest(app, configs_only)
        bases = [app.settings / 'parameters', app.settings / 'graphs']
        if not configs_only:
            for parent in (*[base for base,_ in app.run_bases()], app.storage / 'artifacts'):
                if parent.is_dir():
                    for child in parent.iterdir():
                        if not child.is_symlink() and portable(app.relative(child)) not in app.legacy_moves and (before is None or getattr(child.stat(), 'st_birthtime', child.stat().st_ctime) <= before):
                            bases.append(child)
        entries = [(p, ('.pysas-ui/parameters/'+p.name if p.parent==app.settings/'parameters' else '.pysas-ui/graphs/'+p.name if p.parent==app.settings/'graphs' else portable(app.relative(p)))) for base in bases for p in safe_files(base) if p.name not in {'.schedule.lock', '_cancel.request'}]
        if not configs_only:
            sources = app.tasks / 'graph-sources'
            if sources.is_dir() and not sources.is_symlink():
                entries.extend((p, portable(app.relative(p))) for p in sources.iterdir()
                               if p.is_file() and not p.is_symlink() and p.suffix.lower() in {'.sas', '.egp'}
                               and (before is None or getattr(p.stat(), 'st_birthtime', p.stat().st_ctime) <= before))
            for command in manifest["commands"]:
                identifier = command["id"]
                p = app.storage / (identifier + '.txt')
                if p.is_file() and not p.is_symlink(): entries.append((p, ('.pysas-ui/parameters/'+p.name if p.parent==app.settings/'parameters' else '.pysas-ui/graphs/'+p.name if p.parent==app.settings/'graphs' else portable(app.relative(p)))))
        write_archive(out, entries, progress, manifest)
        return out, 'PySAS-configs.zip' if configs_only else 'PySAS-saved-data.zip'
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
                if (not parts or name.startswith('/') or '\\' in i.orig_filename or '\x00' in i.orig_filename or ':' in name or any(p in {'.', '..'} or p.endswith((' ', '.')) for p in parts)
                    or any(re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', p) for p in parts)
                    or name.casefold() in seen or (i.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('Backup contains an unsafe or duplicate path.')
                seen.add(name.casefold())
                allowed = (len(parts) >= 4 and parts[:2] in {('tasks','files'),('tasks','schedules')}) or name == 'manifest.json' or (len(parts) >= 3 and parts[0] == 'runs') or (len(parts) >= 4 and parts[:2] == ('runner', 'runs')) or (len(parts) >= 4 and parts[:2] == ('.pysas-ui', 'artifacts')) or (len(parts) == 2 and parts[0] == '.pysas-ui' and re.fullmatch(r'[a-zA-Z0-9_-]+\.txt', parts[1]))
                if len(parts)==3 and parts[:2]==('.pysas-ui','graphs'):
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}\.json',parts[2]) or i.file_size>2*1024**2: raise ValueError('Invalid graph backup entry.')
                    allowed=True
                if len(parts)==3 and parts[:2]==('tasks','graph-sources'):
                    if PurePosixPath(parts[2]).suffix.lower() not in {'.sas','.egp'} or i.file_size>512*1024**2: raise ValueError('Invalid graph source backup entry.')
                    allowed=True
                if len(parts) == 3 and parts[:2] == ('.pysas-ui', 'parameters'):
                    ui_parameters.parameter_name(parts[2])
                    if i.file_size > ui_parameters.PARAMETER_LIMIT:
                        raise ValueError('Saved parameter file exceeds 128 KB.')
                    allowed = True
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
        for prefix in ('runs', 'runner/runs', 'tasks/files', 'tasks/schedules'):
            base = unpacked / prefix
            if base.exists():
                for folder in base.iterdir():
                    destination = app.tasks / ('schedules' if prefix in {'runs','tasks/schedules'} else 'files') / folder.name
                    if destination.exists():
                        destination = destination.with_name(folder.name + '_import_' + uuid.uuid4().hex[:8])
                    mappings[prefix + '/' + folder.name] = portable(app.relative(destination))
                    moves.append((folder, destination))
        parameter_settings = manifest.get('parameters_settings')
        parameter_moves = {}
        if parameter_settings is not None:
            if not isinstance(parameter_settings, dict) or not isinstance(parameter_settings.get('enabled'), bool):
                raise ValueError('Backup parameter settings are invalid.')
            if parameter_settings.get('last'):
                ui_parameters.parameter_name(parameter_settings['last'])
        parameter_folder = unpacked / '.pysas-ui/parameters'
        if parameter_folder.exists():
            for file in parameter_folder.iterdir():
                ui_parameters.parameter_text(file.read_text(encoding='utf-8'))
                destination = ui_parameters.parameter_path(app.settings, file.name)
                if destination.exists():
                    if destination.read_bytes() == file.read_bytes():
                        parameter_moves[file.name] = file.name
                        continue
                    # Keep both versions of a saved list rather than replace either.
                    destination = destination.with_name(file.stem[:65] + '_import_' + uuid.uuid4().hex[:8] + '.sas')
                parameter_moves[file.name] = destination.name
                moves.append((file, destination))
        if parameter_settings is not None:
            parameter_settings = dict(parameter_settings)
            parameter_settings['last'] = parameter_moves.get(parameter_settings.get('last'), '')
            if not parameter_settings['last']: parameter_settings['enabled'] = False
        graph_sources=unpacked/'tasks/graph-sources'
        if graph_sources.exists():
            for source in graph_sources.iterdir():
                target=app.tasks/'graph-sources'/source.name
                if target.exists():target=target.with_name(source.stem+'_import_'+uuid.uuid4().hex[:8]+source.suffix)
                mappings['tasks/graph-sources/'+source.name]=portable(app.relative(target));moves.append((source,target))
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
            mappings['.pysas-ui/artifacts/' + identifier] = '.pysas-ui/artifacts/' + ids[identifier]
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
            return str(app.resolve(rel)) if absolute else rel if rel != normalized or '\\' in value else value
        graph_ids={}
        graph_folder=unpacked/'.pysas-ui/graphs'
        if graph_folder.exists():
            from pysas import validate_graph
            for source in graph_folder.iterdir():
                graph=validate_graph(json.loads(source.read_text(encoding='utf-8')))
                if graph.get('id') and graph['id']!=source.stem:raise ValueError('Graph ID does not match its backup filename.')
                target=app.settings/'graphs'/source.name
                if target.exists():target=target.with_name(uuid.uuid4().hex+'.json')
                graph_ids[source.stem]=target.stem
                graph=remap(graph);graph['id']=target.stem
                source.write_text(json.dumps(graph,ensure_ascii=False),encoding='utf-8');moves.append((source,target))
        commands = []
        for original in manifest['commands']:
            item = remap(original)
            old_id = original['id']
            item['id'] = ids[old_id]
            if item.get('graph_id') in graph_ids:item['graph_id']=graph_ids[item['graph_id']]
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
        if parameter_settings is not None:
            settings['parameters-settings.json'] = parameter_settings
        if 'shared_work' in manifest:
            from pysas import shared_work_settings
            shared = shared_work_settings(manifest['shared_work'])
            shared['enabled'] = False  # A restored WORK path may belong to an expired session.
            settings['shared-work.json'] = shared
        preferences = remap(manifest.get('preferences', {}))
        if not isinstance(preferences, dict): raise ValueError('Invalid preferences in backup.')
        clean = {key: '' for key in ('default_egp', 'default_lib')}
        for key in clean:
            value = preferences.get(key, '')
            if isinstance(value, str) and value:
                path = Path(value)
                roots = [app.root, *(Path(v) for v in folders.values())]
                if path.is_file() and any(path.resolve().is_relative_to(root.resolve()) for root in roots):
                    clean[key] = value
        watcher = preferences.get('watcher', {})
        if not isinstance(watcher, dict): raise ValueError('Invalid watcher preferences.')
        clean['watcher'] = dict(workers=max(1, min(32, int(watcher.get('workers') or 2))),
                                poll=max(.5, min(60, float(watcher.get('poll') or 2))),
                                auto_start=False, tables=watcher.get('tables') is True)
        for key in ('template', 'lib'):
            value = watcher.get(key, '')
            if isinstance(value, str) and value and Path(value).is_file() and any(Path(value).resolve().is_relative_to(Path(v).resolve()) for v in [str(app.root), *folders.values()]):
                clean['watcher'][key] = value
        settings['preferences.json'] = clean
        previous = {name: (app.config(name)).read_bytes() if (app.config(name)).exists() else None for name in settings}
        completed = []
        try:
            for source, destination in moves:
                if not any(destination.resolve().is_relative_to(base) for base in (app.root,app.tasks,app.settings)):
                    raise ValueError('Destination contains a link outside the workspace.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                completed.append(destination)
                shutil.move(str(source), str(destination))
            for item in commands:
                destination = app.storage / (item['id'] + '.json')
                completed.append(destination)
                app.save(item)
            for name, value in settings.items():
                (app.config(name)).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        except BaseException:
            for p in reversed(completed):
                if p.is_dir(): shutil.rmtree(p)
                else: p.unlink(missing_ok=True)
            for name, content in previous.items():
                p = app.config(name)
                if content is None: p.unlink(missing_ok=True)
                else: p.write_bytes(content)
            raise
        app.commands.update({c['id']: c for c in commands})
        app.invalidate_lists()
        return {'runs': sum(p.startswith(('runs/', 'runner/runs/', 'tasks/files/', 'tasks/schedules/')) for p in mappings),
                'commands': len(commands), 'parameters': len(parameter_moves), 'graphs': len(graph_ids), 'missing_folders': missing}


def signature(task):
    name = portable(task.get('program') or task.get('name', '')).split('/')[-1].casefold()
    return (name, str(task.get('section') or '').strip().casefold(), int(task.get('row_start') or 0), int(task.get('row_end') or 0))


def duration_history(root, commands, bases=None, resolve=None):
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
                add(task, portable(str(resolve(task['path']) if resolve else (root/portable(task['path'])).resolve())), command.get('started', 0))
    for base, kind in (bases or ((root / 'runs', 'schedule'), (root / 'runner/runs', 'file'))):
        if not base.exists(): continue
        for folder in base.iterdir():
            if not folder.is_dir() or folder.is_symlink(): continue
            if resolve and resolve(str(folder)) != folder.resolve(): continue
            try:
                stamp = folder.stat().st_mtime
                if kind == 'file':
                    status = dict(line.split('=', 1) for line in (folder / 'status.txt').read_text(encoding='utf-8').splitlines() if '=' in line)
                    elapsed = status.get('elapsed_seconds')
                    if elapsed is None and status.get('started') and status.get('finished'):
                        elapsed = (datetime.fromisoformat(status['finished']) - datetime.fromisoformat(status['started'])).total_seconds()
                    if status.get('started'): stamp = datetime.fromisoformat(status['started']).timestamp()
                    identity = portable(str(folder.resolve()))
                    if identity not in samples:
                        add(dict(name=status.get('source'), status=status.get('status'), elapsed=elapsed), identity, stamp)
                else:
                    with (folder / 'run_summary.csv').open(encoding='utf-8-sig', newline='') as f: rows = list(csv.DictReader(f))
                    stamp = (folder / 'run_summary.csv').stat().st_mtime
                    scopes = {}
                    if (folder / 'graph.json').is_file():
                        from pysas import load_graph
                        graph = load_graph(folder / 'graph.json')
                        scopes = {n['id']: dict(program=n['name'], section=n['section'], row_start=n['row_start'], row_end=n['row_end'])
                                  for n in graph['setup'] + graph['nodes']}
                    for workbook in folder.glob('*.xlsx'):
                        if scopes: break
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
                        identity = portable(str((folder / 'tasks' / safe_name(row['task_id'])).resolve()))
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


def remaining_work(commands, queued, samples, now):
    """Forecast current workloads, with running tasks occupying their worker slots."""
    forecasts = []
    for command in commands:
        if command.get('status') not in {'RUNNING', 'STOPPING'}: continue
        if command.get('action') not in {'run', 'watch', 'schedule', 'continue', 'server-refresh'}: continue
        args = command.get('args', [])
        workers = int(args[args.index('--workers')+1]) if '--workers' in args else 1
        tasks = [dict(t) for t in command.get('tasks', {}).values()]
        if command.get('action') == 'watch' and command['status'] == 'RUNNING':
            current = {t.get('name') for t in tasks if t.get('status') in {'RUNNING', 'CANCELLING'}}
            tasks += [dict(key='queue:'+name, name=name, status='PENDING') for name in queued if name not in current]
        if command.get('action') == 'watch' and not any(t.get('status') in {'RUNNING', 'CANCELLING', 'PENDING'} for t in tasks): continue
        ends, pending, heap = set(), {}, []
        unknown = known = 0
        for index, task in enumerate(tasks):
            key = str(task.get('key') or task.get('task_id') or index).casefold()
            status = task.get('status')
            if status in {'SUCCESS', 'SKIPPED_SUCCESS', 'SKIPPED_PREVIOUS', 'ALWAYS_RUN_DEFINITION'}:
                ends.add(key); continue
            if status not in {'RUNNING', 'CANCELLING', 'PENDING'}: continue
            if command['status'] == 'STOPPING' and status == 'PENDING': continue
            seconds = 0 if task.get('skip') else estimate_task(task, samples)['seconds']
            running = status in {'RUNNING', 'CANCELLING'}
            if seconds is not None and running:
                seconds -= max(0, now - (task.get('started') or now))
                if seconds <= 0: seconds = None  # Do not announce zero while SAS still runs.
            unknown += seconds is None
            known += seconds is not None and not task.get('skip')
            if running: heapq.heappush(heap, (max(0, seconds or 0), key))
            else: pending[key] = (task, seconds or 0)
        elapsed = 0
        while pending or heap:
            for key, (task, seconds) in list(pending.items()):
                if len(heap) >= workers: break
                if all(str(dep).casefold() in ends for dep in task.get('depends_on', [])):
                    del pending[key]
                    heapq.heappush(heap, (elapsed + seconds, key))
            if not heap:
                unknown += len(pending); break
            elapsed, key = heapq.heappop(heap); ends.add(key)
            while heap and heap[0][0] == elapsed:
                _, key = heapq.heappop(heap); ends.add(key)
        if not tasks and command['status'] == 'RUNNING' and command.get('action') != 'watch': unknown += 1
        forecasts.append(dict(seconds=elapsed, unknown=unknown, known=known))
    unknown = sum(f['unknown'] for f in forecasts)
    return dict(seconds=max((f['seconds'] for f in forecasts), default=0) if not unknown or any(f['known'] for f in forecasts) else None,
                unknown=unknown, active=bool(forecasts), observed=now)

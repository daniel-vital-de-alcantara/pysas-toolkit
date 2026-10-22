"""Bounded background EGP inspection/extraction for the Run stream editor."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import threading
import time
import uuid
import zipfile

import egp_extract
import ui_stream


class Jobs:
    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.jobs = {}
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='stream-source')

    def working(self):
        with self.lock: return any(j['status'] == 'WORKING' for j in self.jobs.values())

    def close(self): self.pool.shutdown(wait=True, cancel_futures=True)

    def get(self, identifier):
        with self.lock:
            if identifier not in self.jobs: raise ValueError('This source-loading job is no longer available. Try again.')
            return dict(self.jobs[identifier])

    def start(self, data):
        kind = data.get('kind')
        if kind not in {'connection', 'project', 'program'}: raise ValueError('Unknown stream preparation job.')
        # Parse/normalize before queuing; never retain arbitrary request bodies.
        request = dict(kind=kind)
        if kind == 'connection': request['path'] = str(data.get('path') or '')
        else:
            request['project'] = ui_stream.file_ref(data.get('project'), '.egp')
            if not request['project']: raise ValueError('Choose an EGP first.')
            if kind == 'program':
                value = data.get('program_id')
                if not isinstance(value, str) or not 0 < len(value) <= 4096: raise ValueError('Choose an EGP program.')
                request['program_id'] = value
        with self.app.lock:
            if getattr(self.app, 'closing', False): raise ValueError('PySAS is closing.')
            if self.app.storage_busy: raise ValueError('Wait for the saved-data operation to finish.')
        with self.lock:
            if sum(j['status'] == 'WORKING' for j in self.jobs.values()) >= 64:
                raise ValueError('Many sources are loading. Wait for one to finish, then retry.')
            for key, job in list(self.jobs.items()):
                if len(self.jobs) < 100: break
                if job['status'] != 'WORKING': self.jobs.pop(key)
            identifier = uuid.uuid4().hex
            self.jobs[identifier] = dict(id=identifier, kind=kind, status='WORKING', message='Reading project…', started=time.time())
        self.pool.submit(self._work, identifier, request)
        return self.get(identifier)

    def _work(self, identifier, request):
        try:
            if request['kind'] == 'connection': result = self.connection(request['path'])
            elif request['kind'] == 'project':
                ref = request['project']; raw = ui_stream.read_asset(self.app, ref, '.egp')
                result = dict(project=ref, catalog=egp_extract.inspect_project(io.BytesIO(raw)))
            else:
                ref = request['project']; raw = ui_stream.read_asset(self.app, ref, '.egp')
                program, source = egp_extract.read_program(io.BytesIO(raw), request['program_id'], limit=ui_stream.SOURCE_LIMIT)
                # Decode/scan before publishing a source snapshot; no main status lock during IO.
                analysis = ui_stream.scan_source(ui_stream._decode(source))
                with self.app.upload_lock:
                    with self.app.lock:
                        if self.app.storage_busy: raise ValueError('Wait for the saved-data operation to finish, then retry extraction.')
                        self.app.uploading = True
                    try:
                        folder = self.app.tasks / 'stream-sources'; folder.mkdir(exist_ok=True)
                        target = folder / (uuid.uuid4().hex + '.sas')
                        target.write_bytes(source)
                    finally: self.app.uploading = False
                import hashlib
                name = egp_extract.egp_component(program['name'], 'Program', 180)
                if not name.lower().endswith('.sas'): name += '.sas'
                result = dict(program=program, file=dict(path=self.app.relative(target), name=name,
                              sha256=hashlib.sha256(source).hexdigest(), **analysis))
            with self.lock:
                self.jobs[identifier].update(status='READY', result=result, message='Ready', finished=time.time())
        except Exception as exc:
            with self.lock:
                self.jobs[identifier].update(status='FAILED', error=str(exc), message=str(exc), finished=time.time())

    def connection(self, selected=''):
        app, seen, warnings = self.app, set(), []
        def candidates():
            if selected:
                yield selected, None
                return
            preferred = app.preferences().get('default_egp')
            if preferred: yield preferred, None
            with app.lock: commands = sorted(app.commands.values(), key=lambda c:c.get('started', 0), reverse=True)
            for command in commands:
                if command.get('status') not in {'SUCCESS', 'PARTIAL'}: continue
                if command.get('action') == 'stream' and command.get('path'):
                    try:
                        folder = app.resolve(command['path'])
                        saved = json.loads((folder / 'stream-plan.json').read_text(encoding='utf-8'))['document']['egp']
                        yield folder / saved['path'], saved['name']
                    except (OSError, ValueError, KeyError, TypeError): pass
                for flag in ('--template', '--project'):
                    args = command.get('args', [])
                    if flag in args and args.index(flag) + 1 < len(args): yield args[args.index(flag) + 1], None
            # Discovery is deliberately lazy: a valid saved/recent connection does
            # not wait for input-folder scanning (which can include network disks).
            for path in app.inventory():
                if path.lower().endswith('.egp'): yield path, None
            for name in ('stream-sources', 'graph-sources'):
                folder = app.tasks / name
                if not folder.is_dir(): continue
                paths = []
                for path in folder.iterdir():
                    try:
                        if path.suffix.lower() == '.egp': paths.append((path.stat().st_mtime, path))
                    except OSError: continue
                for _, path in sorted(paths, reverse=True): yield path, None
        for value, name in candidates():
            try:
                path = app.input_path(str(value))
                if path.suffix.lower() != '.egp' or not path.is_file() or str(path) in seen: continue
                seen.add(str(path))
                ref = ui_stream.describe(app, path, name)
                raw = ui_stream.read_asset(app, ref, '.egp')
                catalog = egp_extract.inspect_project(io.BytesIO(raw))
                if not catalog['connection_valid']: raise ValueError('No project code node was found to inherit a SAS connection.')
                return dict(egp=ref, catalog=catalog, automatic=not bool(selected), warnings=warnings)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                warnings.append(str(value) + ': ' + str(exc))
                if selected: raise ValueError('Cannot use this connection EGP: ' + str(exc)) from exc
        if selected: raise ValueError('Choose an existing connection EGP.')
        return dict(egp=None, catalog=None, automatic=True, warnings=warnings)

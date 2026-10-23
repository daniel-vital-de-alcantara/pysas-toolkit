"""Editable stream-task graphs. This module never submits or schedules SAS."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import uuid

import egp_extract
import ui_graph
import ui_stream

FORMAT = 'pysas-task-graph-1'
STORED_LIMIT = 20 * 1024**2


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('Graph and task IDs must be unique letters, digits, underscores or hyphens.')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid canvas position or zoom.')
    return value


def validate(value):
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        raise ValueError('Choose a PySAS task graph JSON.')
    # The future execution unit is a Run stream document, rather than a legacy
    # scheduler row. Use the same source/selection schema without running it.
    defaults = ui_stream.validate(dict(value, format=ui_stream.FORMAT, rows=[]))
    workers = value.get('workers', 10)
    if type(workers) is not int or not 1 <= workers <= 32: raise ValueError('Choose 1 to 32 parallel tasks.')
    view = value.get('viewport', {})
    if not isinstance(view, dict): raise ValueError('Invalid graph viewport.')
    result = dict(format=FORMAT, id=identifier(value.get('id')), name=defaults['name'], workers=workers,
                  egp=defaults['egp'], connection_mode=defaults['connection_mode'], server_program=defaults['server_program'],
                  shared_work=defaults['shared_work'], viewport=dict(x=number(view.get('x', 50), -100000, 100000),
                  y=number(view.get('y', 210), -100000, 100000), zoom=number(view.get('zoom', 1), .25, 2)),
                  setup=[], nodes=[], edges=[])
    ids, source_ids, total_rows, total_inline = set(), set(), 0, 0
    for key, limit in (('setup', 100), ('nodes', 200)):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > limit: raise ValueError(f'Use at most {limit} {key} cards.')
        for node in items:
            if not isinstance(node, dict): raise ValueError('Invalid task card.')
            key_id = identifier(node.get('id'))
            if key_id.casefold() in ids: raise ValueError('Task IDs must be unique across tasks and shared setup.')
            ids.add(key_id.casefold())
            stream = ui_stream.validate(dict(node, format=ui_stream.FORMAT, egp=None, shared_work={}))
            for row in stream['rows']:
                original = next(r for r in node['rows'] if r['id'] == row['id'])
                if original.get('legacy_source'):
                    legacy = original['legacy_source']
                    if not isinstance(legacy, str) or len(legacy) > 4096: raise ValueError('Invalid previous source path.')
                    row['legacy_source'] = legacy
                units = row['programs'] if row['source_kind'] == 'egp' else [row]
                total_rows += len(units)
                if row['source_kind'] == 'inline': total_inline += len(row['code'].encode('utf-8'))
                for unit in [row, *row['programs']]:
                    if unit['id'] in source_ids: raise ValueError('Source card and program IDs must be unique across the graph.')
                    source_ids.add(unit['id'])
            result[key].append(dict(id=key_id, name=stream['name'], rows=stream['rows'],
                x=number(node.get('x', 0), -20000, 20000), y=number(node.get('y', 0), -20000, 20000),
                export_html=stream['export_html'], export_tables=stream['export_tables'], consolidate_tables=stream['consolidate_tables']))
    if total_rows > 1000 or total_inline > ui_stream.SOURCE_LIMIT: raise ValueError('A graph supports 1,000 source programs and 16 MB of inline code in total.')
    edges = value.get('edges', [])
    if not isinstance(edges, list) or len(edges) > 2000: raise ValueError('Use at most 2,000 dependencies.')
    tasks, pairs = {n['id'] for n in result['nodes']}, set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in tasks or edge.get('to') not in tasks or edge['from'] == edge['to']:
            raise ValueError('Dependencies must connect different task cards. Shared setup applies to every task without arrows.')
        pair = (edge['from'], edge['to'])
        if pair in pairs: raise ValueError('This dependency already exists.')
        pairs.add(pair); result['edges'].append(dict(zip(('from', 'to'), pair)))
    remaining = set(tasks)
    while remaining:
        ready = {task for task in remaining if not any(e['to'] == task and e['from'] in remaining for e in result['edges'])}
        if not ready: raise ValueError('Circular dependency detected. Remove a link.')
        remaining -= ready
    return result


def all_rows(graph):
    return [row for node in graph['setup'] + graph['nodes'] for row in node['rows']]


def stream_document(graph):
    return dict(graph, format=ui_stream.FORMAT, rows=all_rows(graph))


def hydrate(app, graph):
    for ref, suffix in ui_stream.asset_refs(stream_document(graph)):
        try:
            raw = ui_stream.read_asset(app, ref, suffix)
            if suffix == '.sas': ref.update(ui_stream.scan_source(ui_stream._decode(raw)))
        except (OSError, ValueError) as exc: ref['source_error'] = str(exc)
    for row in all_rows(graph):
        if row['source_kind'] == 'inline': row['analysis'] = ui_stream.scan_source(row['code'])
    return graph


def validate_saved(value):
    if isinstance(value, dict) and value.get('format') == FORMAT: return validate(value)
    from pysas import validate_graph
    return validate_graph(value)


def migrate(app, value):
    from pysas import validate_graph
    old = validate_graph(value)
    graph = dict(format=FORMAT, id=uuid.uuid4().hex, name=old['name'], workers=old['workers'], setup=[], nodes=[], edges=old['edges'])
    if old.get('connection'):
        try: graph['egp'] = ui_stream.describe(app, old['connection'])
        except (OSError, ValueError): pass
    for kind in ('setup', 'nodes'):
        for item in old[kind]:
            source = item['source']; source_id = 's_' + uuid.uuid4().hex
            row = dict(id=source_id, source_kind='file', file=None, mode='section' if item['section'] else 'lines' if item['row_start'] or item['row_end'] else 'whole',
                       section=item['section'], row_start=item['row_start'], row_end=item['row_end'], legacy_source=source['path'])
            try:
                ref = ui_stream.describe(app, source['path'])
                if source['type'] == 'file': row['file'] = ref
                else:
                    program, raw = egp_extract.read_program(io.BytesIO(ui_stream.read_asset(app, ref, '.egp')), source['program_id'], limit=ui_stream.SOURCE_LIMIT)
                    with app.upload_lock:
                        with app.lock:
                            if app.storage_busy: raise ValueError('Wait for the saved-data operation to finish.')
                            app.uploading = True
                        try:
                            folder = app.tasks / 'stream-sources'; folder.mkdir(exist_ok=True)
                            target = folder / (uuid.uuid4().hex + '.sas'); target.write_bytes(raw)
                            name = egp_extract.egp_component(program['name'], limit=175)
                            selected = ui_stream.describe(app, target, name if name.lower().endswith('.sas') else name + '.sas')
                        finally: app.uploading = False
                    row.update(source_kind='egp', project=ref, programs=[dict(row, id='p_' + uuid.uuid4().hex, program_id=source['program_id'], name=program['name'], flow=program['flow'], file=selected)])
            except (OSError, ValueError): pass
            graph[kind].append(dict(id=item['id'], name=item['name'], x=item['x'], y=item['y'], rows=[row], export_tables=item['tables']))
    return hydrate(app, validate(graph))


def load(app, key):
    path = ui_graph.graph_path(app, key); raw = path.read_bytes()
    if len(raw) > STORED_LIMIT: raise ValueError('Saved graph exceeds 20 MB.')
    value = json.loads(raw.decode('utf-8-sig'))
    if value.get('format') == 'pysas-graph-1':
        return dict(graph=migrate(app, value), revision=None, path='', legacy=True)
    return dict(graph=hydrate(app, validate(value)), revision=hashlib.sha256(raw).hexdigest(), path=app.relative(path))


def listing(app):
    folder = app.settings / 'graphs'
    if not folder.is_dir(): return []
    items = []
    for path in folder.glob('*.json'):
        try:
            if path.is_symlink() or path.stat().st_size > STORED_LIMIT: continue
            graph = validate_saved(json.loads(path.read_text(encoding='utf-8-sig')))
            items.append(dict(id=path.stem, name=graph['name'], nodes=len(graph['nodes']), legacy=graph['format'] != FORMAT, updated=path.stat().st_mtime))
        except (OSError, ValueError, TypeError): continue
    return sorted(items, key=lambda i:i['updated'], reverse=True)[:500]


def save(app, data):
    graph = validate(data.get('graph')); raw = json.dumps(graph, ensure_ascii=False, indent=2).encode('utf-8')
    if len(raw) > STORED_LIMIT: raise ValueError('Saved graph exceeds 20 MB.')
    path = ui_graph.graph_path(app, graph['id'])
    with app.lock:
        if app.storage_busy: raise ValueError('Wait for the saved-data operation to finish.')
        if path.exists() and data.get('revision') != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('This graph changed in another window. Reload it before saving.')
        from pysas_ui import atomic_json
        atomic_json(path, graph)
    return dict(graph=graph, revision=hashlib.sha256(path.read_bytes()).hexdigest(), path=app.relative(path))


def export(app, value):
    graph = validate(value)
    raw = json.dumps(ui_stream.portable(graph, ui_stream.assets(app, stream_document(graph))), ensure_ascii=False, indent=2).encode('utf-8')
    if len(raw) > ui_stream.JSON_LIMIT: raise ValueError('Portable graph JSON exceeds 128 MB.')
    with app.upload_lock:
        with app.lock:
            if app.storage_busy: raise ValueError('Wait for the saved-data operation to finish.')
            app.uploading = True
        try:
            folder = app.storage / 'artifacts' / uuid.uuid4().hex; folder.mkdir(parents=True)
            name = re.sub(r'[^a-zA-Z0-9_-]', '_', graph['name'])[:80] or 'graph'
            target = folder / (name + '.graph.json'); target.write_bytes(raw)
        finally: app.uploading = False
    return dict(path=app.relative(target), bytes=len(raw))


def import_document(app, raw):
    if len(raw) > ui_stream.JSON_LIMIT: raise ValueError('Graph JSON exceeds 128 MB.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict): raise ValueError('Choose a PySAS graph JSON.')
    if value.get('format') == 'pysas-graph-1': return migrate(app, value)
    graph = validate(value); graph['id'] = uuid.uuid4().hex
    if 'assets' in value:
        restored = ui_stream.import_document(app, json.dumps(dict(stream_document(graph), assets=value['assets']), ensure_ascii=False).encode('utf-8'))
        graph['egp'] = restored['egp']; rows = iter(restored['rows'])
        for node in graph['setup'] + graph['nodes']: node['rows'] = [next(rows) for _ in node['rows']]
    return hydrate(app, graph)

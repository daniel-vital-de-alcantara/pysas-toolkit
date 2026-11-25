"""Stream-task graph definitions, portable import and frozen run preparation."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import uuid
from datetime import datetime
import shutil
import time

import egp_extract
import ui_graph
import ui_stream

FORMAT = 'pysas-task-graph-2'
AUTHORING_FORMAT = 'pysas-task-graph-authoring-2'
FORMATS = {FORMAT, 'pysas-task-graph-1'}
AUTHORING_FORMATS = {AUTHORING_FORMAT, 'pysas-task-graph-authoring-1'}
STORED_LIMIT = 20 * 1024**2
MAX_DEPTH = 8
MAX_CARDS = 1000


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('Graph and task IDs must be unique letters, digits, underscores or hyphens.')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid canvas position or zoom.')
    return value


def validate(value, *, _depth=0, _budget=None):
    if _depth > MAX_DEPTH: raise ValueError('Graphs can be nested up to 8 levels deep.')
    if _budget is None: _budget = dict(cards=0, rows=0, inline=0, edges=0)
    if not isinstance(value, dict) or value.get('format') not in FORMATS:
        raise ValueError('Choose a PySAS task graph JSON.')
    # Each task uses the same source/selection schema as Run stream.
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
    for key in ('inherit_connection', 'inherit_shared_work'):
        if key in value or _depth:
            setting = value.get(key, True)
            if type(setting) is not bool: raise ValueError(key + ' must be a checkbox value.')
            result[key] = setting
    ids, source_ids, total_rows, total_inline = set(), set(), 0, 0
    for key, limit in (('setup', 100), ('nodes', 200)):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > limit: raise ValueError(f'Use at most {limit} {key} cards.')
        for node in items:
            if not isinstance(node, dict): raise ValueError('Invalid task card.')
            key_id = identifier(node.get('id'))
            if key_id.casefold() in ids: raise ValueError('Task IDs must be unique across tasks and shared setup.')
            ids.add(key_id.casefold())
            _budget['cards'] += 1
            if _budget['cards'] > MAX_CARDS: raise ValueError('Use at most 1,000 cards across the graph and all nested graphs.')
            kind = node.get('kind', 'task')
            if kind not in {'task', 'graph'}: raise ValueError('Choose a task card or a graph card.')
            if kind == 'graph':
                if key == 'setup': raise ValueError('Shared setup must contain source cards, not graphs.')
                if node.get('rows'): raise ValueError('Graph cards contain a graph, not source rows.')
                child = validate(node.get('graph'), _depth=_depth+1, _budget=_budget)
                result[key].append(dict(id=key_id, name=ui_stream.label(node.get('name', ''), 'Untitled graph'), kind='graph', rows=[],
                    x=number(node.get('x', 0), -100000, 100000), y=number(node.get('y', 0), -100000, 100000), graph=child))
                continue
            if node.get('graph') is not None: raise ValueError('Use a graph card to contain a nested graph.')
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
                x=number(node.get('x', 0), -100000, 100000), y=number(node.get('y', 0), -100000, 100000),
                export_html=stream['export_html'], export_tables=stream['export_tables'], consolidate_tables=stream['consolidate_tables']))
    if total_rows > 1000 or total_inline > ui_stream.SOURCE_LIMIT: raise ValueError('A graph supports 1,000 source programs and 16 MB of inline code in total.')
    _budget['rows'] += total_rows; _budget['inline'] += total_inline
    if _budget['rows'] > 1000 or _budget['inline'] > ui_stream.SOURCE_LIMIT:
        raise ValueError('Nested graphs together support 1,000 source programs and 16 MB of inline code in total.')
    edges = value.get('edges', [])
    if not isinstance(edges, list) or len(edges) > 2000: raise ValueError('Use at most 2,000 dependencies.')
    tasks, pairs = {n['id'] for n in result['nodes']}, set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in tasks or edge.get('to') not in tasks or edge['from'] == edge['to']:
            raise ValueError('Dependencies must connect different task cards. Shared setup applies to every task without arrows.')
        pair = (edge['from'], edge['to'])
        if pair in pairs: raise ValueError('This dependency already exists.')
        pairs.add(pair); result['edges'].append(dict(zip(('from', 'to'), pair)))
    _budget['edges'] += len(edges)
    if _budget['edges'] > 5000: raise ValueError('Use at most 5,000 dependencies across all graph levels.')
    remaining = set(tasks)
    while remaining:
        ready = {task for task in remaining if not any(e['to'] == task and e['from'] in remaining for e in result['edges'])}
        if not ready: raise ValueError('Circular dependency detected. Remove a link.')
        remaining -= ready
    return result


def local_rows(graph):
    return [row for node in graph['setup'] + graph['nodes'] for row in node['rows']]


def levels(graph, path=()):
    yield path, graph
    for node in graph['nodes']:
        if node.get('kind') == 'graph': yield from levels(node['graph'], (*path, node['id']))


def all_rows(graph):
    return [row for _, level in levels(graph) for row in local_rows(level)]


def stream_document(graph):
    return dict(graph, format=ui_stream.FORMAT, rows=local_rows(graph))


def asset_refs(graph):
    for _, level in levels(graph): yield from ui_stream.asset_refs(stream_document(level))


def assets(app, graph):
    return ui_stream.assets(app, stream_document(graph), refs=asset_refs(graph))


def hydrate(app, graph):
    for ref, suffix in asset_refs(graph):
        try:
            raw = ui_stream.read_asset(app, ref, suffix)
            if suffix == '.sas': ref.update(ui_stream.scan_source(ui_stream._decode(raw)))
        except (OSError, ValueError) as exc: ref['source_error'] = str(exc)
    for row in all_rows(graph):
        if row['source_kind'] == 'inline': row['analysis'] = ui_stream.scan_source(row['code'])
    return graph


def validate_saved(value):
    if isinstance(value, dict) and value.get('format') in FORMATS: return validate(value)
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
    raw = json.dumps(ui_stream.portable(graph, assets(app, graph)), ensure_ascii=False, indent=2).encode('utf-8')
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
    if value.get('format') in AUTHORING_FORMATS: return authoring(app, value)
    if value.get('format') == 'pysas-graph-1': return migrate(app, value)
    graph = validate(value); graph['id'] = uuid.uuid4().hex
    if 'assets' in value: ui_stream.import_assets(app, asset_refs(graph), value['assets'])
    return hydrate(app, graph)


def refresh(app, value, *, execution=False):
    graph = validate(value)
    used_connections=set()
    def connections(level,path=(),owner=()):
        if not path or not level.get('inherit_connection',True):owner=path
        if any(n.get('kind')!='graph' for n in level['nodes']):used_connections.add(owner)
        for node in level['nodes']:
            if node.get('kind')=='graph':connections(node['graph'],(*path,node['id']),owner)
    if execution:connections(graph)
    for path, level in levels(graph):
        document = json.loads(json.dumps(stream_document(level)))
        inherited = bool(path and level.get('inherit_connection', True)) or (execution and path not in used_connections)
        if inherited: document['egp'] = None
        # Inactive drafts are preserved in templates, but never submitted.
        for row in document['rows']:
            if row['source_kind']=='file':row.update(code='',project=None,programs=[])
            elif row['source_kind']=='inline':row.update(file=None,project=None,programs=[])
            else:
                row.update(file=None,code='')
                for program in row['programs']:program['file']=None
        updated = ui_stream.refresh_document(app, document)
        if not inherited or execution: level['egp'] = updated['egp']
        level['shared_work'] = updated['shared_work']
        for original,fresh in zip(local_rows(level),updated['rows']):
            if execution:original.update(fresh)
            elif original['source_kind']=='file':original['file']=fresh['file']
            elif original['source_kind']=='inline':original['analysis']=fresh['analysis']
            else:original.update(project=fresh['project'],programs=fresh['programs'])
    return graph


def task_document(graph, node):
    """Shared setup is source, never a separately scheduled task."""
    return dict(format=ui_stream.FORMAT, name=node['name'], egp=graph['egp'], connection_mode=graph['connection_mode'],
                server_program=graph['server_program'], shared_work=graph['shared_work'],
                rows=[row for setup in graph['setup'] for row in setup['rows']] + node['rows'],
                **{key: node[key] for key in ('export_html','export_tables','consolidate_tables')})


def selection_ids(task_id=None, task_ids=None):
    """None is a full graph. An empty/invalid selection must never mean run all."""
    if task_id is not None and task_ids is not None: raise ValueError('Choose a task or a selection, not both.')
    if task_id is not None: return [identifier(task_id)]
    if task_ids is None: return None
    if not isinstance(task_ids, list) or not 1 <= len(task_ids) <= 200:
        raise ValueError('Select 1 to 200 task cards to run.')
    ids = [identifier(key) for key in task_ids]
    if len(set(ids)) != len(ids): raise ValueError('Selected task IDs must be unique.')
    return ids


def path_ids(value=None):
    if value is None: return []
    if not isinstance(value, list) or len(value) > MAX_DEPTH: raise ValueError('Choose a valid graph level.')
    return [identifier(key) for key in value]


def graph_at(value, path):
    current = value
    for key in path_ids(path):
        node = next((n for n in current.get('nodes', []) if isinstance(n, dict) and n.get('id') == key), None)
        if not node or node.get('kind') != 'graph' or not isinstance(node.get('graph'), dict):
            raise ValueError('The selected nested graph no longer exists.')
        current = node['graph']
    return current


def record_scope(record):
    """Read old single-task history and current selected-task records."""
    return record.get('graph_task_ids') or ([record['graph_task_id']] if record.get('graph_task_id') else None)


def conflicts(commands, graph_id, ids, exclude=None, *, graph_path=None):
    path = tuple(path_ids(graph_path))
    scopes = [path] if ids is None else [(*path, key) for key in ids]
    for c in commands:
        if c.get('id') == exclude or c.get('action') != 'task-graph' or c.get('graph_id') != graph_id or c.get('status') not in {'RUNNING','STOPPING'}: continue
        other_path = tuple(c.get('graph_run_path') or [])
        other_ids = record_scope(c)
        others = [other_path] if other_ids is None else [(*other_path,key) for key in other_ids]
        if any(a[:len(b)] == b or b[:len(a)] == a for a in scopes for b in others): return True
    return False


def run_name(value, task_id=None, task_ids=None, *, graph_path=None):
    name = value.get('name') or 'Graph'; current = value
    for key in path_ids(graph_path):
        node = next((n for n in current.get('nodes',[]) if n.get('id') == key), None)
        if not node or node.get('kind') != 'graph': raise ValueError('The selected nested graph no longer exists.')
        name += ' / ' + node['name']; current = node['graph']
    ids = selection_ids(task_id, task_ids)
    if task_id is not None:
        node = next((n for n in current.get('nodes', []) if n.get('id') == task_id), {})
        name += ' · ' + node.get('name', task_id)
    elif ids is not None: name += f' · {len(ids)} selected task' + ('s' if len(ids) != 1 else '')
    return name[:120]


def scope_omissions(value, ids, graph_path):
    current = value; prefix = []; result = []
    def add(level, selected):
        for edge in level['edges']:
            if edge['to'] in selected and edge['from'] not in selected:
                result.append({key:'/'.join([*prefix,edge[key]]) for key in ('from','to')})
    for key in graph_path:
        add(current,[key]);current = graph_at(current,[key]);prefix.append(key)
    if ids is not None: add(current,ids)
    return result


def execution_document(app, value, task_id=None, *, task_ids=None, graph_path=None):
    graph = validate(value); path = path_ids(graph_path); current = graph
    name = run_name(graph,task_id,task_ids,graph_path=path)
    for key in path:
        child = graph_at(current,[key]);node = next(n for n in current['nodes'] if n['id']==key)
        current['nodes'],current['edges'] = [node],[]; current = child
    if not current['nodes']: raise ValueError('Add at least one task to run.')
    ids = selection_ids(task_id, task_ids)
    if ids is not None:
        if set(ids) - {n['id'] for n in current['nodes']}: raise ValueError('Choose task cards to run. Shared setup is prepended to tasks.')
        current['nodes'] = [n for n in current['nodes'] if n['id'] in ids]
        current['edges'] = [e for e in current['edges'] if e['from'] in ids and e['to'] in ids]
    graph['name'] = name
    return refresh(app, graph,execution=True)


def effective(level, parent=None):
    result = dict(level)
    if parent:
        if level.get('inherit_connection', True):
            for key in ('egp','connection_mode','server_program'): result[key] = parent[key]
        if level.get('inherit_shared_work', True): result['shared_work'] = parent['shared_work']
    return result


def nested_task_document(level, node, path, setup):
    if not path: return task_document(level,node)
    rows = []
    for namespace,card in [*setup,(path,node)]:
        for original in card['rows']:
            row = json.loads(json.dumps(original))
            for unit in [row,*row['programs']]:
                unit['id'] = 's_' + hashlib.sha256(('/'.join([*namespace,card['id'],unit['id']])).encode()).hexdigest()[:48]
            rows.append(row)
    return dict(task_document(dict(level,setup=[]),node),rows=rows)


def prepare(app, value, task_id=None, cancelled=lambda:False, progress=lambda text:None, *, task_ids=None, graph_path=None, started=None, prepared_graph=None):
    started=time.time() if started is None else started;path=path_ids(graph_path);ids=selection_ids(task_id,task_ids)
    if cancelled():raise InterruptedError('Cancelled before submission.')
    graph=validate(prepared_graph) if prepared_graph is not None else execution_document(app,value,task_id,task_ids=task_ids,graph_path=path)
    if ids is not None and set(ids)!={n['id'] for n in graph_at(graph,path)['nodes']}:raise ValueError('Prepared tasks do not match the selected tasks.')
    raw_assets=assets(app,graph)
    timing_cache=dict(records=ui_stream.stream_history(app),samples=app.timing_samples())
    folder = app.tasks/'schedules'/(datetime.now().strftime('%Y%m%d_%H%M%S')+'__graph_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    try:
        manifest=dict(name=graph['name'],graph_id=graph['id'],started=started,workers=graph['workers'],mode='task' if task_id is not None else 'selection' if ids is not None else 'subgraph' if path else 'graph',
                      graph_path=path,selected_task_ids=ids,external_prerequisites=scope_omissions(validate(value),ids,path),tasks=[])
        root_ids={n['id'] for n in graph['nodes']};keys={};groups=[];count=0
        total=sum(n.get('kind')!='graph' for _,g in levels(graph) for n in g['nodes'])
        def key_for(node_path):
            if len(node_path)==1:return node_path[0]
            salt='';key='g_'+hashlib.sha256(('/'.join(node_path)+salt).encode()).hexdigest()[:48]
            while key in root_ids:salt+='!';key='g_'+hashlib.sha256(('/'.join(node_path)+salt).encode()).hexdigest()[:48]
            return key
        for prefix,level in levels(graph):
            for node in level['nodes']:keys[(*prefix,node['id'])]=key_for((*prefix,node['id']))
        def build(level,prefix=(),labels=(),parent=None,destination=folder,parent_context=None,inherited=()):
            nonlocal count
            context=effective(level,parent_context);setup=[*inherited,*[(prefix,n) for n in level['setup']]]
            if not level['nodes']:raise ValueError(' / '.join(labels or (level['name'],))+': add at least one task to the graph.')
            if any(not card['rows'] for _,card in setup):raise ValueError('Complete every shared setup card before running.')
            for index,node in enumerate(level['nodes'],1):
                if cancelled():raise InterruptedError('Cancelled before submission.')
                node_path=(*prefix,node['id']);key=keys[node_path];group=node.get('kind')=='graph'
                # Keep deep Windows EG paths short. Runtime IDs remain based on
                # logical node paths; the frozen plan maps them to these folders.
                component=f'node_{index:03d}' if prefix else f'graph_{index:03d}' if group and len(node['id'])>16 else 'task_'+node['id']
                target=(destination if prefix else destination/'tasks')/component
                definition=dict(task_id=key,program=node['name'],depends_on=[keys[(*prefix,e['from'])] for e in level['edges'] if e['to']==node['id']],path=target.relative_to(folder).as_posix(),
                    kind='graph' if group else 'task',parent_id=parent,node_path=list(node_path),label_path=[*labels,node['name']],stream_task=not group,setup=[dict(program=n['name']) for _,n in setup])
                manifest['tasks'].append(definition)
                if group:
                    target.mkdir(parents=True);definition.update(workers=node['graph']['workers'],estimate=None)
                    groups.append((definition,node['graph'],target));build(node['graph'],node_path,(*labels,node['name']),key,target,context,setup)
                else:
                    if not context['egp']:raise ValueError(' / '.join([*labels,node['name']])+': choose a connection EGP in Graph settings before running.')
                    if not node['rows']:raise ValueError(node['name']+': add at least one source card.')
                    count+=1;progress(f'Preparing task {count}/{total} · '+ ' / '.join([*labels,node['name']]))
                    _,_,forecast=ui_stream.prepare(app,nested_task_document(context,node,prefix,setup),destination=target,timing_cache=timing_cache,raw_assets=raw_assets)
                    definition['estimate']=forecast
        build(graph)
        portable=json.dumps(ui_stream.portable(graph,raw_assets),ensure_ascii=False,indent=2)
        if len(portable.encode('utf-8'))>ui_stream.JSON_LIMIT:raise ValueError('Portable graph JSON exceeds 128 MB.')
        (folder/'task-graph.json').write_text(portable,encoding='utf-8')
        (folder/'task-graph-plan.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        for definition,child,target in groups:
            descendants=[dict(t,path=(folder/t['path']).relative_to(target).as_posix()) for t in manifest['tasks'] if t['node_path'][:len(definition['node_path'])]==definition['node_path'] and t['task_id']!=definition['task_id']]
            local=dict(name=definition['program'],graph_id=child['id'],workers=child['workers'],root_parent=definition['task_id'],tasks=descendants,mode='graph',started=None)
            (target/'task-graph-plan.json').write_text(json.dumps(local,ensure_ascii=False,indent=2),encoding='utf-8')
            (target/'graph-definition.json').write_text(json.dumps(child,ensure_ascii=False,indent=2),encoding='utf-8')
        return folder,graph,manifest
    except BaseException:
        shutil.rmtree(folder);raise


def authoring(app, value):
    """Bind AI/human-authored paths without weakening portable checksum validation."""
    graph = json.loads(json.dumps(value));graph['format']=FORMAT;graph['id']=uuid.uuid4().hex
    def bind(value,suffix):
        if not value:return None
        path=value if isinstance(value,str) else value.get('path') if isinstance(value,dict) else None
        if not isinstance(path,str):raise ValueError('Use a local '+suffix+' path.')
        ref=ui_stream.describe(app,path)
        if not ref['name'].lower().endswith(suffix):raise ValueError('Choose a '+suffix+' file.')
        return ref
    def visit(level,depth=0):
        if not isinstance(level,dict) or depth>MAX_DEPTH:raise ValueError('Graphs can be nested up to 8 levels deep.')
        level['format']=FORMAT;level['id']=uuid.uuid4().hex;level['egp']=bind(level.get('egp'),'.egp')
        for kind in ('setup','nodes'):
            if not isinstance(level.get(kind,[]),list):raise ValueError('Use a list of '+kind+' cards.')
            for index,node in enumerate(level.get(kind,[])):
                if not isinstance(node,dict):raise ValueError('Invalid task card.')
                node.setdefault('x',(index%4)*374);node.setdefault('y',(index//4)*223)
                if node.get('kind')=='graph':
                    if kind=='setup':raise ValueError('Shared setup cannot contain graph cards.')
                    visit(node.get('graph'),depth+1);continue
                for row in node.get('rows',[]):
                    if not isinstance(row,dict):raise ValueError('Invalid source card.')
                    row.setdefault('id','s_'+uuid.uuid4().hex);row.setdefault('source_kind','file');row.setdefault('programs',[])
                    if row.get('file'):row['file']=bind(row['file'],'.sas')
                    if row.get('project'):row['project']=bind(row['project'],'.egp')
                    if row['source_kind']=='egp':raise ValueError('Authoring JSON supports file and inline sources. Select embedded EGP programs in the editor, then export a portable template.')
    visit(graph)
    return hydrate(app,validate(graph))

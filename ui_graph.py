"""Saved graph documents and explicit source selection for the optional Graph tab."""
import hashlib
import json
from pathlib import Path
import re
import uuid
import zipfile
from pysas import validate_graph, graph_source_path, graph_egp_programs, GRAPH_SOURCE_LIMIT, text_encoding, select_graph_text


def graph_path(app, identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',identifier):raise ValueError('Invalid graph ID.')
    folder=app.settings/'graphs';folder.mkdir(exist_ok=True)
    path=(folder/(identifier+'.json')).resolve()
    if path.parent!=folder.resolve():raise ValueError('Graph points outside its settings folder.')
    return path


def load(app, identifier):
    path=graph_path(app,identifier);raw=path.read_bytes()
    if len(raw)>2*1024**2:raise ValueError('Graph JSON exceeds 2 MB.')
    graph=validate_graph(json.loads(raw.decode('utf-8-sig')))
    return dict(graph=graph,revision=hashlib.sha256(raw).hexdigest(),path=app.relative(path))


def listing(app):
    folder=app.settings/'graphs'
    if not folder.exists():return []
    result=[]
    for path in folder.glob('*.json'):
        if path.is_symlink():continue
        try:
            saved=load(app,path.stem)
            result.append(dict(id=path.stem,name=saved['graph']['name'],nodes=len(saved['graph']['nodes']),updated=path.stat().st_mtime))
        except (OSError,ValueError,UnicodeError):continue
    return sorted(result,key=lambda item:item['updated'],reverse=True)[:500]

def sources(app):
    folder=app.tasks/'graph-sources'
    return sorted(app.relative(p) for p in folder.glob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() in {'.sas','.egp'})[:1000] if folder.exists() else []


def save(app,data):
    graph=validate_graph(data.get('graph'))
    if not graph['id']:graph['id']=uuid.uuid4().hex
    path=graph_path(app,graph['id'])
    with app.lock:
        if app.storage_busy:raise ValueError('Wait for the saved-data operation to finish.')
        if path.exists() and data.get('revision')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('This graph changed in another window. Reload it before saving.')
        from pysas_ui import atomic_json
        atomic_json(path,graph)
    return load(app,graph['id'])


def chosen_path(app,value,suffix):
    if not isinstance(value,str) or not value.strip():raise ValueError('Choose a '+suffix+' file.')
    candidate=Path(value).expanduser()
    if not candidate.is_absolute():candidate=app.resolve(value)
    return graph_source_path(str(candidate),app.root,suffix)


def link_file(app,data):
    path=chosen_path(app,data.get('path'),'.sas')
    if path.stat().st_size>GRAPH_SOURCE_LIMIT:raise ValueError('SAS source exceeds 16 MB.')
    raw=path.read_bytes();raw.decode(text_encoding(raw),errors='strict')
    return dict(name=path.name,source=dict(type='file',path=app.relative(path) or str(path)),sha256=hashlib.sha256(raw).hexdigest())


def egp_programs(app,data):
    path=chosen_path(app,data.get('path'),'.egp')
    programs,warnings=graph_egp_programs(path)
    return dict(path=app.relative(path) or str(path),programs=programs,warnings=warnings)


def bind(app,value,*,runnable=False):
    graph=validate_graph(value,runnable=runnable)
    has_files=any(n['source']['type']=='file' and not n['skip'] for n in graph['nodes'])
    if not graph['connection'] and has_files:graph['connection']=app.server_template('')
    if graph['connection']:graph['connection']=str(chosen_path(app,graph['connection'],'.egp'))
    indexes={}
    for node in graph['setup']+graph['nodes']:
        source=node['source'];source['path']=str(chosen_path(app,source['path'],'.sas' if source['type']=='file' else '.egp'))
        if source['type']=='egp':
            if source['path'] not in indexes:indexes[source['path']]=graph_egp_programs(Path(source['path']))[0]
            program=next((p for p in indexes[source['path']] if p['id']==source['program_id']),None)
            if not program or not program['member']:raise ValueError(node['name']+': embedded source is unavailable. Link the external SAS file instead.')
            if node in graph['nodes'] and program['duplicate']:raise ValueError(node['name']+': rename duplicate program names in Enterprise Guide before running.')
            with zipfile.ZipFile(source['path']) as archive:
                info=archive.getinfo(program['member'])
                if info.file_size>GRAPH_SOURCE_LIMIT:raise ValueError('SAS source exceeds 16 MB.')
                raw=archive.read(info)
        else:
            if Path(source['path']).stat().st_size>GRAPH_SOURCE_LIMIT:raise ValueError('SAS source exceeds 16 MB.')
            raw=Path(source['path']).read_bytes()
        select_graph_text(raw.decode(text_encoding(raw),errors='strict'),node)
    return graph


def launch(app,data):
    graph=bind(app,data.get('graph'),runnable=True)
    if not graph['id']:graph['id']=uuid.uuid4().hex
    with app.lock:
        if app.storage_busy:raise ValueError('Wait for the saved-data operation to finish.')
        folder=app.storage/'graph-plans';folder.mkdir(exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.json')
        from pysas_ui import atomic_json
        atomic_json(path,graph)
    try:
        return app.launch(dict(action='schedule',_graph_plan=str(path),graph_id=graph['id'],display_name=graph['name'],workers=graph['workers']))
    except BaseException:
        path.unlink(missing_ok=True)
        raise

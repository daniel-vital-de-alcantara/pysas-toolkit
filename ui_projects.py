"""Folder-oriented bundle projects and their immutable pack/unpack versions."""
import hashlib
import json
import os
from pathlib import Path
import time


def key(path):return hashlib.sha256(os.path.normcase(str(path)).encode('utf-8')).hexdigest()[:24]
def label(path):return str(path).replace('\\','/').rstrip('/').rsplit('/',1)[-1] or str(path)
def registry(app):
    from pysas_ui import read_json
    return read_json(app.config('projects.json'),{})

def record(app,path,**options):
    from pysas_ui import atomic_json
    with app.lock:
        saved=registry(app);identifier=key(path);item=saved.get(identifier,{'path':str(path),'name':''})
        item.update({k:v for k,v in options.items() if k in {'output','recursive'}});item['updated']=time.time();saved[identifier]=item
        atomic_json(app.config('projects.json'),saved)
    return identifier

def listing(app):
    saved=registry(app);groups={key(p['path']):dict(p,id=key(p['path']),versions=[]) for p in saved.values() if isinstance(p,dict) and p.get('path')}
    with app.lock:commands=[dict(c) for c in app.commands.values() if c.get('action','').startswith('bundle-')]
    for path in app.bundle_settings()['paths']:groups.setdefault(key(path),dict(id=key(path),path=path,name='',versions=[]))
    for command in commands:
        path=command.get('code_root') or str(app.root);identifier=key(path)
        item=groups.setdefault(identifier,dict(id=identifier,path=path,name='',versions=[]));item['versions'].append(command)
    result=[]
    for item in groups.values():
        versions=sorted(item.pop('versions'),key=lambda c:c.get('started',0),reverse=True)
        latest=next((c for c in versions if c.get('status')=='SUCCESS' and c.get('download') and c.get('action') in {'bundle-pack','bundle-unpack'} and (app.storage/'artifacts'/c['download']).is_file()),None)
        pack=next((c for c in versions if c.get('action')=='bundle-pack'),None)
        if pack:
            args=pack.get('args',[])
            if '--output' in args:
                try:item['output']=str(Path(args[args.index('--output')+1]).relative_to(Path(item['path'])))
                except (ValueError,IndexError):pass
            item['recursive']='--recursive' in args
        item.update(name=item.get('name') or label(item['path']),updated=max([item.get('updated',0),*[c.get('finished') or c.get('started',0) for c in versions]]),version_count=len(versions),latest_command=latest['id'] if latest else None,status=versions[0]['status'] if versions else 'EMPTY')
        result.append(item)
    return sorted(result,key=lambda p:p['updated'],reverse=True)

def get(app,identifier):
    project=next((p for p in listing(app) if p['id']==identifier),None)
    if not project:raise ValueError('Project folder not found.')
    return project

def versions(app,identifier):
    project=get(app,identifier)
    with app.lock:
        items=[dict(c) for c in app.commands.values() if c.get('action','').startswith('bundle-') and key(c.get('code_root') or str(app.root))==identifier]
    return sorted(items,key=lambda c:c.get('started',0),reverse=True)

def rename(app,data):
    from pysas_ui import atomic_json
    project=get(app,data.get('id'));name=app.display_name(data.get('name',''))
    with app.lock:
        saved=registry(app);item=saved.get(project['id'],dict(path=project['path']))
        item['name']=name;saved[project['id']]=item;atomic_json(app.config('projects.json'),saved)
    return {'id':project['id'],'name':name or label(project['path'])}

def update(app,identifier):
    project=get(app,identifier)
    return app.launches.start(dict(action='bundle-pack',code_root=project['path'],output=project.get('output') or 'codebase.sasbundle.txt',recursive=project.get('recursive',False)))

def copy_latest(app,identifier):
    project=get(app,identifier)
    if not project['latest_command']:raise ValueError('No completed bundle is available for this folder.')
    return app.copy_file(command=project['latest_command'])

def detail(app,identifier,selected=None):
    project=get(app,identifier);items=versions(app,identifier)
    chosen=next((c for c in items if c['id']==selected),None) if selected else (items[0] if items else None)
    if selected and not chosen:raise ValueError('That version is not part of this project folder.')
    base=app.command_details(chosen['id']) if chosen else dict(files=[],tasks=[],status='EMPTY',name=project['name'],description=project['path'],whole_run=False,folder_path='',export_scope=None)
    base.update(name=project['name'],project_id=identifier,project_path=project['path'],can_rename=True,project_versions=[dict(id=c['id'],action=c['action'],status=c['status'],started=c['started'],elapsed=c.get('elapsed'),download=bool(c.get('download'))) for c in items])
    return base

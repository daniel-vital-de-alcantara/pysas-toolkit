// Exercise the shipped editor DOM, asynchronous source preparation and actual events.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const h=require('../ui/stream.js');
const root=path.join(__dirname,'..');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function settle(check=()=>true){for(let i=0;i<160;i++){await pause(5);if(check())return;}assert.fail('Stream UI did not settle');}

function harness(t,{automatic=true}={}){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/index.html'),'utf8'),{url:'http://localhost/#stream',runScripts:'outside-only'});
  t.after(()=>dom.window.close());const w=dom.window,$=id=>w.document.getElementById(id),calls=[],uploads=[],inspected=[],sourceInfo=new Map();
  const ref=(name)=>({path:'tasks/stream-sources/'+name,name,sha256:'a'.repeat(64),lines:50,sections:['Realised','Cases'],...sourceInfo.get(name)});
  const catalog={programs:[{id:'A',name:'Alpha',flow:'Setup',member:'A/code.sas'},{id:'B',name:'Beta',flow:'Extracts',member:'B/code.sas'},{id:'External',name:'External source',flow:'Extracts',member:null}],flows:[{id:'f1',name:'Setup'},{id:'f2',name:'Extracts'}],warnings:[]};
  const snapshot={token:'csrf',windows:true,openpyxl:true,files:['connection.egp'],commands:[],shared_work:{enabled:false,path:'/server/shared',libref:'VDI'}};
  let failure='',restored=null,jobHandler=null,deferred=new Map(),xhrHandler=null;
  w.XMLHttpRequest=class{
    constructor(){this.upload={};this.status=200;}
    open(method,url){this.url=url;}
    setRequestHeader(name,value){assert.equal(name,'X-PySAS-Token');assert.equal(value,'csrf');}
    send(file){uploads.push({url:this.url,file});const complete=value=>{if(value?.error){this.status=400;this.responseText=JSON.stringify(value);}else this.responseText=JSON.stringify(value);this.onload();};setImmediate(()=>{this.upload.onprogress?.({lengthComputable:true,loaded:1,total:1});this.upload.onload?.();if(xhrHandler)return xhrHandler(this.url,file,complete);if(failure)return complete({error:failure});complete(this.url==='/api/stream-import'?{stream:restored}:ref(file.name));});}
  };
  const ready=result=>({id:'job',status:'READY',result});
  w.PySASGraphHost={request:async(url,data)=>{
    calls.push({url,data:data?structuredClone(data):null});if(deferred.has(url)){const callback=deferred.get(url);deferred.delete(url);return callback(data);}if(failure)throw Error(failure);
    if(url==='/api/stream-job'){
      if(jobHandler){const result=jobHandler(data);if(result)return result;}
      if(data.kind==='connection')return ready({egp:automatic||data.path?ref(data.path?.split('/').pop()||'connection.egp'):null,catalog:automatic||data.path?catalog:null});
      if(data.kind==='project')return ready({project:data.project,catalog});
      return ready({program:catalog.programs.find(p=>p.id===data.program_id),file:ref(data.program_id==='A'?'Alpha.sas':'Beta.sas')});
    }
    if(url==='/api/stream-analyze'){const sections=[...data.code.matchAll(/section_start: (.+?);/g)].map(m=>m[1]);return {lines:data.code.split('\n').length,sections,section_issues:[]};}
    if(url==='/api/stream-estimate')return {seconds:60,unknown:1,basis:'Partial history'};
    if(url==='/api/stream-run'){snapshot.commands=[{id:'stream1',action:'stream',name:data.stream.name,status:'RUNNING',tasks:{}}];return {id:'stream1'};}
    return {path:'tasks/.workbench/artifacts/example'+(url.endsWith('source')?'.sas':'.json')};
  },refresh:async()=>w.PySASStream.update(snapshot,'stream'),inspect:async id=>inspected.push(id),navigate:page=>{w.document.getElementById('page-stream').hidden=page!=='stream';w.document.getElementById('page-files').hidden=page!=='files';},badge:s=>s,timer:()=>'<span class="elapsed">00:00:01</span>',expectedText:e=>e.seconds==null?'Unknown duration':e.seconds+'s'+(e.unknown?'+':''),fileActions:({path},label)=>`<a download href="/api/download?path=${path}">Download ${label}</a><button data-copy-target='{"path":"${path}"}'>Copy file</button>`};
  w.eval(fs.readFileSync(path.join(root,'ui/stream.js'),'utf8'));w.PySASStream.update(snapshot,'stream');
  const change=(element,value)=>{if(typeof element==='string')element=$(element);element.value=value;element.dispatchEvent(new w.Event('change',{bubbles:true}));};
  const input=(element,value)=>{if(typeof element==='string')element=$(element);element.value=value;element.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const upload=async(element,name)=>{Object.defineProperty(element,'files',{configurable:true,value:[new w.File(['example'],name)]});element.dispatchEvent(new w.Event('change',{bubbles:true}));await pause(15);};
  const rows=()=>[...$('stream-rows').querySelectorAll('[data-stream-row]')];
  const start=async()=>{$('stream-new').click();await settle(()=>automatic?$('stream-files-stage').hidden===false:$('stream-connection-options').open);};
  const add=()=>{$('stream-add').click();return rows().at(-1);};
  const addFile=async name=>{const element=add(),id=element.dataset.streamRow;await upload(element.querySelector('[data-stream-upload]'),name);await settle(()=>rows().find(r=>r.dataset.streamRow===id)?.classList.contains('is-ready'));return rows().find(r=>r.dataset.streamRow===id);};
  const current=key=>rows().find(r=>r.dataset.streamRow===key);
  const exportDoc=async()=>{$('stream-export').click();await settle(()=>calls.some(c=>c.url==='/api/stream-export'));return calls.findLast(c=>c.url==='/api/stream-export').data.stream;};
  return {w,$,calls,uploads,inspected,snapshot,catalog,ready,ref,rows,current,change,input,upload,start,add,addFile,exportDoc,setFailure:value=>failure=value,setRestored:value=>restored=value,setJobs:value=>jobHandler=value,setXHR:value=>xhrHandler=value,setDefer:(url,callback)=>deferred.set(url,callback),sourceInfo};
}

test('pure reorder helpers keep source selections and never mutate the previous draft',()=>{
  const doc=h.empty(),first=h.row();first.mode='lines';first.row_start=2;first.row_end=8;doc.rows=[first,{...h.row(),mode:'section',sections:['Cases','Realised']}];
  const moved=h.move(doc,first.id,1);assert.equal(moved.rows[1].row_start,2);assert.deepEqual(moved.rows[0].sections,['Cases','Realised']);assert.equal(doc.rows[0].id,first.id);
  assert.equal(h.remove(moved,first.id).rows.length,1);assert.equal(h.scope(moved.rows[1]),'Lines 2–8');assert.equal(h.reorder(doc,first.id,doc.rows[1].id,true).rows[1].id,first.id);
});

test('initial screen offers only new run/template; automatic EGP keeps connection options collapsed',async t=>{
  const {$,start,rows,calls}=harness(t);assert.equal($('stream-workspace').hidden,true);assert.equal(rows().length,0);
  await start();assert.equal($('stream-workspace').hidden,false);assert.equal($('stream-connection-options').open,false);assert.match($('stream-connection-summary').textContent,/Automatic.*connection.egp/);
  assert.equal($('stream-files-stage').firstElementChild.id,'stream-shared-work-card');assert.equal($('stream-rows').nextElementSibling.id,'stream-add');
  assert.equal($('stream-ready-controls').hidden,true);assert.equal(calls.filter(c=>c.url==='/api/stream-job'&&c.data.kind==='connection').length,1);
});

test('missing automatic EGP expands only connection setup and a browsed EGP unlocks sources',async t=>{
  const {$,start,upload}=harness(t,{automatic:false});await start();assert.equal($('stream-connection-options').open,true);assert.equal($('stream-files-stage').hidden,true);assert.match($('stream-egp-status').textContent,/No usable EGP/);
  await upload($('stream-egp-upload'),'new.egp');await settle(()=>$('stream-files-stage').hidden===false);assert.equal($('stream-connection-options').open,false);assert.match($('stream-connection-summary').textContent,/new.egp/);
});

test('source options appear only after file selection; blank row bounds hide all bottom actions',async t=>{
  const {$,start,add,upload,rows,change}=harness(t);await start();let element=add();assert.equal(element.querySelector('.stream-selection'),null);assert.equal($('stream-ready-controls').hidden,true);
  await upload(element.querySelector('[data-stream-upload]'),'extract.sas');await settle(()=>rows()[0].classList.contains('is-ready'));element=rows()[0];assert.ok(element.querySelector('.stream-selection'));
  change(element.querySelector('[data-unit-field="mode"]'),'lines');assert.equal($('stream-ready-controls').hidden,true);assert.match(element.querySelector('.stream-card-status').textContent,/first or last line/);
  change(rows()[0].querySelector('[data-unit-field="row_end"]'),'8');assert.equal($('stream-ready-controls').hidden,false);
  change(rows()[0].querySelector('[data-unit-field="row_start"]'),'10');assert.equal($('stream-ready-controls').hidden,true);assert.match($('stream-readiness').textContent,/first line is after/);
});

test('multiple section checkboxes keep source order and no-section mode teaches paired markers',async t=>{
  const {$,start,addFile,rows,change,exportDoc,sourceInfo}=harness(t);await start();await addFile('extract.sas');change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');assert.equal($('stream-ready-controls').hidden,true);
  for(const name of ['Cases','Realised']){const checkbox=rows()[0].querySelector(`[data-unit-section="${name}"]`);checkbox.checked=true;checkbox.dispatchEvent(new checkbox.ownerDocument.defaultView.Event('change',{bubbles:true}));}
  assert.equal($('stream-ready-controls').hidden,false);const doc=await exportDoc();assert.deepEqual(doc.rows[0].sections,['Realised','Cases']);
  sourceInfo.set('plain.sas',{sections:[]});await addFile('plain.sas');change(rows()[1].querySelector('[data-unit-field="mode"]'),'section');assert.match(rows()[1].textContent,/No complete named sections/);assert.match(rows()[1].textContent,/section_start: My section/);assert.match(rows()[1].textContent,/section_end: My section/);assert.equal($('stream-ready-controls').hidden,true);
});

test('a whitespace-only source stays incomplete after loading',async t=>{
  const {$,start,add,upload,rows,sourceInfo}=harness(t);await start();sourceInfo.set('blank.sas',{lines:2,sections:[],has_code:false});
  await upload(add().querySelector('[data-stream-upload]'),'blank.sas');await settle(()=>!rows()[0].classList.contains('is-loading'));
  assert.match(rows()[0].querySelector('.stream-card-status').textContent,/no SAS code/);assert.equal($('stream-ready-controls').hidden,true);
});

test('file moves/deletion preserve ranges and expose source/config actual-file Copy controls',async t=>{
  const {$,start,addFile,rows,change,calls}=harness(t);await start();await addFile('_cases.sas');change(rows()[0].querySelector('[data-unit-field="mode"]'),'lines');change(rows()[0].querySelector('[data-unit-field="row_end"]'),'8');await addFile('extract.sas');
  rows()[1].querySelector('[data-stream-action="up"]').click();$('stream-source').click();await settle(()=>$('stream-artifacts').querySelector('a'));assert.ok($('stream-artifacts').querySelector('[data-copy-target]'));
  const doc=calls.find(c=>c.url==='/api/stream-source').data.stream;assert.equal(doc.rows[0].file.name,'extract.sas');assert.equal(doc.rows[1].row_end,8);
  rows()[0].querySelector('[data-stream-action="delete"]').click();assert.equal(rows().length,1);assert.equal(rows()[0].querySelector('[data-unit-field="row_end"]').value,'8');assert.equal($('stream-rows').nextElementSibling.id,'stream-add');
});

test('inline code is analyzed asynchronously without losing the cursor or other card edits',async t=>{
  const {w,$,start,add,rows,change,input,exportDoc}=harness(t);await start();const element=add();change(element.querySelector('[data-stream-field="source_kind"]'),'inline');let editor=rows()[0].querySelector('textarea');editor.focus();input(editor,'%let ids=12;');
  assert.match(rows()[0].querySelector('.stream-card-status').textContent,/Reading sections/);assert.equal($('stream-ready-controls').hidden,true);
  input('stream-name','Case extracts');await settle(()=>$('stream-ready-controls').hidden===false);assert.equal(w.document.activeElement.tagName,'TEXTAREA');assert.equal(w.document.activeElement.value,'%let ids=12;');
  const doc=await exportDoc();assert.equal(doc.name,'Case extracts');assert.equal(doc.rows[0].source_kind,'inline');assert.equal(doc.rows[0].code,'%let ids=12;');assert.equal('analysis' in doc.rows[0],false);
});

test('shared WORK checkbox is explicit, links to settings and follows a settings edit on return',async t=>{
  const {w,$,start,addFile,snapshot,exportDoc}=harness(t);await start();await addFile('extract.sas');$('stream-shared-work').checked=true;$('stream-shared-work').dispatchEvent(new w.Event('change'));
  let doc=await exportDoc();assert.equal(doc.shared_work.enabled,true);assert.equal(doc.shared_work.path,'/server/shared');
  $('stream-shared-settings').click();assert.equal($('settings-shared-work').open,true);snapshot.shared_work={enabled:true,path:'/server/other',libref:'VDI'};w.PySASStream.update(snapshot,'stream');
  assert.match($('stream-shared-work-info').textContent,/other/);
});

test('switching a file card to inline code uses the editor sections and keeps the file draft',async t=>{
  const {w,$,start,addFile,rows,change,input,exportDoc}=harness(t);await start();await addFile('extract.sas');
  change(rows()[0].querySelector('[data-stream-field="source_kind"]'),'inline');
  input(rows()[0].querySelector('textarea'),'* (please do not delete) section_start: Macro;\n%let ids=12;\n* (please do not delete) section_end: Macro;');
  await settle(()=>$('stream-ready-controls').hidden===false);change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');
  assert.equal(rows()[0].querySelector('[data-unit-section="Realised"]'),null);
  const checkbox=rows()[0].querySelector('[data-unit-section="Macro"]');assert.ok(checkbox);checkbox.checked=true;checkbox.dispatchEvent(new w.Event('change',{bubbles:true}));
  const doc=await exportDoc();assert.deepEqual(doc.rows[0].sections,['Macro']);assert.equal(doc.rows[0].file.name,'extract.sas');
  const editor=rows()[0].querySelector('textarea');editor.focus();input(editor,'');assert.equal(rows()[0].querySelector('.stream-selection'),null);assert.equal(w.document.activeElement,editor);assert.equal($('stream-ready-controls').hidden,true);
});

test('late automatic discovery cannot replace a manually selected connection',async t=>{
  const {$,setJobs,ready,ref,catalog,upload}=harness(t);let finish;
  setJobs(data=>data.kind==='connection'&&!data.path?new Promise(resolve=>{finish=()=>resolve(ready({egp:ref('automatic.egp'),catalog}));}):null);
  $('stream-new').click();await settle(()=>finish);await upload($('stream-egp-upload'),'manual.egp');
  await settle(()=>$('stream-connection-summary').textContent.includes('manual.egp'));finish();await pause(25);
  assert.match($('stream-connection-summary').textContent,/manual.egp/);assert.equal($('stream-egp').value,ref('manual.egp').path);
});

test('EGP programs show process-flow filters, extract on selection and preserve chosen order',async t=>{
  const {w,$,start,add,rows,change,exportDoc}=harness(t);await start();change(add().querySelector('[data-stream-field="source_kind"]'),'egp');await settle(()=>rows()[0].querySelector('[data-egp-program="B"]'));
  assert.equal(rows()[0].querySelector('[data-egp-program="External"]').disabled,true);
  for(const key of ['B','A']){const checkbox=rows()[0].querySelector(`[data-egp-program="${key}"]`);checkbox.checked=true;checkbox.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>!rows()[0].classList.contains('is-loading'));}
  assert.equal($('stream-ready-controls').hidden,false);let doc=await exportDoc();assert.deepEqual(doc.rows[0].programs.map(p=>p.program_id),['B','A']);
  rows()[0].querySelectorAll('[data-stream-program]')[1].querySelector('[data-program-action="up"]').click();doc=await exportDoc();assert.deepEqual(doc.rows[0].programs.map(p=>p.program_id),['A','B']);
  change(rows()[0].querySelector('[data-stream-field="flow"]'),'Setup');assert.equal(rows()[0].querySelector('[data-egp-program="B"]'),null);
});

test('native mouse dragging reorders cards while pending extraction still completes on its card',async t=>{
  const {w,$,start,add,addFile,rows,change,setJobs,ready,ref,exportDoc}=harness(t);let finish;await start();setJobs(data=>data.kind==='program'?new Promise(resolve=>{finish=()=>resolve(ready({file:ref('Alpha.sas')}));}):null);
  change(add().querySelector('[data-stream-field="source_kind"]'),'egp');await settle(()=>rows()[0].querySelector('[data-egp-program="A"]'));
  const checkbox=rows()[0].querySelector('[data-egp-program="A"]');checkbox.checked=true;checkbox.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>finish);const pendingId=rows()[0].dataset.streamRow;
  await addFile('later.sas');assert.equal(rows()[1].classList.contains('is-ready'),true);assert.equal($('stream-add').disabled,false);
  const transfer={setData(){},effectAllowed:'',dropEffect:''};function drag(type,target,y=0){const event=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperties(event,{dataTransfer:{value:transfer},clientY:{value:y}});target.dispatchEvent(event);}
  rows()[1].getBoundingClientRect=()=>({top:0,height:100});drag('dragstart',rows()[0].querySelector('.stream-grip'));drag('dragover',rows()[1],90);drag('drop',rows()[1],90);assert.equal(rows()[1].dataset.streamRow,pendingId);
  finish();await settle(()=>$('stream-ready-controls').hidden===false);const doc=await exportDoc();assert.equal(doc.rows[0].file.name,'later.sas');assert.equal(doc.rows[1].programs[0].file.name,'Alpha.sas');
});

test('late background results cannot resurrect a deleted source card',async t=>{
  const {w,$,start,add,rows,change,setJobs,ready,ref}=harness(t);let finish;await start();setJobs(data=>data.kind==='program'?new Promise(resolve=>{finish=()=>resolve(ready({file:ref('Alpha.sas')}));}):null);
  change(add().querySelector('[data-stream-field="source_kind"]'),'egp');await settle(()=>rows()[0].querySelector('[data-egp-program="A"]'));
  const checkbox=rows()[0].querySelector('[data-egp-program="A"]');checkbox.checked=true;checkbox.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>finish);rows()[0].querySelector('[data-stream-action="delete"]').click();finish();await pause(25);assert.equal(rows().length,0);assert.equal($('stream-ready-controls').hidden,true);
});

test('Run forwards all output options through the normal engine/inspector boundary',async t=>{
  const {w,$,start,addFile,calls,inspected}=harness(t);await start();await addFile('extract.sas');for(const [key,checked] of [['stream-html',false],['stream-tables',true],['stream-consolidate',true]]){$(key).checked=checked;$(key).dispatchEvent(new w.Event('change'));}
  $('stream-run').click();await settle(()=>inspected.length);const doc=calls.find(c=>c.url==='/api/stream-run').data.stream;assert.equal(doc.export_html,false);assert.equal(doc.export_tables,true);assert.equal(doc.consolidate_tables,true);assert.deepEqual(inspected,['stream1']);
});

test('template restoration preserves inline, section choices, nested programs and blank range bound',async t=>{
  const {$,start,upload,rows,setRestored,exportDoc,ref}=harness(t);await start();const doc=h.empty();doc.egp=ref('connection.egp');doc.name='Restored cases';doc.rows=[{...h.row(),file:ref('saved.sas'),mode:'lines',row_end:22}];doc.export_tables=true;doc.consolidate_tables=true;
  setRestored(doc);await upload($('stream-import'),'template.json');await settle(()=>$('stream-name').value==='Restored cases'&&!$('stream-ready-controls').hidden);assert.equal(rows()[0].querySelector('[data-unit-field="row_start"]').value,'');assert.equal(rows()[0].querySelector('[data-unit-field="row_end"]').value,'22');const restored=await exportDoc();assert.equal(restored.rows[0].row_start,null);assert.equal(restored.consolidate_tables,true);
});

test('template import cannot discard edits made while its upload is pending',async t=>{
  const {$,start,addFile,input,rows,upload,setXHR,ref}=harness(t);await start();await addFile('current.sas');let finish;setXHR((url,file,complete)=>{finish=()=>{const doc=h.empty();doc.name='Imported';doc.egp=ref('connection.egp');complete({stream:doc});};});
  await upload($('stream-import'),'template.json');input('stream-name','Latest edit');finish();await settle(()=>$('stream-use-template').hidden===false);assert.equal($('stream-name').value,'Latest edit');assert.equal(rows().length,1);
  $('stream-use-template').click();assert.equal($('stream-name').value,'Imported');assert.equal(rows().length,0);await settle(()=>$('stream-connection-options').open===false&&$('stream-connection-summary').textContent.includes('connection.egp'));
});

test('restoring a mixed template retains inline sections and ordered nested EGP selections',async t=>{
  const {$,upload,rows,setRestored,exportDoc,ref}=harness(t);const doc=h.empty();doc.egp=ref('connection.egp');
  doc.rows=[{...h.row('inline'),name:'Setup macro',code:'* (please do not delete) section_start: Setup;\n%let ids=12;\n* (please do not delete) section_end: Setup;',mode:'section',sections:['Setup']},
    {...h.row('egp'),project:ref('connection.egp'),programs:[{...h.row(),program_id:'B',name:'Beta',flow:'Extracts',file:ref('Beta.sas'),mode:'lines',row_start:2,row_end:null},{...h.row(),program_id:'A',name:'Alpha',flow:'Setup',file:ref('Alpha.sas'),mode:'section',sections:['Cases']}]}];
  setRestored(doc);await upload($('stream-import'),'mixed.json');await settle(()=>$('stream-ready-controls').hidden===false);
  assert.equal(rows().length,2);assert.ok(rows()[0].querySelector('[data-unit-section="Setup"]:checked'));
  const restored=await exportDoc();assert.equal(restored.rows[0].code,doc.rows[0].code);assert.deepEqual(restored.rows[1].programs.map(p=>p.program_id),['B','A']);assert.equal(restored.rows[1].programs[0].row_end,null);assert.deepEqual(restored.rows[1].programs[1].sections,['Cases']);
});

test('polling preserves field focus and read-only platforms cannot enable SAS execution',async t=>{
  const {w,$,start,addFile,rows,snapshot,change}=harness(t);await start();await addFile('extract.sas');change(rows()[0].querySelector('[data-unit-field="mode"]'),'lines');const field=rows()[0].querySelector('[data-unit-field="row_start"]');field.value='20';field.focus();snapshot.windows=false;w.PySASStream.update(snapshot,'stream');assert.equal(w.document.activeElement,field);assert.equal(field.value,'20');assert.equal($('stream-run').disabled,true);
});

test('operation errors stay beside the actions and upload failures stay on their card',async t=>{
  const {$,start,addFile,add,rows,setFailure,upload}=harness(t);await start();await addFile('extract.sas');setFailure('Output is unavailable.');$('stream-source').click();await settle(()=>$('stream-status').textContent.includes('unavailable'));assert.equal($('error').textContent,'');const element=add();await upload(element.querySelector('[data-stream-upload]'),'other.sas');await settle(()=>rows()[1].querySelector('.stream-card-status').textContent.includes('unavailable'));assert.equal($('stream-ready-controls').hidden,true);
});

test('names and section suggestions are escaped; stale exports never advertise the old draft',async t=>{
  const {$,start,addFile,rows,sourceInfo,input,setDefer}=harness(t);sourceInfo.set('safe.sas',{name:'<img src=x>.sas',sections:['<script>bad</script>']});await start();await addFile('safe.sas');assert.equal(rows()[0].querySelector('img'),null);assert.equal(rows()[0].querySelector('script'),null);
  let finish;setDefer('/api/stream-source',()=>new Promise(resolve=>{finish=()=>resolve({path:'old.sas'});}));$('stream-source').click();input('stream-name','Changed');finish();await settle(()=>$('stream-source').disabled===false);assert.equal($('stream-artifacts').innerHTML,'');assert.match($('stream-status').textContent,/editor changed/);
});

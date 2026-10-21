// Actual Run stream markup/events with local HTTP substitutes; no live browser/SAS.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const h=require('../ui/stream.js');
const root=path.join(__dirname,'..');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(check=()=>true){for(let i=0;i<30;i++){await turn();if(check())return;}assert.fail('Stream UI did not settle');}

function harness(t){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/index.html'),'utf8'),{url:'http://localhost/#stream',runScripts:'outside-only'});
  t.after(()=>dom.window.close());const w=dom.window,$=id=>w.document.getElementById(id),calls=[],uploads=[],inspected=[];
  const snapshot={token:'csrf',windows:true,openpyxl:true,files:['connection.egp'],commands:[]};
  let fail='',restored=null,deferred=null;
  const ref=(name)=>({path:'tasks/stream-sources/'+name,name,sha256:'a'.repeat(64),lines:50,sections:['Realised','Cases']});
  w.XMLHttpRequest=class{
    constructor(){this.upload={};this.status=200;}
    open(method,url){this.url=url;}
    setRequestHeader(name,value){assert.equal(name,'X-PySAS-Token');assert.equal(value,'csrf');}
    send(file){uploads.push({url:this.url,file});setImmediate(()=>{
      if(fail){this.status=400;this.responseText=JSON.stringify({error:fail});}
      else this.responseText=JSON.stringify(this.url==='/api/stream-import'?{stream:restored}:ref(file.name));
      this.onload();
    });}
  };
  w.PySASGraphHost={request:async(url,data)=>{
    calls.push({url,data:structuredClone(data)});if(deferred){const callback=deferred;deferred=null;return callback(url,data);}if(fail)throw Error(fail);
    if(url==='/api/stream-estimate')return {seconds:60,unknown:1,basis:'Partial history'};
    if(url==='/api/stream-run'){snapshot.commands=[{id:'stream1',action:'stream',name:data.stream.name,status:'RUNNING',tasks:{}}];return {id:'stream1'};}
    if(url==='/api/stream-file')return ref('connection.egp');
    return {path:'tasks/.workbench/artifacts/example'+(url.endsWith('source')?'.sas':'.json')};
  },refresh:async()=>w.PySASStream.update(snapshot,'stream'),inspect:async id=>inspected.push(id),badge:s=>s,timer:()=>'<span class="elapsed">00:00:01</span>',expectedText:e=>e.seconds==null?'Unknown duration':e.seconds+'s'+(e.unknown?'+':''),fileActions:({path},label)=>`<a download href="/api/download?path=${path}">Download ${label}</a><button data-copy-target='{"path":"${path}"}'>Copy file</button>`};
  w.eval(fs.readFileSync(path.join(root,'ui/stream.js'),'utf8'));w.PySASStream.update(snapshot,'stream');
  const change=(element,value)=>{if(typeof element==='string')element=$(element);element.value=value;element.dispatchEvent(new w.Event('change',{bubbles:true}));};
  const upload=async(input,name)=>{Object.defineProperty(input,'files',{configurable:true,value:[new w.File(['example'],name)]});input.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>$('stream-source').disabled===false);};
  const rows=()=>[...$('stream-rows').querySelectorAll('[data-stream-row]')];
  return {w,$,calls,uploads,inspected,snapshot,rows,change,upload,setFailure:v=>fail=v,setRestored:v=>restored=v,setDefer:v=>deferred=v};
}

test('row reordering and deletion preserve source selections and do not mutate the previous document',()=>{
  const doc=h.empty(),first=doc.rows[0];first.mode='lines';first.row_start=2;first.row_end=8;doc.rows.push({...h.row(),section:'Cases',mode:'section'});
  const moved=h.move(doc,first.id,1);assert.equal(moved.rows[1].row_start,2);assert.equal(moved.rows[0].section,'Cases');assert.equal(doc.rows[0].id,first.id);
  assert.equal(h.remove(moved,first.id).rows.length,1);assert.equal(h.scope(moved.rows[1]),'Lines 2–8');assert.equal(h.scope({...first,row_start:null,row_end:null}),'Lines 1–end');
});

test('browser uploads, row scope edits, moves and deletes produce the ordered server payload',async t=>{
  const {w,$,rows,upload,change,calls,uploads}=harness(t);
  await upload($('stream-egp-upload'),'connection.egp');
  await upload(rows()[0].querySelector('[data-stream-upload]'),'_cases.sas');
  change(rows()[0].querySelector('[data-stream-field="mode"]'),'lines');
  change(rows()[0].querySelector('[data-stream-field="row_end"]'),'8');
  $('stream-add').click();await upload(rows()[1].querySelector('[data-stream-upload]'),'extract.sas');
  change(rows()[1].querySelector('[data-stream-field="mode"]'),'section');change(rows()[1].querySelector('[data-stream-field="section"]'),'Realised');
  rows()[1].querySelector('[data-stream-action="up"]').click();
  $('stream-estimate').click();await settle(()=>calls.length>0);
  const doc=calls.find(c=>c.url==='/api/stream-estimate').data.stream;
  assert.equal(doc.rows[0].file.name,'extract.sas');assert.equal(doc.rows[0].section,'Realised');assert.equal(doc.rows[1].row_start,null);assert.equal(doc.rows[1].row_end,8);
  assert.equal(doc.egp.name,'connection.egp');assert.equal(uploads.length,3);assert.match($('stream-estimate-result').textContent,/60s\+/);
  rows()[0].querySelector('[data-stream-action="delete"]').click();assert.equal(rows().length,1);assert.match(rows()[0].textContent,/_cases.sas/);
  assert.equal(rows()[0].querySelector('[data-stream-field="row_end"]').value,'8');
});

test('scope changes show only their own inputs and whole-file choices preserve inactive selections',t=>{
  const {rows,change,calls,$}=harness(t);const element=rows()[0];
  assert.equal(element.querySelector('.stream-bounds').hidden,true);assert.equal(element.querySelector('.stream-section').hidden,true);
  change(element.querySelector('[data-stream-field="mode"]'),'lines');change(element.querySelector('[data-stream-field="row_start"]'),'20');
  assert.equal(element.querySelector('.stream-bounds').hidden,false);
  change(element.querySelector('[data-stream-field="mode"]'),'section');change(element.querySelector('[data-stream-field="section"]'),'Cases');
  assert.equal(element.querySelector('.stream-section').hidden,false);assert.equal(element.querySelector('.stream-bounds').hidden,true);
  change(element.querySelector('[data-stream-field="mode"]'),'whole');assert.equal(element.querySelector('[data-stream-field="row_start"]').value,'20');
});

test('Get source and Export JSON expose the shared Download and actual-file Copy controls',async t=>{
  const {w,$,rows,upload,calls}=harness(t);await upload(rows()[0].querySelector('[data-stream-upload]'),'extract.sas');
  $('stream-source').click();await settle(()=>$('stream-artifacts').querySelector('a'));
  assert.match($('stream-artifacts').textContent,/Download SAS source/);assert.ok($('stream-artifacts').querySelector('[data-copy-target]'));
  $('stream-export').click();await settle(()=>calls.some(c=>c.url==='/api/stream-export'));
  assert.match($('stream-artifacts').textContent,/Download stream JSON/);
  $('stream-name').value='Changed';$('stream-name').dispatchEvent(new w.Event('input'));
  assert.equal($('stream-artifacts').innerHTML,'');
});

test('Run submits every output choice and opens the normal inspector',async t=>{
  const {w,$,rows,upload,calls,inspected}=harness(t);await upload($('stream-egp-upload'),'connection.egp');await upload(rows()[0].querySelector('[data-stream-upload]'),'extract.sas');
  $('stream-html').checked=false;$('stream-html').dispatchEvent(new w.Event('change'));
  $('stream-tables').checked=true;$('stream-tables').dispatchEvent(new w.Event('change'));assert.equal($('stream-consolidate').disabled,false);
  $('stream-consolidate').checked=true;$('stream-consolidate').dispatchEvent(new w.Event('change'));
  $('stream-run').click();await settle(()=>inspected.length>0);
  const doc=calls.find(c=>c.url==='/api/stream-run').data.stream;
  assert.equal(doc.export_html,false);assert.equal(doc.export_tables,true);assert.equal(doc.consolidate_tables,true);assert.deepEqual(inspected,['stream1']);
  assert.equal($('stream-execution').hidden,false);
});

test('Restore JSON replaces the editor atomically and keeps every selection and blank bound',async t=>{
  const {w,$,rows,upload,change,calls,setRestored}=harness(t);
  const restored=h.empty();restored.name='Restored cases';restored.rows=[{...h.row(),file:{path:'saved.sas',name:'saved.sas',sha256:'a'.repeat(64)},mode:'lines',row_start:null,row_end:22,section:'Saved inactive section'}];restored.export_tables=true;restored.consolidate_tables=true;
  setRestored(restored);await upload($('stream-import'),'stream.json');
  assert.equal($('stream-name').value,'Restored cases');assert.equal(rows().length,1);assert.equal(rows()[0].querySelector('[data-stream-field="row_end"]').value,'22');assert.equal($('stream-consolidate').checked,true);
  change(rows()[0].querySelector('[data-stream-field="mode"]'),'section');assert.equal(rows()[0].querySelector('[data-stream-field="section"]').value,'Saved inactive section');
  $('stream-export').click();await settle(()=>calls.length>0);assert.equal(calls.at(-1).data.stream.rows[0].row_start,null);
});

test('upload and validation errors stay next to the stream and do not discard the draft',async t=>{
  const {$,rows,upload,calls,setFailure}=harness(t);setFailure('The section is missing.');
  $('stream-source').click();await settle(()=>$('stream-status').textContent.includes('missing'));
  assert.equal($('error').textContent,'');assert.equal($('stream-status').classList.contains('inline-error'),true);
  await upload(rows()[0].querySelector('[data-stream-upload]'),'extract.sas');assert.match(rows()[0].querySelector('.stream-row-status').textContent,/section is missing/);
  assert.equal(rows().length,1);assert.equal($('stream-source').disabled,false);
});

test('polling does not rebuild rows, lose focus, overwrite edits or enable execution on macOS',t=>{
  const {w,$,rows,snapshot,change}=harness(t);change(rows()[0].querySelector('[data-stream-field="mode"]'),'section');const field=rows()[0].querySelector('[data-stream-field="section"]');field.value='In progress';field.focus();
  snapshot.windows=false;w.PySASStream.update(snapshot,'stream');
  assert.equal(w.document.activeElement,field);assert.equal(field.value,'In progress');assert.equal($('stream-run').disabled,true);
});

test('SAS names and section suggestions are escaped when rendering upload metadata',async t=>{
  const {$,rows,setRestored,upload}=harness(t);const doc=h.empty();doc.rows[0].file={path:'x.sas',name:'<img src=x>.sas',sha256:'a'.repeat(64),sections:['<script>bad</script>']};
  setRestored(doc);await upload($('stream-import'),'stream.json');assert.equal(rows()[0].querySelector('img'),null);assert.equal(rows()[0].querySelector('script'),null);assert.match(rows()[0].textContent,/<img src=x>.sas/);
});

test('moving the last row keeps keyboard focus on an available action',async t=>{
  const {w,$,rows}=harness(t);$('stream-add').click();const id=rows()[1].dataset.streamRow;
  rows()[1].querySelector('[data-stream-action="up"]').click();
  assert.equal(w.document.activeElement.closest('[data-stream-row]').dataset.streamRow,id);
  rows()[0].querySelector('[data-stream-action="down"]').click();
  assert.equal(w.document.activeElement.closest('[data-stream-row]').dataset.streamRow,id);
});

test('a late source response cannot advertise a download for different editor choices',async t=>{
  const {w,$,setDefer}=harness(t);let release;setDefer(()=>new Promise(resolve=>{release=()=>resolve({path:'old.sas'});}));
  $('stream-source').click();$('stream-name').value='New choice';$('stream-name').dispatchEvent(new w.Event('input'));
  release();await settle(()=>$('stream-source').disabled===false);
  assert.equal($('stream-artifacts').innerHTML,'');assert.match($('stream-status').textContent,/editor changed/);
});

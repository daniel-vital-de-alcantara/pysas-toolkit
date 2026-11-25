const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const h=require('../ui/graph.js');
const root=path.join(__dirname,'..');
const clone=value=>JSON.parse(JSON.stringify(value));
const pause=ms=>new Promise(done=>setTimeout(done,ms));
async function settle(check){for(let i=0;i<180;i++){await pause(5);if(check())return;}assert.fail('Graph did not settle');}
const node=(id,x=0,y=0)=>({...h.task(id,x,y),id});
function graph(nodes=[],edges=[],setup=[]){return {...h.empty(),id:'example',nodes,edges,setup};}

test('task graph permits incomplete drafts but rejects cycles, duplicate and setup links',()=>{
  const g=graph([node('A'),node('B')],[],[node('S')]);assert.equal(h.validate(g).nodes.length,2);assert.equal(h.validate(graph()).nodes.length,0);
  const linked=h.link(g,'A','B');assert.deepEqual(h.order(linked),['A','B']);assert.equal(g.edges.length,0);
  for(const [from,to] of [['B','A'],['A','B'],['A','A'],['S','A'],['Missing','B']])assert.throws(()=>h.link(linked,from,to));
});
test('remove, duplicate and layout preserve source definitions and unrelated dependencies',()=>{
  const g=graph(['A','B','C','D'].map(key=>node(key)),[{from:'A',to:'B'},{from:'B',to:'C'},{from:'A',to:'D'}],[node('S')]);
  g.nodes[1].rows[0].source_kind='inline';g.nodes[1].rows[0].code='%let ids=12;';const copy=h.duplicate(g,'B');assert.equal(copy.nodes.length,5);assert.equal(copy.nodes[4].rows[0].code,'%let ids=12;');assert.notEqual(copy.nodes[4].rows[0].id,g.nodes[1].rows[0].id);assert.equal(copy.edges.length,3);
  const removed=h.remove(g,'B');assert.deepEqual(removed.edges,[{from:'A',to:'D'}]);const layout=h.arrange(g),map=Object.fromEntries(layout.nodes.map(n=>[n.id,n]));assert.ok(map.A.x<map.B.x&&map.B.x<map.C.x);assert.notEqual(map.B.y,map.D.y);assert.equal(g.nodes[0].x,0);
});
test('camera fit, directional navigation and history retain layout and sources',()=>{
  const g=graph([node('A',100,100),node('B',500,100),node('C',100,400)]);assert.equal(h.nearest(g.nodes,'A','ArrowRight'),'B');assert.equal(h.nearest(g.nodes,'A','ArrowDown'),'C');assert.equal(h.nearest(g.nodes,'A','ArrowLeft'),'A');
  const fit=h.fitView(g.nodes,900,450);assert.ok(fit.zoom>=.25&&fit.zoom<=1.2);const history=new h.History();history.push(g);const after=h.duplicate(g,'A');assert.equal(history.undo(after).nodes.length,3);assert.equal(history.redo(g).nodes.length,4);assert.equal(g.nodes.length,3);
});

function harness(t,{automatic=true}={}){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/index.html'),'utf8'),{url:'http://localhost/#graph',runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());
  const w=dom.window,$=id=>w.document.getElementById(id),requests=[],uploads=[],sourceInfo=new Map(),snapshot={token:'csrf',windows:false,files:['connection.egp'],commands:[],shared_work:{enabled:false,path:'/server/shared',libref:'VDI'}};
  let imported=null,jobs=null,xhrHandler=null,failure='',deferred=new Map();
  const ref=name=>({path:'tasks/stream-sources/'+name,name,sha256:'a'.repeat(64),lines:20,has_code:true,sections:['Extract','Summary'],...sourceInfo.get(name)});
  const catalog={programs:[{id:'A',name:'Libraries',flow:'Setup',member:'A/code.sas'},{id:'B',name:'Extract',flow:'Tasks',member:'B/code.sas'},{id:'External',name:'Linked source',flow:'Tasks',member:null}],warnings:[]};
  const ready=result=>({id:'job',status:'READY',result});
  w.confirm=()=>true;
  w.XMLHttpRequest=class{constructor(){this.upload={};this.status=200;}open(method,url){this.url=url;}setRequestHeader(key,value){assert.equal(key,'X-PySAS-Token');assert.equal(value,'csrf');}send(file){uploads.push({url:this.url,file});setImmediate(()=>{const finish=result=>{this.responseText=JSON.stringify(result);this.onload();};this.upload.onprogress?.({lengthComputable:true,loaded:1,total:1});if(xhrHandler)return xhrHandler(this.url,file,finish);finish(this.url==='/api/task-graph-import'?{graph:clone(imported)}:ref(file.name));});}};
  const host={request:async(url,data)=>{requests.push({url,data:data?clone(data):null});if(deferred.has(url)){const fn=deferred.get(url);deferred.delete(url);return fn(data);}if(failure)throw Error(failure);
      if(url==='/api/task-graphs')return data?{graph:data.graph,revision:'rev'+requests.length,path:'settings/graphs/'+data.graph.id+'.json'}:{graphs:[]};
      if(url.startsWith('/api/task-graphs?id='))return {graph:clone(imported),revision:'saved-rev'};
      if(url==='/api/stream-file')return {...ref(data.path.split('/').at(-1)),...(data.name?{name:data.name}:{}),origin_path:data.path};
      if(url==='/api/task-graph-refresh')return {graph:data.graph};
      if(url==='/api/submit')return {id:'graph-run-1'};
      if(url==='/api/stop')return {ok:true};
      if(url==='/api/task-graph-export')return {path:'tasks/.workbench/artifacts/plan.graph.json'};
      if(url==='/api/task-graph-check')return {nodes:data.graph.nodes.length,setup:data.graph.setup.length,edges:data.graph.edges.length};
      if(url==='/api/stream-job'){const custom=jobs?.(data);if(custom)return custom;if(data.kind==='connection')return ready({egp:automatic||data.path?ref(data.path?.split('/').at(-1)||'connection.egp'):null,catalog});if(data.kind==='project')return ready({project:data.project,catalog});return ready({file:ref(data.program_id+'.sas'),program:catalog.programs.find(p=>p.id===data.program_id)});}
      if(url==='/api/stream-analyze')return {lines:data.code.split('\n').length,has_code:!!data.code.trim(),sections:[...data.code.matchAll(/section_start: (.+?);/g)].map(match=>match[1]),section_issues:[]};
      throw Error('Unexpected endpoint: '+url);
    },startRun:async(data,options)=>{requests.push({url:'/api/submit',data:clone(data),options});host.navigate('overview');return {id:'graph-run-1'};},inspect:async id=>requests.push({url:'/inspect',id}),fileActions:({path},label)=>`<a download href="/api/download?path=${path}">Download ${label}</a><button data-copy-target='{"path":"${path}"}'>Copy file</button>`,navigate:page=>{w.document.body.classList.toggle('graph-page',page==='graph');$('page-overview').hidden=page!=='overview';$('page-graph').hidden=page!=='graph';},badge:()=>'',timer:()=>'',refresh:async()=>{},expectedText:()=>''};
  w.PySASGraphHost=host;
  for(const filename of ['stream.js','source-cards.js','graph-layout.js','graph.js'])w.eval(fs.readFileSync(path.join(root,'ui',filename),'utf8'));
  $('page-overview').hidden=true;$('page-graph').hidden=false;w.document.body.classList.add('graph-page');w.PySASGraph.update(snapshot,'graph');
  $('graph-canvas').getBoundingClientRect=()=>({left:0,top:0,width:1100,height:800});$('graph-canvas').setPointerCapture=()=>{};$('graph-canvas').releasePointerCapture=()=>{};
  const input=(element,value)=>{if(typeof element==='string')element=$(element);element.value=value;element.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const change=(element,value)=>{if(typeof element==='string')element=$(element);element.value=value;element.dispatchEvent(new w.Event('change',{bubbles:true}));};
  const nodes=()=>[...$('graph-nodes').children],rows=()=>[...$('graph-task-sources').querySelectorAll('[data-source-row]')];
  const upload=async(element,name)=>{Object.defineProperty(element,'files',{configurable:true,value:[new w.File(['test'],name)]});element.dispatchEvent(new w.Event('change',{bubbles:true}));await pause(15);};
  const start=()=>settle(()=>requests.some(r=>r.url==='/api/stream-job')&&$('graph-connection-summary').textContent!=='Reading project…');
  const add=name=>{$('graph-add-task').click();if(name)input('graph-task-name',name);return nodes().at(-1).dataset.graphNode;};
  const inline=async(code='%let ids=12;')=>{change(rows()[0].querySelector('[data-source-field="source_kind"]'),'inline');input(rows()[0].querySelector('textarea'),code);await settle(()=>!$('graph-save').disabled);};
  const save=async()=>{const prior=requests.filter(r=>r.url==='/api/task-graphs'&&r.data).length;$('graph-save').click();await settle(()=>requests.filter(r=>r.url==='/api/task-graphs'&&r.data).length>prior&&!$('graph-save').disabled);return requests.findLast(r=>r.url==='/api/task-graphs'&&r.data).data.graph;};
  const key=(element,key,extras={})=>element.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key,...extras}));
  const pointer=(type,target,x,y,extras={})=>{const event=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperties(event,Object.fromEntries(Object.entries({pointerId:1,button:0,clientX:x,clientY:y,...extras}).map(([name,value])=>[name,{value}])));target.dispatchEvent(event);};
  return {w,$,snapshot,ref,catalog,ready,requests,uploads,start,add,inline,save,rows,nodes,input,change,upload,key,pointer,sourceInfo,setImported:value=>imported=value,setJobs:value=>jobs=value,setXHR:value=>xhrHandler=value,setFailure:value=>failure=value,setDefer:(url,fn)=>deferred.set(url,fn)};
}

test('canvas preserves editing on non-Windows and never starts a run automatically',async t=>{
  const {$,requests,start,add,rows,nodes}=harness(t);await start();assert.equal($('graph-empty').hidden,false);assert.equal($('graph-run').disabled,true);add('Extract cases');assert.equal(nodes().length,1);assert.equal(rows().length,1);assert.equal($('graph-drawer').hidden,false);assert.equal($('graph-task-context').textContent.includes('one task'),true);assert.equal(requests.some(r=>r.url.includes('-run')),false);assert.ok(nodes()[0].querySelector('[data-port="out"]'));assert.equal($('graph-empty').hidden,true);
});
test('task definitions mix inline code, files and selected sections and survive save',async t=>{
  const {w,$,start,add,inline,rows,upload,change,save}=harness(t);await start();add('Cases');await inline('%let ids=12,24;');$('graph-task-sources').querySelector('.source-add').click();await upload(rows()[1].querySelector('[data-source-file]'),'extract.sas');await settle(()=>!$('graph-save').disabled);change(rows()[1].querySelector('[data-unit-field="mode"]'),'section');
  for(const name of ['Summary','Extract']){const box=rows()[1].querySelector(`[data-unit-section="${name}"]`);box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));}
  const saved=await save();assert.equal(saved.nodes[0].rows[0].code,'%let ids=12,24;');assert.deepEqual(saved.nodes[0].rows[1].sections,['Extract','Summary']);assert.equal('analysis' in saved.nodes[0].rows[0],false);assert.equal('sections' in saved.nodes[0].rows[1].file,false);
});
test('named sections and ranges show incomplete status and instructions without disabling graph drafts',async t=>{
  const {$,start,add,rows,upload,change,sourceInfo,save,nodes}=harness(t);await start();add();sourceInfo.set('plain.sas',{sections:[]});await upload(rows()[0].querySelector('[data-source-file]'),'plain.sas');change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');assert.match(rows()[0].textContent,/No complete named sections/);assert.match(rows()[0].textContent,/section_start: My section/);assert.match(nodes()[0].textContent,/Needs definition/);change(rows()[0].querySelector('[data-unit-field="mode"]'),'lines');assert.match(rows()[0].querySelector('.source-status').textContent,/first or last line/);assert.equal((await save()).nodes[0].rows[0].mode,'lines');
});
test('click linking, cycle rejection and dependency removal work on real canvas controls',async t=>{
  const {$,start,add,nodes,save}=harness(t);await start();const a=add('A'),b=add('B');$('graph-close-drawer').click();nodes()[0].querySelector('[data-graph-focus]').click();$('graph-connect').click();nodes()[1].querySelector('[data-graph-focus]').click();assert.deepEqual((await save()).edges,[{from:a,to:b}]);nodes()[1].querySelector('[data-port="out"]').click();nodes()[0].querySelector('[data-port="in"]').click();assert.match($('graph-status').textContent,/Circular/);assert.equal((await save()).edges.length,1);$('graph-edges').querySelector('[data-graph-edge]').dispatchEvent(new ($('graph-canvas').ownerDocument.defaultView.MouseEvent)('click',{bubbles:true}));$('graph-remove-edge').click();assert.equal((await save()).edges.length,0);
});
test('pointer dragging moves nodes in canvas coordinates and port dragging creates a dependency',async t=>{
  const {w,$,start,add,nodes,save,pointer}=harness(t);await start();const a=add('A'),b=add('B');$('graph-close-drawer').click();let before=await save(),n=before.nodes[0];pointer('pointerdown',nodes()[0].querySelector('[data-graph-focus]'),100,100);pointer('pointermove',$('graph-canvas'),180,145);pointer('pointerup',$('graph-canvas'),180,145);$('graph-canvas').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));let moved=await save();assert.equal(moved.nodes[0].x,n.x+80);assert.equal(moved.nodes[0].y,n.y+45);
  pointer('pointerdown',nodes()[0].querySelector('[data-port="out"]'),100,100);pointer('pointermove',$('graph-canvas'),350,200);w.document.elementFromPoint=()=>nodes()[1].querySelector('[data-port="in"]');pointer('pointerup',$('graph-canvas'),350,200);$('graph-canvas').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));assert.deepEqual((await save()).edges,[{from:a,to:b}]);
});
test('keyboard browsing, linking, moving and undo retain the dependency plan',async t=>{
  const {$,start,add,nodes,save,key}=harness(t);await start();const a=add('A'),b=add('B');$('graph-close-drawer').click();$('graph-arrange').click();nodes()[0].querySelector('[data-graph-focus]').click();$('graph-connect').click();key($('graph-canvas'),'ArrowDown');key($('graph-canvas'),'Enter');let saved=await save();assert.deepEqual(saved.edges,[{from:a,to:b}]);const oldX=saved.nodes[1].x;key($('graph-canvas'),'ArrowRight',{ctrlKey:true});assert.equal((await save()).nodes[1].x,oldX+10);$('graph-undo').click();saved=await save();assert.equal(saved.nodes[1].x,oldX);assert.equal(saved.edges.length,1);$('graph-redo').click();assert.equal((await save()).nodes[1].x,oldX+10);
});
test('shared setup cards reorder separately and do not acquire dependency arrows',async t=>{
  const {$,start,input,inline,save,w}=harness(t);await start();for(const name of ['Libraries','Parameters']){$('graph-add-setup').click();input('graph-task-name',name);await inline('%let '+name+'=1;');}assert.equal($('graph-dependencies').hidden,true);$('graph-setup-earlier').click();assert.deepEqual((await save()).setup.map(n=>n.name),['Parameters','Libraries']);
  const items=()=>[...$('graph-setup-list').querySelectorAll('[data-graph-setup]')];function drag(type,target,x){const event=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperties(event,{clientX:{value:x},dataTransfer:{value:{setData(){}}}});target.dispatchEvent(event);}items()[1].getBoundingClientRect=()=>({left:0,width:100});drag('dragstart',items()[0],0);drag('dragover',items()[1],90);drag('drop',items()[1],90);const saved=await save();assert.deepEqual(saved.setup.map(n=>n.name),['Libraries','Parameters']);assert.deepEqual(saved.edges,[]);
});
test('EGP task sources use process flows, ordered selections and the same background reader',async t=>{
  const {w,start,add,rows,change,save}=harness(t);await start();add();change(rows()[0].querySelector('[data-source-field="source_kind"]'),'egp');await settle(()=>rows()[0].querySelector('[data-egp-program="A"]'));assert.equal(rows()[0].querySelector('[data-egp-program="External"]').disabled,true);
  for(const key of ['B','A']){const box=rows()[0].querySelector(`[data-egp-program="${key}"]`);box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>!rows()[0].querySelector('[aria-busy="true"]')&&rows()[0].querySelectorAll('.source-program [data-unit-field="mode"]').length===(key==='B'?1:2));}
  assert.deepEqual((await save()).nodes[0].rows[0].programs.map(p=>p.program_id),['B','A']);rows()[0].querySelectorAll('.source-program')[1].querySelector('[data-source-action="program-up"]').click();assert.deepEqual((await save()).nodes[0].rows[0].programs.map(p=>p.program_id),['A','B']);
});
test('background extraction survives selecting another task and cannot resurrect a deleted task',async t=>{
  const {w,$,start,add,rows,change,nodes,setJobs,ready,ref,save}=harness(t);let finish;await start();setJobs(data=>data.kind==='program'?new Promise(resolve=>{finish=()=>resolve(ready({file:ref('extracted.sas')}));}):null);const first=add('First');change(rows()[0].querySelector('[data-source-field="source_kind"]'),'egp');await settle(()=>rows()[0].querySelector('[data-egp-program="A"]'));let box=rows()[0].querySelector('[data-egp-program="A"]');box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>finish);add('Second');assert.equal(nodes().length,2);finish();await settle(()=>!$('graph-save').disabled);assert.equal((await save()).nodes.find(n=>n.id===first).rows[0].programs[0].file.name,'extracted.sas');
  nodes()[0].querySelector('[data-edit-task]').click();rows()[0].querySelector('[data-source-action="program-remove"]').click();box=rows()[0].querySelector('[data-egp-program="A"]');box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));await pause(10);$('graph-remove-node').click();finish();await pause(20);assert.equal((await save()).nodes.length,1);
});
test('portable import restores viewport, source choices, setup and links; export offers file Copy',async t=>{
  const {$,start,upload,setImported,ref,save,requests}=harness(t);await start();const g=graph([node('A',-80,95),node('B',400,130)],[{from:'A',to:'B'}],[node('Setup')]);g.viewport={x:-120,y:210,zoom:.75};g.egp=ref('connection.egp');g.nodes[0].rows[0].file=ref('source.sas');g.nodes[0].rows[0].mode='lines';g.nodes[0].rows[0].row_end=7;g.nodes[1].export_tables=true;setImported(g);await upload($('graph-import'),'graph.json');await settle(()=>$('graph-nodes').children.length===2);const saved=await save();assert.deepEqual(saved.viewport,g.viewport);assert.deepEqual(saved.edges,g.edges);assert.equal(saved.nodes[0].rows[0].row_end,7);assert.equal(saved.nodes[1].export_tables,true);$('graph-export').click();await settle(()=>$('graph-saved-actions').querySelector('[data-copy-target]'));assert.equal(requests.filter(r=>r.url==='/api/task-graph-export').length,1);
});
test('panning and zooming preserve the world point and are remembered in JSON',async t=>{
  const {w,$,start,add,save,pointer}=harness(t);await start();add();$('graph-close-drawer').click();const initial=(await save()).viewport;pointer('pointerdown',$('graph-canvas'),500,350);pointer('pointermove',$('graph-canvas'),540,390);pointer('pointerup',$('graph-canvas'),540,390);$('graph-canvas').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));let current=await save();assert.equal(current.viewport.x,initial.x+40);assert.equal(current.viewport.y,initial.y+40);const before=current.viewport;const wheel=new w.WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-50,clientX:400,clientY:300});$('graph-canvas').dispatchEvent(wheel);current=await save();assert.ok(current.viewport.zoom>before.zoom);assert.ok(Math.abs((400-before.x)/before.zoom-(400-current.viewport.x)/current.viewport.zoom)<.0001);
});
test('task duplication and deletion keep unrelated source cards and links',async t=>{
  const {$,start,add,inline,save,nodes}=harness(t);await start();const key=add('Original');await inline();$('graph-duplicate-task').click();let saved=await save();assert.equal(saved.nodes.length,2);assert.equal(saved.nodes[1].rows[0].code,'%let ids=12;');assert.notEqual(saved.nodes[0].rows[0].id,saved.nodes[1].rows[0].id);$('graph-remove-node').click();saved=await save();assert.equal(saved.nodes.length,1);assert.equal(saved.nodes[0].id,key);
});
test('selecting a different canvas task switches the editing drawer to that task',async t=>{
  const {$,start,add,inline,nodes,input,rows,save}=harness(t);await start();const first=add('First');await inline('%let first=1;');const second=add('Second');await inline('%let second=2;');
  nodes()[0].querySelector('[data-graph-focus]').click();assert.equal($('graph-task-name').value,'First');assert.equal(rows()[0].querySelector('textarea').value,'%let first=1;');
  input('graph-task-name','First updated');input(rows()[0].querySelector('textarea'),'%let first=3;');await settle(()=>!$('graph-save').disabled);
  const saved=await save();assert.equal(saved.nodes.find(n=>n.id===first).name,'First updated');assert.equal(saved.nodes.find(n=>n.id===first).rows[0].code,'%let first=3;');assert.equal(saved.nodes.find(n=>n.id===second).rows[0].code,'%let second=2;');
});
test('pending restore protects edits made during upload and source errors stay local',async t=>{
  const {$,start,add,input,upload,setXHR,save,setFailure}=harness(t);await start();add('Current');let finish;setXHR((url,file,done)=>{finish=()=>done({graph:graph([node('Imported')])});});await upload($('graph-import'),'graph.json');input('graph-task-name','Latest name');finish();await settle(()=>$('graph-use-import').hidden===false);assert.equal((await save()).nodes[0].name,'Latest name');$('graph-use-import').click();assert.equal((await save()).nodes[0].name,'Imported');setFailure('Cannot save this folder');$('graph-save').click();await settle(()=>$('graph-file-status').textContent.includes('Cannot save'));assert.equal($('error').textContent,'');
});
test('late portable export cannot attach an old plan to a new graph',async t=>{
  const {$,start,add,setDefer}=harness(t);await start();add('Old task');let finish;
  setDefer('/api/task-graph-export',()=>new Promise(resolve=>{finish=()=>resolve({path:'old-plan.graph.json'});}));$('graph-export').click();await settle(()=>finish);
  $('graph-new').click();await settle(()=>$('graph-save').disabled===false);assert.equal($('graph-nodes').children.length,0);finish();await pause(20);assert.equal($('graph-saved-actions').textContent,'');assert.equal($('graph-file-status').textContent.includes('Portable JSON ready'),false);
});
test('untrusted names are escaped and polling never takes the inline editor focus',async t=>{
  const {w,$,start,add,inline,nodes,rows,input,snapshot}=harness(t);await start();add('<img src=x onerror=alert(1)>');await inline();assert.equal(nodes()[0].querySelector('img'),null);assert.match(nodes()[0].textContent,/<img/);const editor=rows()[0].querySelector('textarea');editor.focus();editor.setSelectionRange(3,5);w.PySASGraph.update(snapshot,'graph');assert.equal(w.document.activeElement,editor);assert.equal(editor.selectionStart,3);input(editor,'%let ids=13;');await settle(()=>!$('graph-save').disabled);assert.equal(w.document.activeElement.tagName,'TEXTAREA');assert.equal(w.document.activeElement.value,'%let ids=13;');
});

test('Arrange reserves a lane for A→C around B, and routing avoids manually aligned cards',()=>{
  const triangle=graph(['A','B','C'].map(key=>node(key)),[{from:'A',to:'C'},{from:'A',to:'B'},{from:'B',to:'C'}]);
  const arranged=h.arrange(triangle),byId=Object.fromEntries(arranged.nodes.map(n=>[n.id,n])),geometry=require('../ui/graph-layout.js');
  assert.ok(byId.A.x<byId.B.x&&byId.B.x<byId.C.x);const link=geometry.route(byId.A,byId.C,arranged.nodes);
  const b={left:byId.B.x-12,right:byId.B.x+h.WIDTH+12,top:byId.B.y-12,bottom:byId.B.y+h.HEIGHT+12};
  assert.ok(link.points.slice(1).every((p,i)=>!geometry.intersects(link.points[i],p,b)));
  const straight=[node('A',0,0),node('B',374,0),node('C',748,0)],routed=geometry.route(straight[0],straight[2],straight);
  assert.equal(routed.routed,true);assert.match(routed.path,/Q/);const obstacle={left:362,right:650,top:-12,bottom:170};assert.ok(routed.points.slice(1).every((p,i)=>!geometry.intersects(routed.points[i],p,obstacle)));
  const large=h.arrange(graph(Array.from({length:200},(_,i)=>node('N'+i)),Array.from({length:199},(_,i)=>({from:'N'+i,to:'N'+(i+1)}))));assert.equal(h.validate(large).nodes.length,200);
});

test('alignment and distribution change selected positions without touching sources or edges',()=>{
  const g=graph([node('A',20,90),node('B',170,30),node('C',500,200),node('D',900,500)],[{from:'A',to:'C'}]);
  const left=h.align(g,['A','B','C'],'left');assert.deepEqual(left.nodes.slice(0,3).map(n=>n.x),[20,20,20]);assert.equal(left.nodes[3].x,900);assert.deepEqual(left.edges,g.edges);
  assert.equal(h.align(g,['A','B'],'right').nodes[0].x,170);assert.equal(h.align(g,['A','B'],'center').nodes[0].x,95);assert.equal(h.align(g,['A','B'],'top').nodes[0].y,30);assert.equal(h.align(g,['A','B'],'bottom').nodes[1].y,90);assert.equal(h.align(g,['A','B'],'middle').nodes[0].y,60);
  assert.deepEqual(h.align(g,['A','B','C'],'horizontal').nodes.slice(0,3).map(n=>n.x),[20,260,500]);assert.deepEqual(h.align(g,['A','B','C'],'vertical').nodes.slice(0,3).map(n=>n.y),[115,30,200]);assert.equal(g.nodes[1].x,170);
});

test('Shift selection supports repeated alignment, group dragging and one-step undo',async t=>{
  const {w,$,start,add,nodes,save,pointer}=harness(t);await start();add('A');add('B');add('C');$('graph-close-drawer').click();$('graph-arrange').click();
  nodes()[0].querySelector('[data-graph-focus]').click();nodes()[1].querySelector('[data-graph-focus]').dispatchEvent(new w.MouseEvent('click',{bubbles:true,shiftKey:true}));
  assert.equal($('graph-nodes').querySelectorAll('.selected').length,2);assert.match($('graph-selection-count').textContent,/2 selected/);
  $('graph-align-menu').querySelector('[data-graph-align="left"]').click();assert.equal($('graph-nodes').querySelectorAll('.selected').length,2);
  let before=await save();assert.equal(before.nodes[0].x,before.nodes[1].x);assert.equal($('graph-align-menu').querySelector('[data-graph-align="horizontal"]').disabled,true);
  pointer('pointerdown',nodes()[0].querySelector('[data-graph-focus]'),100,100);pointer('pointermove',$('graph-canvas'),150,130);pointer('pointerup',$('graph-canvas'),150,130);$('graph-canvas').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  let moved=await save();for(let i=0;i<2;i++){assert.equal(moved.nodes[i].x,Math.round(before.nodes[i].x+50/before.viewport.zoom));assert.equal(moved.nodes[i].y,Math.round(before.nodes[i].y+30/before.viewport.zoom));}assert.equal(moved.nodes[2].y,before.nodes[2].y);
  $('graph-undo').click();assert.deepEqual((await save()).nodes.map(n=>[n.x,n.y]),before.nodes.map(n=>[n.x,n.y]));
});

test('full graph run opens Overview with the graph definition and no inspector',async t=>{
  const {w,$,snapshot,start,add,inline,requests}=harness(t);await start();add('A');await inline();$('graph-close-drawer').click();snapshot.windows=true;w.PySASGraph.update(snapshot,'graph');assert.equal($('graph-run').disabled,false);assert.equal($('graph-run').hidden,false);
  $('graph-run').click();await settle(()=>requests.some(r=>r.url==='/api/submit'));const submitted=requests.find(r=>r.url==='/api/submit').data;assert.equal(submitted.action,'task-graph');assert.equal(submitted.graph.nodes.length,1);assert.equal(submitted.task_id,undefined);assert.equal($('page-overview').hidden,false);assert.equal(requests.some(r=>r.url==='/inspect'),false);
});

test('manual task can run while another card is incomplete, but full graph remains blocked',async t=>{
  const {w,$,snapshot,start,add,inline,nodes,requests}=harness(t);await start();const a=add('A');await inline();add('Incomplete B');nodes()[0].querySelector('[data-edit-task]').click();snapshot.windows=true;w.PySASGraph.update(snapshot,'graph');
  assert.equal($('graph-run').disabled,true);assert.equal($('graph-run-task').disabled,false);assert.match($('graph-run-task').parentElement.textContent,/Prerequisites are not submitted/);
  $('graph-run-task').click();await settle(()=>requests.some(r=>r.url==='/api/submit'));assert.equal(requests.find(r=>r.url==='/api/submit').data.task_id,a);
});

test('running node badges, global stop and latest inspector use the actual graph command',async t=>{
  const {w,$,snapshot,start,add,inline,save,nodes,requests}=harness(t);await start();const a=add('A');await inline();const model=await save();snapshot.windows=true;snapshot.commands=[{id:'running',action:'task-graph',graph_id:model.id,name:model.name,status:'RUNNING',started:1,tasks:{[a]:{key:a,name:'A',status:'RUNNING',started:1}}}];w.PySASGraph.update(snapshot,'graph');
  assert.equal($('graph-run').disabled,true);assert.equal($('graph-stop').hidden,false);assert.equal(nodes()[0].classList.contains('task-running'),true);$('graph-stop').click();await settle(()=>requests.some(r=>r.url==='/api/stop'));assert.equal(requests.find(r=>r.url==='/api/stop').data.id,'running');$('graph-inspect-run').click();assert.equal(requests.find(r=>r.url==='/inspect').id,'running');
});

test('restored file references without section metadata are scanned before they become ready',async t=>{
  const {$,start,upload,setImported,ref,rows,change,sourceInfo}=harness(t);await start();const g=graph([node('A')]);g.egp=ref('connection.egp');g.nodes[0].rows[0].file={path:'tasks/stream-sources/restored.sas',name:'restored.sas',sha256:'a'.repeat(64)};sourceInfo.set('restored.sas',{sections:['New section'],lines:4});setImported(g);
  await upload($('graph-import'),'graph.json');await settle(()=>$('graph-nodes').children.length===1);$('graph-nodes').querySelector('[data-edit-task]').click();await settle(()=>rows()[0].querySelector('.source-status').textContent.includes('Defined'));change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');assert.ok(rows()[0].querySelector('[data-unit-section="New section"]'));assert.match(rows()[0].textContent,/Refresh source/);
});

test('file refresh revalidates selected sections and a late result cannot replace a newer upload',async t=>{
  const {$,start,add,upload,rows,change,sourceInfo,setDefer,ref,save}=harness(t);await start();add();await upload(rows()[0].querySelector('[data-source-file]'),'old.sas');await settle(()=>!$('graph-save').disabled);change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');
  sourceInfo.set('old.sas',{sections:['Latest'],sha256:'b'.repeat(64)});rows()[0].querySelector('[data-source-action="refresh-source"]').click();await settle(()=>rows()[0].querySelector('[data-unit-section="Latest"]'));
  let finish;setDefer('/api/stream-file',()=>new Promise(resolve=>{finish=()=>resolve(ref('old.sas'));}));rows()[0].querySelector('[data-source-action="refresh-source"]').click();await settle(()=>finish);await upload(rows()[0].querySelector('[data-source-file]'),'new.sas');finish();await settle(()=>!$('graph-save').disabled);
  assert.equal((await save()).nodes[0].rows[0].file.name,'new.sas');assert.equal(rows()[0].querySelector('[data-unit-section="Latest"]'),null);
});

test('inline sections are detected after starting with an empty editor and use checked source order',async t=>{
  const {w,$,start,add,inline,rows,change,save}=harness(t);await start();add();await inline('* (please do not delete) section_start: First;\n%let ids=1;\n* (please do not delete) section_end: First;\n* (please do not delete) section_start: Second;\n%put &ids.;\n* (please do not delete) section_end: Second;');
  change(rows()[0].querySelector('[data-unit-field="mode"]'),'section');for(const name of ['Second','First']){const box=rows()[0].querySelector(`[data-unit-section="${name}"]`);assert.ok(box);box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));}
  assert.deepEqual((await save()).nodes[0].rows[0].sections,['First','Second']);
});

test('restored EGP program sections are selectable without a source_kind field on the program',async t=>{
  const {w,$,start,upload,setImported,ref,rows,change,save}=harness(t);await start();const g=graph([node('A')]);g.egp=ref('connection.egp');g.nodes[0].rows=[{...h.source(),id:'project',source_kind:'egp',project:ref('connection.egp'),programs:[{id:'program',program_id:'A',name:'Libraries',flow:'Setup',file:ref('embedded.sas'),mode:'whole',row_start:null,row_end:null,sections:[]}]}];setImported(g);
  await upload($('graph-import'),'graph.json');await settle(()=>$('graph-nodes').children.length===1);$('graph-nodes').querySelector('[data-edit-task]').click();await settle(()=>!$('graph-save').disabled);
  const program=rows()[0].querySelector('[data-source-unit="program"]');change(program.querySelector('[data-unit-field="mode"]'),'section');const box=rows()[0].querySelector('[data-source-unit="program"] [data-unit-section="Extract"]');assert.ok(box);box.checked=true;box.dispatchEvent(new w.Event('change',{bubbles:true}));assert.deepEqual((await save()).nodes[0].rows[0].programs[0].sections,['Extract']);
});

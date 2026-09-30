const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const nodes = new Map(), registered = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {textContent:'', innerHTML:'', value:'', hidden:false, className:'', dataset:{}, addEventListener(){}, querySelectorAll(){return []}, classList:{toggle(){}}, options:[]});
  return nodes.get(id);
}
const snapshot = {now:100,windows:false,openpyxl:true,files:[],commands:[],history:[],queued:[],token:'test',workspace:'test',version:'test'};
const context = {
  document:{getElementById:node,querySelectorAll:()=>[],addEventListener(){},modelContext:{registerTool(t){registered.push(t)}}},
  window:{addEventListener(){}}, location:{hash:''},history:{replaceState(){}},
  URLSearchParams,fetch:async()=>({ok:true,json:async()=>snapshot}),setInterval(){},AbortController,Date,console
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8')+'\nglobalThis.helpers={remainingText,focusTarget,putMarkup,catalogIssues,setCopyTarget,copyFile,storageSize,catalogRows,duration,elapsed,timer,esc,badge,taskTable,commandCards,syncClock,clockSeconds,taskScope,scheduleStopControl,expectedText,putParameters,parameterFields};',context);
const h = context.helpers;
test('elapsed formatting supports seconds, hours, and runs longer than a day',()=>{
  assert.equal(h.duration(65.9),'00:01:05');
  assert.equal(h.duration(90061),'25:01:01');
  assert.equal(h.duration(null),'—');
  assert.equal(h.duration(-1),'00:00:00');
});
test('completed jobs display saved duration, unknown jobs do not keep ticking',()=>{
  assert.equal(h.elapsed({status:'SUCCESS',elapsed:125}),'00:02:05');
  assert.equal(h.elapsed({status:'UNKNOWN',started:1,elapsed:125}),'—');
  assert.match(h.timer({status:'RUNNING',started:50}),/data-start="50"/);
  assert.doesNotMatch(h.timer({status:'SUCCESS',started:50,elapsed:4}),/data-start/);
});
test('file names and log content are escaped',()=>{
  assert.equal(h.esc('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
});
test('read-only run tool validates input and returns lifecycle data',async()=>{
  assert.equal(registered.length,1);
  const tool=registered[0];
  assert.equal(tool.annotations.readOnlyHint,true);
  await assert.rejects(tool.execute({limit:0}),/Limit/);
  await assert.rejects(tool.execute({command:'run'}),/Expected/);
  snapshot.commands=[{status:'RUNNING',tasks:{a:{name:'example.sas',status:'RUNNING',started:92}}}];
  const result=await tool.execute({limit:5});
  assert.equal(result.running[0].name,'example.sas');
  assert.equal(result.running[0].elapsed_seconds,8);
});

test('only running owned files show stop controls and bundle cards show downloads',()=>{
  const task={key:'A',name:'job.sas',status:'RUNNING',path:'runs/A',elapsed:1};
  assert.match(h.taskTable([task],'owner'),/data-cancel-command="owner"/);
  assert.doesNotMatch(h.taskTable([{...task,status:'SUCCESS'}],'owner'),/data-cancel-command/);
  assert.match(h.commandCards([{id:'bundle1',name:'Bundle',status:'SUCCESS',download:'bundle1/code.txt',tasks:{}}]),/api\/download\?command=bundle1/);
});

test('running clock ignores delayed status-poll timestamps',()=>{
  h.syncClock(100);
  const before=h.clockSeconds();
  h.syncClock(90);
  assert.ok(h.clockSeconds()>=before);
  h.syncClock(120);
  assert.ok(h.clockSeconds()-before<1);
});

test('scheduler scope displays section and inclusive row bounds without inventing legacy metadata',()=>{
  assert.equal(h.taskScope({section:'Realised',row_start:20,row_end:85}),'Section Realised · Rows 20–85');
  assert.equal(h.taskScope({row_start:20,row_end:null}),'From row 20 to end');
  assert.equal(h.taskScope({row_start:null,row_end:85}),'Rows 1–85');
  assert.equal(h.taskScope({row_start:20,row_end:20}),'Row 20');
  assert.equal(h.taskScope({row_start:null,row_end:null}),'Whole program');
  assert.equal(h.taskScope({}), '');
  assert.equal(h.taskScope({section:'Realised',row_start:null,row_end:null}), 'Section Realised');
  const markup=h.taskTable([{name:'Realised.sas',section:'<setup>',row_start:2,row_end:5,status:'RUNNING'}]);
  assert.match(markup,/Section &lt;setup&gt; · Rows 2–5/);
});

 test('historical runs without cancellation support never offer a stop button', () => {
   const html = h.taskTable([{name:'job',key:'A',status:'RUNNING',path:'runs/A',can_cancel_file:false}], 'command');
   assert.ok(!html.includes('data-cancel-command'));
 });

test('running scheduler task shows setup and stage without extra running rows',()=>{
  const html=h.taskTable([{name:'Realised',key:'job',status:'RUNNING',section:'A',row_start:2,row_end:5,setup:[{program:'Libraries',row_start:1,row_end:4},{program:'Macros'}],progress:'Appending shared setup: <Libraries>'}]);
  assert.match(html,/Shared setup: Libraries/);
  assert.match(html,/Appending shared setup: &lt;Libraries&gt;/);
  assert.equal((html.match(/<tr(?: |>|\n)/g)||[]).length,2); // one header and one task
});


test('whole-schedule stop is available for schedule and continuation and disabled while stopping',()=>{
  for(const action of ['schedule','continue']) {
    const command={id:'selected',action,status:'RUNNING',name:'Schedule',tasks:{}};
    assert.match(h.commandCards([command]), /data-stop-schedule="selected"/);
    assert.match(h.scheduleStopControl({...command,status:'STOPPING'}), /disabled/);
    assert.match(h.commandCards([{...command,status:'STOPPING'}]), /Stopping schedule/);
    assert.equal(h.scheduleStopControl({...command,status:'SUCCESS'}), '');
  }
  assert.equal(h.scheduleStopControl({id:'watcher',action:'watch',status:'RUNNING'}), '');
  assert.equal(h.scheduleStopControl(undefined), '');
});


test('completed schedules offer their own combined log download',()=>{
  const command={id:'schedule',action:'schedule',name:'Schedule',status:'SUCCESS',tasks:{},schedule_log:'runs/my schedule/schedule.log'};
  const markup=h.commandCards([command]);
  assert.match(markup,/Download schedule log/);
  assert.match(markup,/api\/download\?path=runs%2Fmy%20schedule%2Fschedule.log/);
  assert.doesNotMatch(h.commandCards([{...command,schedule_log:undefined}]),/Download schedule log/);
});


test('timing labels distinguish partial history, unknown and skipped work',()=>{
  assert.match(h.expectedText({seconds:18000,unknown:2}), /~5h\+.*2 task/);
  assert.match(h.expectedText({seconds:null}), /unknown/);
  assert.match(h.expectedText({seconds:120,samples:4}), /~2m.*4 previous/);
  assert.match(h.expectedText({seconds:0}), /skipped/);
  assert.match(h.taskTable([{name:'file',status:'RUNNING',estimate:{seconds:18000,samples:2}}]), /Expected: ~5h/);
});


test('parameters load into the editor as text and can be disabled without discarding edits',()=>{
  h.putParameters({name:'_cases.sas',text:'%let case_ids=1,2;\n/* <code> */',revision:'abc'},true);
  assert.equal(node('parameter-text').value,'%let case_ids=1,2;\n/* <code> */');
  assert.equal(node('parameter-name').value,'_cases.sas');
  assert.equal(node('parameter-files').value,'_cases.sas');
  assert.equal(node('use-parameters').checked,true);
  node('use-parameters').checked=false;h.parameterFields();
  assert.equal(node('parameters-editor').hidden,true);
  assert.match(node('parameter-text').value,/case_ids/);
  h.putParameters({name:'import.sas',text:'%let name=café;'},false);
  assert.equal(node('parameter-files').value,'');
  assert.match(node('parameters-status').textContent,/original file is unchanged/);
});

test('server storage distinguishes missing sizes and partial library totals',()=>{
  assert.equal(h.storageSize(null),'Unknown');
  assert.equal(h.storageSize(0,3),'Unknown');
  assert.equal(h.storageSize(1024,2),'At least 1 KB');
  assert.equal(h.storageSize(1048576),'1 MB');
  assert.equal(h.storageSize(0),'0 B');
});
test('server tables filter and sort without changing the saved snapshot',()=>{
  const catalog={tables:[{libname:'B',name:'Z',bytes:null},{libname:'A',name:'X',label:'Claims',bytes:1024,modified:'2026-09-24T10:00:00'},{libname:'A',name:'Y',bytes:2048,modified:'2026-09-23T10:00:00'}]};
  assert.equal(h.catalogRows(catalog,'A','claims','name')[0].name,'X');
  assert.deepEqual(Array.from(h.catalogRows(catalog,'','','size'),t=>t.name),['Y','X','Z']);
  assert.deepEqual(Array.from(h.catalogRows(catalog,'','','modified'),t=>t.name),['X','Y','Z']);
  assert.equal(catalog.tables[0].name,'Z');
});

test('Copy file requests a native file copy and never fetches or writes file text',async()=>{
  const originalFetch=context.fetch;const originalWindows=snapshot.windows;let request;
  try{
    snapshot.windows=true;
    context.fetch=async(path,options)=>{request={path,options};return {ok:true,json:async()=>({name:'results.xlsx'})};};
    h.setCopyTarget('runs/a long path/results.xlsx');await h.copyFile();
    assert.equal(request.path,'/api/copy-file');
    assert.equal(request.options.method,'POST');
    assert.equal(request.options.headers['X-PySAS-Token'],'test');
    assert.deepEqual(JSON.parse(request.options.body),{path:'runs/a long path/results.xlsx'});
    assert.equal(node('copy-file').textContent,'File copied');
    assert.match(node('copy-status').textContent,/results.xlsx copied as a file/);
    context.fetch=async()=>({ok:false,json:async()=>({error:'Windows clipboard busy'})});
    await h.copyFile();
    assert.match(node('copy-status').textContent,/Copy failed.*clipboard busy/);
    assert.equal(node('copy-file').textContent,'Copy file');
    snapshot.windows=false;h.setCopyTarget('job.log');
    assert.equal(node('copy-file').disabled,true);
    h.setCopyTarget(null);assert.equal(node('copy-file').hidden,true);
  }finally{context.fetch=originalFetch;snapshot.windows=originalWindows;}
});
test('A completed file copy does not mark a different selected file as copied',async()=>{
  const originalFetch=context.fetch;const originalWindows=snapshot.windows;let finish;
  try{
    snapshot.windows=true;
    context.fetch=()=>new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({name:'original.log'})});});
    h.setCopyTarget('original.log');const pending=h.copyFile();
    assert.equal(node('copy-file').disabled,true);
    h.setCopyTarget('different.log');finish();await pending;
    assert.equal(node('copy-file').textContent,'Copy file');
    assert.equal(node('copy-status').hidden,true);
  }finally{context.fetch=originalFetch;snapshot.windows=originalWindows;h.setCopyTarget(null);}
});


test('partial catalogs expose escaped skip reasons and incomplete totals',()=>{
  assert.match(h.badge('PARTIAL'), /Partial snapshot/);
  assert.equal(h.catalogIssues({}), '');
  const html=h.catalogIssues({issues:[{libname:'DATA',name:'<Locked>',message:'Denied <script>'}]});
  assert.match(html, /DATA.&lt;Locked&gt;/);
  assert.match(html, /Denied &lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.equal(h.storageSize(1024,1),'At least 1 KB');
  assert.equal(h.storageSize(0,1),'Unknown');
  assert.match(h.catalogIssues({issues:Array.from({length:101},()=>({message:'Missing'}))}), /first 100 warnings/);
});

test('continued schedule timer includes saved active seconds and identifies multiple parts',()=>{
  const item={status:'RUNNING',started:h.clockSeconds()-5,elapsed_base:3600};
  assert.match(h.elapsed(item),/^01:00:0[56]$/);
  assert.match(h.timer(item),/data-base="3600"/);
  assert.match(h.commandCards([{id:'resume',name:'Schedule',...item,parts:3,tasks:{}}]),/Continued in 3 parts/);
});
test('bundle and schedule downloads offer actual-file copy actions',()=>{
  const html=h.commandCards([{id:'bundle',name:'Bundle',status:'SUCCESS',download:'bundle/source.txt',schedule_log:'runs/x/schedule.log',tasks:{}}]);
  assert.equal((html.match(/data-copy-target=/g)||[]).length,2);
  assert.match(html,/&quot;command&quot;:&quot;bundle&quot;/);
  assert.match(html,/&quot;path&quot;:&quot;runs\/x\/schedule.log&quot;/);
});

// Exercise the actual event controller with DOM-like controls and a list.
function keyboardFixture(count=2,onlyDialog=false){
  const listeners={},lists=[];let doc;
  function element(){return {children:[],style:{},dataset:{},isConnected:true,disabled:false,
    setAttribute(){},getAttribute(){return null},hasAttribute(){return false},append(child){this.children.push(child)},remove(){},
    closest(selector){return selector==='[data-key-list]'?this.list||null:null;},
    getClientRects(){return [1]},getBoundingClientRect(){return {left:10,top:10,bottom:30,right:100}},
    focus(){this.focused=(this.focused||0)+1;doc.activeElement=this;},scrollIntoView(){},querySelectorAll(){return []},
    click(){this.clicked=(this.clicked||0)+1},matches(selector){return selector==='button,a[href]'?!this.field:!!this.field;}
  };}
  const controls=Array.from({length:count},(_,i)=>({...element(),id:'control'+String(i).padStart(3,'0'),textContent:'Action '+i,dataset:{keytip:i===0?'A':i===1?'B':undefined},clicked:0,focused:0}));
  controls[0].dataset.page='overview';if(controls[1])controls[1].dataset.page='history';
  const scope={...element(),querySelectorAll(){return [...(onlyDialog?controls.slice(1):controls),...lists]}};
  doc={body:element(),createElement:element,activeElement:null,getElementById(){return null},
    querySelector(q){if(q.startsWith('.page'))return scope;if(q.startsWith('#all-history'))return lists[0];return null;},
    querySelectorAll(q){if(q==='dialog[open]')return onlyDialog?[scope]:[];if(q==='[data-key-list]')return lists;if(q==='[data-page]')return controls.filter(c=>c.dataset.page);return [];},
    addEventListener(k,f){listeners[k]=f;}};
  const ctx={document:doc,window:{addEventListener(){}},innerWidth:1200,innerHeight:900,requestAnimationFrame:f=>f()};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/keyboard.js'),'utf8'),ctx);
  function key(type,value,options={}){const event={key:value,target:doc.activeElement,prevented:false,preventDefault(){this.prevented=true},stopPropagation(){},...options};listeners[type](event);return event;}
  function addList(count=4){
    const list={...element(),dataset:{keytip:'L'},textContent:'Run history',hasAttribute:q=>q==='data-key-list'};
    list.list=list;list.rows=Array.from({length:count},(_,i)=>{
      const row={...element(),list,matches(){return false;}};
      row.buttons=[{...element(),list,dataset:{path:'runs/'+i},clicked:0},{...element(),list,dataset:{cancelKey:String(i)},clicked:0}];
      row.querySelectorAll=()=>row.buttons;return row;
    });list.querySelectorAll=()=>list.rows;lists.push(list);return list;
  }
  return {api:ctx.PySASKeys,controls,key,doc,addList};
}
test('Alt uses fixed mnemonic navigation and Escape returns from page hints',()=>{
  const f=keyboardFixture();f.key('keydown','Alt');f.key('keyup','Alt');assert.equal(f.api.active,true);
  f.key('keydown','O');assert.equal(f.controls[0].clicked,1);assert.equal(f.api.active,true);
  f.key('keydown','Escape');assert.equal(f.api.active,true);f.key('keydown','Escape');assert.equal(f.api.active,false);
  f.controls[0].field=true;f.api.showPage();f.key('keydown','A');assert.equal(f.controls[0].focused,2);assert.equal(f.controls[0].clicked,1);
});
test('page hints stay stable when a control is disabled and avoid ambiguous prefixes',()=>{
  const f=keyboardFixture(30),items=[{identity:'a',preferred:'C',label:'Copy'},{identity:'b',preferred:'C',label:'Close'},...Array.from({length:40},(_,i)=>({identity:'x'+i,label:'Action'}))];
  const assigned=f.api.assignHints(items);assert.equal(new Set(assigned).size,items.length);
  assert.ok(assigned.every((code,i)=>!assigned.some((other,j)=>i!==j&&other.startsWith(code))));
  f.controls[0].disabled=true;f.api.showPage();f.key('keydown','B');assert.equal(f.controls[1].clicked,1);assert.equal(f.controls[0].clicked,0);
  f.api.hide();f.key('keydown','Alt',{ctrlKey:true});f.key('keyup','Alt');assert.equal(f.api.active,false);
});
test('keyboard hints target the open dialog only',()=>{
  const f=keyboardFixture(2,true);f.api.show();f.key('keydown','B');
  assert.equal(f.controls[0].clicked,0);assert.equal(f.controls[1].clicked,1);
});
test('Alt H enters history, arrows browse without opening and row actions use left/right',()=>{
  const f=keyboardFixture(),list=f.addList();f.api.show();f.key('keydown','H');
  assert.equal(f.doc.activeElement,list.rows[0].buttons[0]);assert.equal(f.api.active,false);
  f.key('keydown','ArrowDown');assert.equal(f.doc.activeElement,list.rows[1].buttons[0]);
  f.key('keydown','ArrowRight');assert.equal(f.doc.activeElement,list.rows[1].buttons[1]);
  f.key('keydown','End');assert.equal(f.doc.activeElement,list.rows[3].buttons[1]);
  f.key('keydown','Home');assert.equal(f.doc.activeElement,list.rows[0].buttons[1]);
  assert.ok(list.rows.every(r=>r.buttons.every(b=>b.clicked===0)));
  assert.equal(f.key('keydown','Enter').prevented,false); // native button activation
  assert.equal(f.key('keydown','Tab').prevented,false);
});
test('list entry remembers the inspected run, clamps bounds, and leaves text-field arrows alone',()=>{
  const f=keyboardFixture(),list=f.addList(2);f.api.enterList(list);f.key('keydown','ArrowDown');
  f.api.enterList(list);assert.equal(f.doc.activeElement,list.rows[1].buttons[0]);
  f.key('keydown','PageDown');assert.equal(f.doc.activeElement,list.rows[1].buttons[0]);
  f.key('keydown','PageUp');assert.equal(f.doc.activeElement,list.rows[0].buttons[0]);
  const input={field:true,matches:()=>true,closest:()=>list};f.doc.activeElement=input;
  assert.equal(f.key('keydown','ArrowDown').prevented,false);assert.equal(f.doc.activeElement,input);
  f.api.refreshLists();assert.ok(list.rows.every(r=>r.buttons.every(b=>b.tabIndex===-1)));assert.equal(list.tabIndex,0);
});
test('unchanged inspector markup preserves focused controls and copy feedback',()=>{
  h.putMarkup('file-list','<button>Copy file</button>');
  node('file-list').innerHTML='<button>Copy file</button><span>Copied</span>';
  h.putMarkup('file-list','<button>Copy file</button>');
  assert.match(node('file-list').innerHTML,/Copied/);
  h.putMarkup('file-list','<button>Different file</button>');
  assert.doesNotMatch(node('file-list').innerHTML,/Copied/);
});

test('restoring an inspected run chooses its original page, not a hidden duplicate',()=>{
  const make=scope=>({tagName:'BUTTON',dataset:{path:'runs/a'},closest:q=>q==='dialog,.page'?{id:scope}:{getAttribute:()=> 'Run history'}});
  const hidden=make('page-overview'),shown=make('page-history');
  const old=context.document.querySelectorAll;context.document.querySelectorAll=()=>[hidden,shown];
  try{assert.equal(h.focusTarget({el:{isConnected:false},data:JSON.stringify(shown.dataset),tag:'BUTTON',list:'Run history',scope:'page-history'}),shown);}
  finally{context.document.querySelectorAll=old;}
});

test('remaining label counts down and distinguishes unknown, overrun and idle',()=>{
  assert.equal(h.remainingText({active:false},100),'No files running');
  assert.match(h.remainingText({active:true,seconds:3660,observed:100,unknown:0},160),/~1h 0m until finished/);
  assert.match(h.remainingText({active:true,seconds:60,observed:100,unknown:1},100),/~1m\+/);
  assert.match(h.remainingText({active:true,seconds:null,unknown:1},100),/unknown/);
  assert.match(h.remainingText({active:true,seconds:5,observed:100,unknown:1},110),/unknown/);
});

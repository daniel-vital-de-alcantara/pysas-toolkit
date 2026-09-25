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
  fetch:async()=>({ok:true,json:async()=>snapshot}),setInterval(){},AbortController,Date,console
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8')+'\nglobalThis.helpers={setCopyTarget,copyFile,storageSize,catalogRows,duration,elapsed,timer,esc,badge,taskTable,commandCards,syncClock,clockSeconds,taskScope,scheduleStopControl,expectedText,putParameters,parameterFields};',context);
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
  assert.equal((html.match(/<tr>/g)||[]).length,2); // one header and one task
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

test('Copy writes full endpoint text rather than the rendered tail and reports permission failures',async()=>{
  const originalFetch=context.fetch;let copied=null, requested=null;
  const originalNavigator=context.navigator;
  try{
    node('file-preview').textContent='[Showing latest output] last few lines';
    context.fetch=async path=>{requested=path;return {ok:true,json:async()=>({text:'FIRST\nfull log café\nLAST'})};};
    context.navigator={clipboard:{writeText:async text=>{copied=text;}}};
    h.setCopyTarget('runs/a long path/job.log');await h.copyFile();
    assert.equal(requested,'/api/file-text?path=runs%2Fa%20long%20path%2Fjob.log');
    assert.equal(copied,'FIRST\nfull log café\nLAST');
    assert.equal(node('copy-file').textContent,'Copied');
    assert.equal(node('copy-file').disabled,false);
    context.navigator.clipboard.writeText=async()=>{throw new Error('Clipboard permission denied');};
    await h.copyFile();
    assert.match(node('copy-status').textContent,/Copy failed.*permission denied/);
    assert.equal(node('copy-file').textContent,'Copy');
    h.setCopyTarget(null);
    assert.equal(node('copy-file').hidden,true);
    assert.equal(node('copy-status').hidden,true);
  }finally{context.fetch=originalFetch;context.navigator=originalNavigator;}
});
test('Copy retains click activation and does not mark a newly selected file as copied',async()=>{
  const originalFetch=context.fetch;const originalNavigator=context.navigator;let resolveFile, copied;
  try{
    context.Blob=Blob;context.ClipboardItem=class{constructor(values){this.values=values;}};
    context.fetch=()=>new Promise(resolve=>{resolveFile=()=>resolve({ok:true,json:async()=>({text:'Original file contents'})});});
    context.navigator={clipboard:{write:async items=>{copied=await (await items[0].values['text/plain']).text();}}};
    h.setCopyTarget('original.log');const pending=h.copyFile();
    assert.equal(node('copy-file').disabled,true);
    h.setCopyTarget('different.log');resolveFile();await pending;
    assert.equal(copied,'Original file contents');
    assert.equal(node('copy-file').textContent,'Copy');
    assert.equal(node('copy-status').hidden,true);
  }finally{context.fetch=originalFetch;context.navigator=originalNavigator;delete context.ClipboardItem;delete context.Blob;h.setCopyTarget(null);}
});

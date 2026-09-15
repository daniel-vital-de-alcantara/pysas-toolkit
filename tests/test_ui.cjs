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
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8')+'\nglobalThis.helpers={duration,elapsed,timer,esc,badge,taskTable,commandCards};',context);
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

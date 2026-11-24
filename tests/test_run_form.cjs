// Parse the actual HTML and dispatch real DOM events/FormData. No live browser or SAS.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.join(__dirname,'..');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(predicate=()=>true){for(let i=0;i<30;i++){await turn();if(predicate())return;}assert.fail('DOM operation did not settle');}

async function harness(t){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/index.html'),'utf8'),{url:'http://localhost/#runner',runScripts:'outside-only'});
  t.after(()=>dom.window.close());
  const w=dom.window,$=id=>w.document.getElementById(id),calls=[];
  const snapshot={now:100,windows:true,openpyxl:true,files:['extract.sas','_override.SAS','_saved.sas'],commands:[],history:[],queued:[],token:'test',workspace:'C:/workspace',version:'test',
    folders:{init:'C:/shared',inbox:'C:/inbox',inputs:'C:/workspace'},initialization_files:['C:/shared/_10_libs.SAS','C:/inbox/_20_macros.sas'],preferences:{default_lib:'',default_egp:'',watcher:{}},shared_work:{enabled:false,path:'',libref:'VDI'},parameters_settings:{enabled:false,files:[]}};
  let revision='revision-1',failure='',defer=null;const responses=new Map();
  function plan(data){
    const override=data.initialization_mode==='override'?data.lib:data.initialization_mode==='shared'?'':snapshot.preferences.default_lib;
    const files=(override?[{name:override.split('/').pop(),path:override,role:'initialization'}]:snapshot.initialization_files.map(p=>({name:p.split('/').pop(),path:p,role:'initialization'})));
    if(data.use_parameters)files.push({name:data.parameters_name,path:null,role:'parameters'});
    files.push({name:data.program,path:'C:/workspace/'+data.program,role:'program'});
    return {revision,mode:override?'override':'shared',override,folders:[snapshot.folders.init,snapshot.folders.inbox],files};
  }
  w.setInterval=()=>0;
  w.fetch=async(url,options={})=>{
    const data=options.body?JSON.parse(options.body):null;calls.push({url,data});
    let result=snapshot,ok=true;
    if(responses.has(url)){const response=responses.get(url),value=typeof response==='function'?await response(data):response;return {ok:!value.error,json:async()=>value};}
    if(url==='/api/run-plan'){
      if(defer){const callback=defer;defer=null;return callback(data);}
      if(failure){result={error:failure};ok=false;}
      else if(data.initialization_mode==='override'&&!data.lib){result={error:'Select the initialization override file.'};ok=false;}
      else result=plan(data);
    }else if(url==='/api/submit'){const command={id:'single',action:'run',name:'Extract',status:'RUNNING',started:100,preparing:true,tasks:{_preparing:{key:'_preparing',name:'Extract',status:'RUNNING',kind:'preparation',started:100,message:'Preparing run…',can_cancel_file:false}}};snapshot.commands=[command];result={id:'single',command};}
    else if(url.startsWith('/api/command-details'))result={command_id:'single',name:'Extract',status:'RUNNING',files:[],tasks:[]};
    return {ok,json:async()=>result};
  };
  w.eval(fs.readFileSync(path.join(root,'ui/app.js'),'utf8')+'\nwindow.testRun={refresh,formData,renderRunInitialization,runFlow,files,launch,navigate,showCommand,showProject,groupedTasks,taskRecords,renderInspectorVersions};');
  await settle(()=>$('connection').textContent==='Connected locally');
  assert.equal($('error').hidden,true,$('error').textContent);
  $('confirm-dialog').showModal=function(){this.open=true;};$('confirm-dialog').close=function(){this.open=false;};
  const change=(id,value)=>{$(id).value=value;$(id).dispatchEvent(new w.Event('change',{bubbles:true}));};
  const ready=async()=>{await w.testRun.renderRunInitialization(true);await settle();assert.equal($('run-submit').disabled,false,$('run-plan-status').textContent);};
  return {w,$,calls,snapshot,change,ready,setResponse:(url,value)=>responses.set(url,value),setRevision:v=>revision=v,setFailure:v=>failure=v,setDefer:v=>defer=v,plan};
}

test('Projects folder list uses arrow keys across actions and between folders',async t=>{
  const {w,$,snapshot}=await harness(t);snapshot.projects=[{id:'first',path:'C:/code/first',name:'First',updated:100,status:'SUCCESS',version_count:1,latest_command:'one'},{id:'second',path:'C:/code/second',name:'Second',updated:99,status:'RUNNING',version_count:1,latest_command:'two'}];await w.testRun.refresh();w.testRun.navigate('tools');
  w.HTMLElement.prototype.getClientRects=function(){return [{width:100,height:20}];};w.HTMLElement.prototype.scrollIntoView=function(){};
  w.eval(fs.readFileSync(path.join(root,'ui/keyboard.js'),'utf8'));const list=$('tools-activity').querySelector('[data-key-list]');
  w.PySASKeys.enterList(list);assert.equal(w.document.activeElement.dataset.projectCopy,'first');
  const key=value=>w.document.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
  key('ArrowRight');assert.equal(w.document.activeElement.dataset.projectUpdate,'first');key('ArrowRight');assert.equal(w.document.activeElement.dataset.projectInspect,'first');
  key('ArrowDown');assert.equal(w.document.activeElement.dataset.projectInspect,'second');key('ArrowLeft');assert.equal(w.document.activeElement.dataset.projectCopy,'second');
  key('Home');assert.equal(w.document.activeElement.dataset.projectCopy,'first');
});

test('actual Run form previews selected override and posts it with unsaved parameters',async t=>{
  const {w,$,calls,change,ready}=await harness(t);
  change('run-source','extract.sas');change('run-init-mode','override');
  assert.equal($('run-init').disabled,false);assert.equal($('run-init-file').hidden,false);
  await settle();assert.equal($('run-submit').disabled,true);
  change('run-init','_override.SAS');$('use-parameters').checked=true;
  $('parameter-name').value='_cases.sas';$('parameter-text').value='%let ids=UNSAVED;';
  $('use-parameters').dispatchEvent(new w.Event('change',{bubbles:true}));await ready();
  const list=Array.from($('run-initialization').querySelectorAll('li')).map(el=>el.textContent);
  assert.equal(list.length,3);assert.match(list[0],/_override.SAS/);assert.match(list[1],/_cases.sas/);assert.match(list[2],/extract.sas/);
  assert.doesNotMatch($('run-initialization').textContent,/_10_libs/);
  assert.match($('run-initialization').textContent,/Current parameter editor contents/);
  assert.equal($('run-form').checkValidity(),true);
  $('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await settle(()=>calls.some(c=>c.url==='/api/submit'));
  const data=calls.find(c=>c.url==='/api/submit').data;
  assert.equal(data.lib,'_override.SAS');assert.equal(data.initialization_mode,'override');
  assert.equal(data.use_parameters,true);assert.equal(data.parameters_text,'%let ids=UNSAVED;');assert.equal(data.plan_revision,'revision-1');
});

test('polling preserves selected override even if the inventory drops it',async t=>{
  const {w,$,snapshot,change,ready}=await harness(t);
  change('run-source','extract.sas');change('run-init-mode','override');change('run-init','_override.SAS');await ready();
  snapshot.files=['extract.sas','new.sas'];await w.testRun.refresh();
  assert.equal($('run-init').value,'_override.SAS');
  assert.equal(w.testRun.formData($('run-form')).lib,'_override.SAS');
  assert.match($('run-initialization').textContent,/_override.SAS/);
});

test('saved default is visible and shared mode can deliberately replace it',async t=>{
  const {w,$,snapshot,change,ready,calls}=await harness(t);snapshot.preferences.default_lib='_saved.sas';
  change('run-source','extract.sas');await ready();assert.match($('run-initialization').textContent,/_saved.sas/);
  change('run-init-mode','shared');await ready();
  assert.match($('run-initialization').textContent,/C:\/shared\/_10_libs.SAS/);
  assert.doesNotMatch($('run-initialization').textContent,/_saved.sas/);
  assert.equal($('run-init').disabled,true);assert.equal(w.testRun.formData($('run-form')).lib,undefined);
  $('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle(()=>calls.some(c=>c.url==='/api/submit'));
  assert.equal(calls.find(c=>c.url==='/api/submit').data.initialization_mode,'shared');
});

test('Run immediately opens Overview and sends the reviewed revision for background validation',async t=>{
  const {w,$,change,ready,calls,setRevision,setFailure}=await harness(t);change('run-source','extract.sas');await ready();
  setRevision('changed');$('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  assert.equal($('page-overview').hidden,false);assert.match($('live-overview').textContent,/Preparing run/);assert.equal(!!$('details-dialog').open,false);
  await settle(()=>calls.some(c=>c.url==='/api/submit'));assert.equal(calls.find(c=>c.url==='/api/submit').data.plan_revision,'revision-1');
  assert.equal(calls.filter(c=>c.url.startsWith('/api/command-details')).length,0);
  setFailure('Override file is no longer available.');await w.testRun.renderRunInitialization(true);
  assert.match($('run-plan-status').textContent,/Override file is no longer available/);assert.equal($('run-submit').disabled,true);
});

test('a late response cannot overwrite the current override preview or enable an unvalidated run',async t=>{
  const {w,$,change,ready,setDefer,plan}=await harness(t);change('run-source','extract.sas');await ready();
  let release;setDefer(data=>new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>plan(data)});}));
  const pending=w.testRun.renderRunInitialization(true);assert.equal($('run-submit').disabled,true);
  change('run-init-mode','override');change('run-init','_override.SAS');await ready();
  release();await pending;
  assert.match($('run-initialization').textContent,/_override.SAS/);assert.doesNotMatch($('run-initialization').textContent,/_10_libs/);
  assert.equal($('run-submit').disabled,false);
});

test('Overview remains visible during a slow submission and polling retains one preparing row',async t=>{
  const {w,$,snapshot,calls,change,ready,setResponse}=await harness(t);change('run-source','extract.sas');await ready();let release;
  setResponse('/api/submit',()=>new Promise(resolve=>{release=()=>{const command={id:'accepted',name:'extract.sas',action:'run',status:'RUNNING',started:100,preparing:true,tasks:{_preparing:{key:'_preparing',name:'extract.sas',kind:'preparation',status:'RUNNING',started:100,message:'Preparing run…',can_cancel_file:false}}};snapshot.commands=[command];resolve({id:'accepted',command});};}));
  $('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));assert.equal($('page-overview').hidden,false);assert.match($('live-overview').textContent,/Preparing run/);await settle(()=>release);
  snapshot.commands=[];await w.testRun.refresh();assert.equal($('live-overview').querySelectorAll('tbody tr').length,1);release();await settle(()=>calls.some(c=>c.url==='/api/submit')&&!$('live-overview').textContent.includes('pending_'));
  assert.equal(!!$('details-dialog').open,false);assert.equal($('live-overview').querySelectorAll('tbody tr').length,1);
});

test('same exact names group only the history view while separate active jobs remain visible',async t=>{
  const {w,$,snapshot}=await harness(t);snapshot.commands=[{id:'a',name:'Daily',action:'stream',status:'RUNNING',started:90,tasks:{a:{key:'a',name:'Daily',status:'RUNNING',started:90}}},{id:'b',name:'Daily',action:'stream',status:'RUNNING',started:95,tasks:{b:{key:'b',name:'Daily',status:'RUNNING',started:95}}},{id:'c',name:'daily',action:'stream',status:'SUCCESS',started:80,tasks:{}}];
  await w.testRun.refresh();w.testRun.navigate('overview');assert.equal($('live-overview').querySelectorAll('tbody tr').length,2);assert.equal($('all-history').querySelectorAll('tbody tr').length,2);assert.match($('all-history').textContent,/2 versions/);
});

test('inspector version choice stays selected and completed/error schedules offer the right rerun actions',async t=>{
  const {w,$,snapshot,setResponse}=await harness(t);snapshot.commands=[{id:'failed',name:'Daily',action:'schedule',status:'FAILED',started:90,tasks:{}},{id:'done',name:'Daily',action:'schedule',status:'SUCCESS',started:95,tasks:{}}];
  setResponse('/api/command-details?id=failed',{command_id:'failed',name:'Daily',status:'FAILED',whole_run:true,folder_path:'tasks/schedules/failed',files:[],tasks:[]});setResponse('/api/command-details?id=done',{command_id:'done',name:'Daily',status:'SUCCESS',whole_run:true,folder_path:'tasks/schedules/done',files:[],tasks:[]});
  await w.testRun.refresh();await w.testRun.showCommand('failed');assert.ok($('inspector-execution-controls').querySelector('[data-run-again]'));assert.ok($('inspector-execution-controls').querySelector('[data-continue-schedule]'));assert.equal($('inspector-version').options.length,2);
  $('inspector-version').value='command:done';$('inspector-version').dispatchEvent(new w.Event('change',{bubbles:true}));await settle(()=>$('inspector-version').value==='command:done'&&!$('inspector-execution-controls').querySelector('[data-continue-schedule]'));
  snapshot.commands.unshift({id:'newest',name:'Daily',action:'schedule',status:'SUCCESS',started:99,tasks:{}});await w.testRun.refresh();await w.testRun.showCommand('done',true);assert.equal($('inspector-version').value,'command:done');assert.equal($('inspector-version').options.length,3);assert.equal($('inspector-execution-controls').querySelectorAll('[data-run-again]').length,1);
});

test('Projects has separate Pack/Unpack buttons and folder rows with three keyboard-browsable actions',async t=>{
  const {w,$,snapshot,calls,setResponse}=await harness(t);snapshot.projects=[{id:'folder1',name:'Models',path:'C:/long/path/Models',updated:90,version_count:2,latest_command:'pack1',status:'SUCCESS'}];await w.testRun.refresh();w.testRun.navigate('tools');
  assert.equal($('bundle-action'),null);assert.match($('bundle-form').querySelector('[type=submit]').textContent,/Pack bundle/);assert.match($('bundle-unpack').textContent,/Unpack bundle/);assert.doesNotMatch($('tools-activity').textContent,/C:\/long\/path/);
  const row=$('tools-activity').querySelector('[data-key-row]');assert.equal(row.querySelectorAll('button').length,3);assert.ok(row.closest('[data-key-list]'));
  setResponse('/api/project-copy',{name:'latest.txt'});row.querySelector('[data-project-copy]').click();await settle(()=>calls.some(c=>c.url==='/api/project-copy'));assert.equal(calls.find(c=>c.url==='/api/project-copy').data.id,'folder1');
  $('bundle-code-root').value='C:/long/path/Models';$('bundle-unpack').click();assert.equal($('confirm-dialog').open,true);assert.match($('unpack-target').textContent,/Models/);$('cancel-unpack').click();assert.equal($('confirm-dialog').open,false);
});

test('folder inspector opens version history, selects a pack and renames the folder',async t=>{
  const {w,$,snapshot,calls,setResponse}=await harness(t);snapshot.commands=[{id:'pack1',name:'bundle pack',action:'bundle-pack',status:'SUCCESS',started:90,tasks:{}}];
  const detail={project_id:'folder',project_path:'C:/code/Models',command_id:'pack1',name:'Models',status:'SUCCESS',can_rename:true,files:[],tasks:[],project_versions:[{id:'pack1',action:'bundle-pack',status:'SUCCESS',started:90,download:true}]};
  setResponse('/api/project-details?id=folder',detail);setResponse('/api/project-details?id=folder&version=pack1',detail);setResponse('/api/project-name',{id:'folder',name:'Daily models'});
  await w.testRun.refresh();await w.testRun.showProject('folder');assert.equal($('detail-tasks').hidden,false);assert.match($('detail-tasks').textContent,/pack/);$('detail-tasks').querySelector('[data-project-version]').click();await settle(()=>$('detail-tasks').hidden===true);
  $('run-display-name').value='Daily models';$('rename-run').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle(()=>calls.some(c=>c.url==='/api/project-name'));assert.equal(calls.find(c=>c.url==='/api/project-name').data.name,'Daily models');
});

test('rapid folder version choices ignore an older response that arrives last',async t=>{
  const {w,$,setResponse}=await harness(t);const base={project_id:'folder',project_path:'C:/code',name:'Code',status:'SUCCESS',can_rename:true,files:[],tasks:[],project_versions:[{id:'old',action:'bundle-pack',status:'SUCCESS',started:90},{id:'new',action:'bundle-pack',status:'SUCCESS',started:95}]};
  let finish;setResponse('/api/project-details?id=folder&version=old',()=>new Promise(resolve=>{finish=()=>resolve({...base,command_id:'old'});}));setResponse('/api/project-details?id=folder&version=new',{...base,command_id:'new'});
  const pending=w.testRun.showProject('folder',false,'old');await settle(()=>finish);await w.testRun.showProject('folder',false,'new',true);finish();await pending;
  assert.equal($('inspector-version').value,'command:new');assert.equal($('run-display-name').getAttribute('aria-label'),'Folder name');
});

test('an older inspector retains replay actions outside the recent command list',async t=>{
  const {w,$,snapshot,setResponse}=await harness(t);snapshot.commands=[];await w.testRun.refresh();
  setResponse('/api/command-details?id=old',{command_id:'old',command:{id:'old',name:'Daily',action:'schedule',status:'FAILED',started:1,elapsed:10},name:'Daily',status:'FAILED',whole_run:true,folder_path:'tasks/schedules/old',files:[],tasks:[]});
  await w.testRun.showCommand('old');assert.ok($('inspector-execution-controls').querySelector('[data-run-again]'));assert.ok($('inspector-execution-controls').querySelector('[data-continue-schedule]'));
});

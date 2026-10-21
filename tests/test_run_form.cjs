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
  let revision='revision-1',failure='',defer=null;
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
    if(url==='/api/run-plan'){
      if(defer){const callback=defer;defer=null;return callback(data);}
      if(failure){result={error:failure};ok=false;}
      else if(data.initialization_mode==='override'&&!data.lib){result={error:'Select the initialization override file.'};ok=false;}
      else result=plan(data);
    }else if(url==='/api/launch')result={id:'single'};
    else if(url.startsWith('/api/command-details'))result={command_id:'single',name:'Extract',status:'RUNNING',files:[],tasks:[]};
    return {ok,json:async()=>result};
  };
  w.eval(fs.readFileSync(path.join(root,'ui/app.js'),'utf8')+'\nwindow.testRun={refresh,formData,renderRunInitialization,runFlow,files,launch};');
  await settle(()=>$('connection').textContent==='Connected locally');
  assert.equal($('error').hidden,true,$('error').textContent);
  const change=(id,value)=>{$(id).value=value;$(id).dispatchEvent(new w.Event('change',{bubbles:true}));};
  const ready=async()=>{await w.testRun.renderRunInitialization(true);await settle();assert.equal($('run-submit').disabled,false,$('run-plan-status').textContent);};
  return {w,$,calls,snapshot,change,ready,setRevision:v=>revision=v,setFailure:v=>failure=v,setDefer:v=>defer=v,plan};
}

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
  await settle(()=>calls.some(c=>c.url==='/api/launch'));
  const data=calls.find(c=>c.url==='/api/launch').data;
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
  $('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle(()=>calls.some(c=>c.url==='/api/launch'));
  assert.equal(calls.find(c=>c.url==='/api/launch').data.initialization_mode,'shared');
});

test('changed inputs require review and a plan error stays beside the Run controls',async t=>{
  const {w,$,change,ready,calls,setRevision,setFailure}=await harness(t);change('run-source','extract.sas');await ready();
  setRevision('changed');$('run-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle(()=>$('run-plan-status').textContent.includes('No code was submitted'));
  assert.equal(calls.filter(c=>c.url==='/api/launch').length,0);assert.equal($('run-submit').disabled,false);
  setFailure('Override file is no longer available.');await w.testRun.renderRunInitialization(true);
  assert.match($('run-plan-status').textContent,/Override file is no longer available/);
  assert.equal($('run-submit').disabled,true);assert.equal($('error').hidden,true);
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

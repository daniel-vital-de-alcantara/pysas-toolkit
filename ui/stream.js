/* Staged Run stream editor. Source preparation stays independent of SAS execution. */
(function () {
  'use strict';
  const FORMAT='pysas-run-stream-2', clone=value=>JSON.parse(JSON.stringify(value));
  let counter=0;
  const id=()=>`source_${Date.now().toString(36)}_${++counter}`;
  function selection(){return {mode:'whole',row_start:null,row_end:null,section:'',sections:[]};}
  function row(kind='file'){return {id:id(),source_kind:kind,name:'Inline code',file:null,code:'',project:null,programs:[],...selection()};}
  function empty(shared={}){return {format:FORMAT,name:'Untitled stream',egp:null,connection_mode:'auto',server_program:'',rows:[],shared_work:{enabled:!!shared.enabled,path:shared.path||'',libref:shared.libref||'VDI'},export_html:true,export_tables:false,consolidate_tables:false};}
  function move(document,key,step){const next=clone(document),index=next.rows.findIndex(r=>r.id===key),target=index+step;if(index>=0&&target>=0&&target<next.rows.length)[next.rows[index],next.rows[target]]=[next.rows[target],next.rows[index]];return next;}
  function reorder(document,key,target,after=false){const next=clone(document),from=next.rows.findIndex(r=>r.id===key);if(from<0||key===target)return next;const [item]=next.rows.splice(from,1),index=next.rows.findIndex(r=>r.id===target);if(index<0)return clone(document);next.rows.splice(index+(after?1:0),0,item);return next;}
  function remove(document,key){const next=clone(document);next.rows=next.rows.filter(r=>r.id!==key);return next;}
  function chosenSections(unit){return unit.sections?.length?unit.sections:unit.section?[unit.section]:[];}
  function analysisFor(unit){return unit.source_kind==='inline'?unit.analysis:unit.file;}
  function scope(unit){return unit.mode==='section'?'Sections: '+(chosenSections(unit).join(', ')||'choose below'):unit.mode==='lines'?`Lines ${unit.row_start||1}–${unit.row_end||'end'}`:'Whole file';}
  function selectionErrors(unit,analysis){
    const errors=[];
    if(unit.mode==='lines'){
      if(unit.row_start==null&&unit.row_end==null)errors.push('Enter a first or last line, or choose Whole file.');
      for(const key of ['row_start','row_end'])if(unit[key]!=null&&(!Number.isInteger(unit[key])||unit[key]<1))errors.push('Line numbers must be positive whole numbers.');
      if(unit.row_start&&unit.row_end&&unit.row_start>unit.row_end)errors.push('The first line is after the last line.');
      if(analysis?.lines!=null&&((unit.row_start||1)>analysis.lines||(unit.row_end||0)>analysis.lines))errors.push(`This source has ${analysis.lines} lines; adjust the range.`);
    }
    if(unit.mode==='section'){
      const chosen=chosenSections(unit),available=new Set((analysis?.sections||[]).map(s=>s.toLowerCase()));
      if(!chosen.length)errors.push('Select at least one section.');
      if(analysis&&chosen.some(s=>!available.has(s.toLowerCase())))errors.push('A selected section is not available in this source.');
    }
    return [...new Set(errors)];
  }
  function submission(value){const next=clone(value),clean=ref=>ref?{path:ref.path,name:ref.name,sha256:ref.sha256}:null;next.egp=clean(next.egp);for(const r of next.rows){r.file=clean(r.file);r.project=clean(r.project);delete r.analysis;for(const p of r.programs||[])p.file=clean(p.file);}return next;}
  const helpers={empty,row,move,reorder,remove,scope,submission,selectionErrors};
  if(typeof module!=='undefined')module.exports=helpers;
  if(typeof document==='undefined'||!document.getElementById('page-stream'))return;
  const $=key=>document.getElementById(key), host=()=>globalThis.PySASGraphHost;
  const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const spinner=text=>`<span class="stream-loading"><i aria-hidden="true"></i>${E(text)}</span>`;
  const views=new Map(), queue=[];
  let model=empty(),snapshot=null,started=false,shownFiles=false,generation=0,revision=0,connectionToken=0,connectionState='idle',connectionError='',connectionCatalog=null;
  let busy=0,backgroundCount=0,commandId=null,commandSignature='',pendingTemplate=null,refreshShared=false,dragged=null;
  function view(key){if(!views.has(key))views.set(key,{token:0,loading:'',error:'',catalog:null,search:'',flow:'',visible:100});return views.get(key);}
  function findRow(key){return model.rows.find(r=>r.id===key);}
  function findUnit(key){for(const r of model.rows){if(r.id===key)return r;const p=r.programs.find(p=>p.id===key);if(p)return p;}return null;}
  function cardElement(key){return [...$('stream-rows').querySelectorAll('[data-stream-row]')].find(el=>el.dataset.streamRow===key);}
  function unitElement(key){return [...$('stream-rows').querySelectorAll('[data-unit]')].find(el=>el.dataset.unit===key);}
  function message(text,failed=false,target='stream-status'){$(target).textContent=text;$(target).classList.toggle('inline-error',failed);}
  function changed(){revision++;message('');$('stream-estimate-result').textContent='';$('stream-artifacts').innerHTML='';updateStatus();}
  function afterRender(){globalThis.PySASKeys?.refreshLists();}
  function rememberFocus(){const element=document.activeElement;if(!element?.closest('#stream-rows'))return null;return {card:element.closest('[data-stream-row]')?.dataset.streamRow,unit:element.closest('[data-unit]')?.dataset.unit,field:element.dataset.streamField||element.dataset.unitField,action:element.dataset.streamAction,programAction:element.dataset.programAction,start:element.selectionStart,end:element.selectionEnd};}
  function restoreFocus(saved){if(!saved)return;const root=saved.unit?unitElement(saved.unit):cardElement(saved.card);let element=saved.field?root?.querySelector(`[data-stream-field="${saved.field}"],[data-unit-field="${saved.field}"]`):saved.programAction?root?.querySelector(`[data-program-action="${saved.programAction}"]:not(:disabled)`):root?.querySelector(`[data-stream-action="${saved.action}"]:not(:disabled)`);element=element||root?.querySelector('[data-stream-action="focus-source"],textarea,button:not(:disabled)');element?.focus({preventScroll:true});try{if(saved.start!=null)element?.setSelectionRange(saved.start,saved.end);}catch(_){} }
  function rowIssues(r){
    const v=view(r.id),issues=[];
    if(v.loading)issues.push(v.loading);
    if(v.error)issues.push(v.error);
    if(r.source_kind==='file'){
      if(!r.file)issues.push('Choose a SAS file.');
      else if(!r.file.lines||r.file.has_code===false)issues.push('The file has no SAS code.');
      else issues.push(...selectionErrors(r,r.file));
    }else if(r.source_kind==='inline'){
      if(!r.code.trim())issues.push('Enter SAS code.');
      else issues.push(...selectionErrors(r,r.analysis));
    }else{
      if(!r.project)issues.push('Choose an EGP project.');
      if(!r.programs.length)issues.push('Select one or more EGP programs.');
      for(const p of r.programs){const pv=view(p.id);if(pv.loading)issues.push(`${p.name}: extracting code…`);else if(pv.error)issues.push(`${p.name}: ${pv.error}`);else if(!p.file)issues.push(`${p.name}: source is not loaded.`);else if(!p.file.lines||p.file.has_code===false)issues.push(`${p.name}: this program has no SAS code.`);else issues.push(...selectionErrors(p,p.file).map(e=>`${p.name}: ${e}`));}
    }
    return [...new Set(issues)];
  }
  function documentIssues(){
    const issues=[];
    if(!model.name.trim())issues.push('Give the run a name.');
    if(connectionState!=='ready'||!model.egp)issues.push(connectionState==='loading'?'Checking the connection EGP…':connectionError||'Choose a connection EGP.');
    if(model.server_program&&connectionCatalog){const matches=connectionCatalog.programs.filter(p=>p.name.toLowerCase()===model.server_program.trim().toLowerCase());if(matches.length!==1)issues.push('Choose a uniquely named code node from the connection EGP.');}
    const shared=model.shared_work;
    if(shared.enabled&&(!shared.path.trim()||!/^[_A-Z][_A-Z0-9]{0,7}$/i.test(shared.libref)||['WORK','USER','SASUSER','SASHELP'].includes(shared.libref.toUpperCase())))issues.push('Complete the shared WORK settings, or turn shared WORK off.');
    if(!model.rows.length)issues.push('Add a file or code card.');
    model.rows.forEach((r,index)=>rowIssues(r).forEach(error=>issues.push(`Card ${index+1}: ${error}`)));
    return issues;
  }
  function updateStatus(){
    const issues=documentIssues(),valid=started&&!issues.length;
    $('stream-ready-controls').hidden=!valid;
    $('stream-submit-card').classList.toggle('stream-needs-input',!valid);
    $('stream-readiness').innerHTML=valid?'<span class="stream-ready-label">✓ Ready to submit</span>':`<strong>Complete the stream to continue</strong><ul>${issues.slice(0,6).map(s=>`<li>${E(s)}</li>`).join('')}${issues.length>6?`<li>And ${issues.length-6} more items…</li>`:''}</ul>`;
    for(const kind of ['estimate','source','export','run'])$('stream-'+kind).disabled=!valid||busy>0||(kind==='run'&&!snapshot?.windows);
    $('stream-consolidate').disabled=!model.export_tables;
    for(const r of model.rows){const element=cardElement(r.id);if(!element)continue;const errors=rowIssues(r),v=view(r.id),loading=!!v.loading||r.programs.some(p=>view(p.id).loading);element.classList.toggle('is-ready',!errors.length);element.classList.toggle('needs-input',!!errors.length&&!loading);element.classList.toggle('is-loading',loading);element.setAttribute('aria-busy',String(loading));const status=element.querySelector('.stream-card-status');if(status)status.innerHTML=loading?spinner(v.loading||'Extracting selected code…'):errors.length?`<span class="stream-incomplete-label">○ ${E(errors[0])}</span>`:'<span class="stream-ready-label">✓ Ready</span>';}
    $('stream-shared-work-status').textContent=model.shared_work.enabled&&!model.shared_work.path?'Set the server WORK path in Settings, or turn this off.':'';
    $('stream-shared-work-info').textContent=model.shared_work.enabled?(model.shared_work.path?`${model.shared_work.libref} · ${model.shared_work.path}`:'Server path needed'):'Use a private WORK for this submission';
  }
  function connectionOptions(){
    const choices=new Map((snapshot?.files||[]).filter(path=>/\.egp$/i.test(path)).map(path=>[path,path]));if(model.egp)choices.set(model.egp.path,model.egp.name);
    const signature=JSON.stringify([...choices]);if($('stream-egp').dataset.signature!==signature){$('stream-egp').innerHTML='<option value="">Automatic · use an available EGP</option>'+[...choices].map(([path,name])=>`<option value="${E(path)}">${E(name)}</option>`).join('');$('stream-egp').dataset.signature=signature;}
    $('stream-egp').value=model.connection_mode==='auto'?'':model.egp?.path||'';
    $('stream-connection-summary').innerHTML=connectionState==='loading'?spinner('Checking project…'):model.egp&&connectionState==='ready'?E((model.connection_mode==='auto'?'Automatic · ':'')+model.egp.name):'Choose an EGP';
  }
  function optionsMarkup(unit,analysis){
    const key=E(unit.id),sections=analysis?.sections||[],chosen=new Set(chosenSections(unit).map(s=>s.toLowerCase()));
    const unknown=chosenSections(unit).filter(s=>!sections.some(name=>name.toLowerCase()===s.toLowerCase()));
    return `<div class="stream-selection"><label>Run<select data-unit-field="mode"><option value="whole" ${unit.mode==='whole'?'selected':''}>Whole file</option><option value="lines" ${unit.mode==='lines'?'selected':''}>Between lines</option><option value="section" ${unit.mode==='section'?'selected':''}>Named sections</option></select></label><div class="stream-bounds" ${unit.mode==='lines'?'':'hidden'}><label>From line<input type="number" min="1" step="1" data-unit-field="row_start" value="${E(unit.row_start??'')}" placeholder="Start"></label><label>To line<input type="number" min="1" step="1" data-unit-field="row_end" value="${E(unit.row_end??'')}" placeholder="End"></label></div></div><div class="stream-sections" ${unit.mode==='section'?'':'hidden'}>${sections.length?`<fieldset><legend>Sections · run in the order listed</legend>${sections.map(name=>`<label class="check"><input type="checkbox" data-unit-section="${E(name)}" ${chosen.has(name.toLowerCase())?'checked':''}>${E(name)}</label>`).join('')}</fieldset>`:`<p class="hint stream-section-help">No complete named sections were found. Add matching markers around your code:</p><pre class="stream-marker-example">* (please do not delete) section_start: My section;\n/* your code */\n* (please do not delete) section_end: My section;</pre>`}${unknown.length?`<p class="inline-error">Missing sections: ${E(unknown.join(', '))}. <button class="text-button" type="button" data-clear-sections="${key}">Clear unavailable choices</button></p>`:''}${analysis?.section_issues?.length?`<p class="hint">${E(analysis.section_issues.join(' '))}</p>`:''}</div>`;
  }
  function programMarkup(p,index,total){const v=view(p.id);return `<article class="stream-program" data-key-row data-unit="${E(p.id)}" data-stream-program="${E(p.id)}"><div class="stream-program-heading"><strong>${index+1}. ${E(p.name)}<small>${E(p.flow)}</small></strong><div class="actions"><button type="button" class="subtle" data-program-action="up" ${index===0?'disabled':''} aria-label="Move ${E(p.name)} earlier">↑</button><button type="button" class="subtle" data-program-action="down" ${index===total-1?'disabled':''} aria-label="Move ${E(p.name)} later">↓</button><button type="button" class="subtle" data-program-action="delete" aria-label="Remove ${E(p.name)}">Remove</button></div></div>${v.loading?spinner('Extracting code…'):v.error?`<p class="inline-error">${E(v.error)} <button type="button" class="text-button" data-program-action="retry">Retry</button></p>`:p.file?`<div class="stream-options-host">${optionsMarkup(p,p.file)}</div>`:'<p class="hint">Source not loaded.</p>'}</article>`;}
  function catalogMarkup(r){const v=view(r.id);if(v.loading)return spinner(v.loading);if(v.error)return `<p class="inline-error">${E(v.error)} <button type="button" class="text-button" data-stream-action="read-project">Retry</button></p>`;if(!v.catalog)return '<p class="hint">Choose a project to see its process flows and programs.</p>';return `<div class="stream-program-picker"><div class="stream-program-filters"><label>Process flow<select data-stream-field="flow"><option value="">All process flows</option>${[...new Set(v.catalog.programs.map(p=>p.flow))].map(name=>`<option value="${E(name)}" ${v.flow===name?'selected':''}>${E(name)}</option>`).join('')}</select></label><label>Find a program<input type="search" data-stream-field="search" value="${E(v.search)}" placeholder="Program name…"></label></div><div class="stream-program-catalog">${catalogChoices(r)}</div></div>`;}
  function catalogChoices(r){const v=view(r.id),list=(v.catalog?.programs||[]).filter(p=>(!v.flow||p.flow===v.flow)&&(!v.search||p.name.toLowerCase().includes(v.search.toLowerCase())));return list.slice(0,v.visible).map(p=>`<label class="check"><input type="checkbox" data-egp-program="${E(p.id)}" ${r.programs.some(item=>item.program_id===p.id)?'checked':''} ${p.member?'':'disabled'}><span>${E(p.name)}<small>${E(p.flow)}${p.member?'':' · source is external; choose its SAS file instead'}</small></span></label>`).join('')+(list.length>v.visible?'<button type="button" class="text-button" data-stream-action="more-programs">Show more programs</button>':'')+(!list.length?'<p class="hint">No matching embedded programs.</p>':'');}
  function rowMarkup(r,index){
    const v=view(r.id),key=E(r.id),title=r.source_kind==='file'?(r.file?.name||'Choose a SAS file'):r.source_kind==='inline'?(r.name||'Inline code'):(r.project?.name||'Choose EGP programs');
    let content='';
    if(r.source_kind==='file')content=`<input type="file" accept=".sas" data-stream-upload hidden>${r.file?`<div data-unit="${key}"><div class="stream-options-host">${optionsMarkup(r,r.file)}</div><small class="hint">${r.file.lines} source lines</small></div>`:'<p class="hint stream-source-prompt">Choose a SAS file to see its line and section options.</p>'}`;
    else if(r.source_kind==='inline')content=`<label class="stream-inline-name">Code name<input type="text" maxlength="120" data-stream-field="name" value="${E(r.name)}" placeholder="Parameters or setup"></label><label>SAS code<textarea class="stream-code-editor" data-stream-field="code" rows="4" spellcheck="false" placeholder="%let case_ids = ;">${E(r.code)}</textarea></label>${r.code.trim()?`<div data-unit="${key}"><div class="stream-options-host">${optionsMarkup(r,r.analysis)}</div></div>`:''}`;
    else content=`<div class="stream-egp-source"><span>${r.project?E(r.project.name):'Use the connection EGP or choose another project.'}</span><button type="button" class="text-button" data-stream-action="use-connection">Use connection EGP</button><button type="button" class="secondary" data-stream-action="browse-project">Browse EGP…</button><input type="file" accept=".egp" data-project-upload hidden></div><div class="stream-catalog-host">${catalogMarkup(r)}</div><div class="stream-programs" data-key-list tabindex="0" aria-label="Selected programs in order">${r.programs.length?'<h4>Selected order</h4>'+r.programs.map((p,i)=>programMarkup(p,i,r.programs.length)).join(''):''}</div>${v.catalog?.warnings?.length?`<details class="stream-project-warnings"><summary>Project notes (${v.catalog.warnings.length})</summary><p class="hint">${v.catalog.warnings.map(E).join('<br>')}</p></details>`:''}`;
    return `<article class="panel stream-row" data-key-row data-stream-row="${key}" aria-label="Source card ${index+1}"><div class="stream-row-heading"><span class="stream-grip" draggable="true" title="Drag to reorder" aria-label="Drag to reorder">⠿</span><span class="stream-position">${index+1}</span><button class="stream-source-title text-button" type="button" data-stream-action="focus-source">${E(title)}</button><label class="stream-kind-label"><span class="sr-only">Source type for card ${index+1}</span><select data-stream-field="source_kind"><option value="file" ${r.source_kind==='file'?'selected':''}>SAS file</option><option value="inline" ${r.source_kind==='inline'?'selected':''}>Write code</option><option value="egp" ${r.source_kind==='egp'?'selected':''}>EGP programs</option></select></label><div class="actions"><button type="button" class="subtle" data-stream-action="up" aria-label="Move card ${index+1} up" ${index===0?'disabled':''}>↑</button><button type="button" class="subtle" data-stream-action="down" aria-label="Move card ${index+1} down" ${index===model.rows.length-1?'disabled':''}>↓</button><button type="button" class="subtle" data-stream-action="delete" aria-label="Delete card ${index+1}">×</button></div></div>${content}<div class="stream-card-status" role="status"></div></article>`;
  }
  function renderRows(focus){const saved=focus||rememberFocus();$('stream-rows').innerHTML=model.rows.map(rowMarkup).join('');afterRender();updateStatus();restoreFocus(saved);}
  function renderRow(key){const element=cardElement(key),r=findRow(key);if(!element||!r)return;const saved=rememberFocus();element.outerHTML=rowMarkup(r,model.rows.indexOf(r));afterRender();updateStatus();restoreFocus(saved);}
  function renderPrograms(r){const element=cardElement(r.id);if(!element)return;const saved=rememberFocus(),programList=element.querySelector('.stream-programs');if(!programList){updateStatus();return;}programList.innerHTML=r.programs.length?'<h4>Selected order</h4>'+r.programs.map((p,i)=>programMarkup(p,i,r.programs.length)).join(''):'';const choices=element.querySelector('.stream-program-catalog');if(choices)choices.innerHTML=catalogChoices(r);afterRender();updateStatus();restoreFocus(saved);}
  function updateUnitOptions(unit){const element=unitElement(unit.id);if(!element)return;const saved=rememberFocus();element.querySelector('.stream-options-host').innerHTML=optionsMarkup(unit,analysisFor(unit));afterRender();updateStatus();restoreFocus(saved);}
  function render(){
    $('stream-workspace').hidden=!started;$('stream-start-hint').textContent=started?'Start a new run or load another template.':'Start fresh or restore a saved template.';
    $('stream-name').value=model.name;$('stream-server-program').value=model.server_program;
    for(const [key,field] of [['stream-html','export_html'],['stream-tables','export_tables'],['stream-consolidate','consolidate_tables']])$(key).checked=model[field];
    $('stream-shared-work').checked=model.shared_work.enabled;$('stream-files-stage').hidden=!shownFiles;
    connectionOptions();renderRows();updateStatus();
  }
  function queueBackground(work){return new Promise((resolve,reject)=>{queue.push({work,resolve,reject});pump();});}
  function pump(){while(backgroundCount<3&&queue.length){const task=queue.shift();backgroundCount++;Promise.resolve().then(task.work).then(task.resolve,task.reject).finally(()=>{backgroundCount--;pump();});}}
  async function background(data){return queueBackground(async()=>{let result=await host().request('/api/stream-job',data);while(result.status==='WORKING'){await new Promise(resolve=>setTimeout(resolve,180));result=await host().request('/api/stream-job?id='+encodeURIComponent(result.id));}if(result.status!=='READY')throw Error(result.error||result.message||'Source preparation failed.');return result.result;});}
  function upload(file,path,progress){return new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open('POST',path);request.setRequestHeader('X-PySAS-Token',snapshot?.token||'');request.upload.onprogress=e=>{if(e.lengthComputable)progress(`Uploading ${file.name} · ${Math.round(e.loaded/e.total*100)}%`);};request.upload.onload=()=>progress('Reading '+file.name+'…');request.onload=()=>{try{const value=JSON.parse(request.responseText);if(request.status>=200&&request.status<300)resolve(value);else reject(Error(value.error||'Upload failed.'));}catch(e){reject(e);}};request.onerror=()=>reject(Error('Upload interrupted.'));request.send(file);});}
  async function loadConnection(path='',preserveAutomatic=false){
    const token=++connectionToken,currentGeneration=generation;connectionState='loading';connectionError='';connectionOptions();updateStatus();$('stream-egp-status').innerHTML=spinner('Checking available EGPs…');
    try{const result=await background({kind:'connection',path});if(token!==connectionToken||currentGeneration!==generation)return;
      model.egp=result.egp;connectionCatalog=result.catalog;connectionState=result.egp?'ready':'missing';if(!preserveAutomatic)model.connection_mode=path?'chosen':'auto';
      $('stream-server-nodes').innerHTML=(result.catalog?.programs||[]).map(p=>`<option value="${E(p.name)}"></option>`).join('');
      if(result.egp){shownFiles=true;$('stream-files-stage').hidden=false;$('stream-connection-options').open=false;message('',false,'stream-egp-status');}
      else{$('stream-connection-options').open=true;message('No usable EGP was found. Browse a connection project to continue.',false,'stream-egp-status');}
      changed();connectionOptions();
    }catch(e){if(token!==connectionToken||currentGeneration!==generation)return;connectionState='error';connectionError=e.message;$('stream-connection-options').open=true;message(e.message,true,'stream-egp-status');connectionOptions();updateStatus();}
  }
  async function chooseConnection(file){if(!file)return;const current=generation,token=++connectionToken;connectionState='loading';connectionError='';connectionOptions();updateStatus();try{if(!/\.egp$/i.test(file.name))throw Error('Choose an .egp file.');const ref=await upload(file,'/api/upload?target=stream&name='+encodeURIComponent(file.name),text=>{if(current===generation&&token===connectionToken)$('stream-egp-status').innerHTML=spinner(text);});if(current!==generation||token!==connectionToken)return;model.egp=ref;model.connection_mode='chosen';connectionOptions();await loadConnection(ref.path);}catch(e){if(current!==generation||token!==connectionToken)return;connectionState='error';connectionError=e.message;message(e.message,true,'stream-egp-status');connectionOptions();updateStatus();}}
  async function chooseFile(file,key,project=false){if(!file)return;const r=findRow(key);if(!r)return;const v=view(key),token=++v.token,current=generation;v.loading='Reading '+file.name+'…';v.error='';updateStatus();try{
      if(!(project?/\.egp$/i:/\.sas$/i).test(file.name))throw Error(project?'Choose an .egp file.':'Choose a .sas file.');
      const ref=await upload(file,'/api/upload?target=stream&name='+encodeURIComponent(file.name),text=>{if(token===v.token){v.loading=text;updateStatus();}});
      if(current!==generation||token!==v.token||!findRow(key))return;
      if(project){r.project=ref;r.programs=[];v.catalog=null;v.loading='';changed();renderRow(key);await loadProject(r);}else{r.file=ref;v.loading='';changed();renderRow(key);}
    }catch(e){if(current===generation&&token===v.token&&findRow(key)){v.error=e.message;v.loading='';updateStatus();}}
  }
  async function loadProject(r){const v=view(r.id),token=++v.token,current=generation;if(!r.project){v.error='Choose an EGP.';renderRow(r.id);return;}v.loading='Reading process flows and programs…';v.error='';renderRow(r.id);try{const result=connectionCatalog&&model.egp?.sha256===r.project.sha256?{catalog:connectionCatalog}:await background({kind:'project',project:submission({egp:r.project,rows:[]}).egp});if(current!==generation||token!==v.token||!findRow(r.id))return;v.catalog=result.catalog;v.loading='';renderRow(r.id);}catch(e){if(current===generation&&token===v.token&&findRow(r.id)){v.error=e.message;v.loading='';renderRow(r.id);}}}
  async function loadProgram(r,p){const v=view(p.id),token=++v.token,current=generation;v.loading='Extracting code…';v.error='';renderPrograms(r);try{const result=await background({kind:'program',project:submission({egp:r.project,rows:[]}).egp,program_id:p.program_id});if(current!==generation||token!==v.token||!findRow(r.id)?.programs.includes(p))return;p.file=result.file;v.loading='';changed();renderPrograms(r);}catch(e){if(current===generation&&token===v.token&&findRow(r.id)?.programs.includes(p)){v.loading='';v.error=e.message;renderPrograms(r);}}}
  function analyzeInline(r){const v=view(r.id),token=++v.token,current=generation;clearTimeout(v.timer);v.loading=r.code.trim()?'Reading sections…':'';v.error='';updateStatus();if(!r.code.trim()){r.analysis=null;cardElement(r.id)?.querySelector('[data-unit]')?.remove();return;}v.timer=setTimeout(async()=>{try{const result=await host().request('/api/stream-analyze',{code:r.code});if(current!==generation||token!==v.token||!findRow(r.id))return;r.analysis=result;v.loading='';const root=cardElement(r.id);if(!root?.querySelector('[data-unit]'))renderRow(r.id);else updateUnitOptions(r);updateStatus();}catch(e){if(current===generation&&token===v.token&&findRow(r.id)){v.loading='';v.error=e.message;updateStatus();}}},300);}
  function startNew(){generation++;connectionToken++;for(const v of views.values())clearTimeout(v.timer);views.clear();model=empty(snapshot?.shared_work);started=true;shownFiles=false;connectionState='idle';connectionCatalog=null;pendingTemplate=null;revision++;$('stream-use-template').hidden=true;message('',false,'stream-import-status');render();loadConnection();$('stream-name').focus();}
  function applyTemplate(value){generation++;connectionToken++;for(const v of views.values())clearTimeout(v.timer);views.clear();model=clone(value);model.connection_mode=model.connection_mode||'chosen';started=true;shownFiles=true;pendingTemplate=null;revision++;$('stream-use-template').hidden=true;render();loadConnection(model.egp?.path||'',true);for(const r of model.rows){if(r.source_kind==='inline'&&!r.analysis)analyzeInline(r);if(r.source_kind==='egp')loadProject(r);}message('Template restored. All source choices and their order were kept.',false,'stream-import-status');}
  function execution(){const c=snapshot?.commands?.find(c=>c.id===commandId);$('stream-execution').hidden=!c;if(!c)return;const signature=JSON.stringify(c);if(signature===commandSignature)return;commandSignature=signature;$('stream-execution').innerHTML=`<div class="panel-header"><strong>${E(c.name)}</strong><button type="button" class="secondary" id="stream-inspect">Inspect run →</button></div><p>${host().badge(c.status)} ${host().timer(c)} ${c.estimate?E(host().expectedText(c.estimate)):''}</p><p class="hint">${E(c.message||'Submitting the frozen source through engine.py.')}</p>`;$('stream-inspect').addEventListener('click',()=>host().inspect(c.id));}
  function update(state,page){snapshot=state;if(page!=='stream')return;if(refreshShared){refreshShared=false;model.shared_work={...snapshot.shared_work,enabled:model.shared_work.enabled};$('stream-shared-work').checked=model.shared_work.enabled;changed();}connectionOptions();updateStatus();execution();}
  async function action(kind){const errors=documentIssues();if(errors.length){updateStatus();message(errors[0],true);return;}busy++;updateStatus();const current=generation,sentRevision=revision,sent=submission(model);message(kind==='run'?'Preparing the source snapshot…':kind==='estimate'?'Looking for previous timings…':kind==='source'?'Composing selected code…':'Preparing portable template JSON…');try{const result=await host().request('/api/stream-'+kind,{stream:sent});if(current!==generation)return;if(kind!=='run'&&sentRevision!==revision){message('The editor changed during preparation. Click the action again to use the current choices.');return;}if(kind==='estimate'){$('stream-estimate-result').textContent=host().expectedText(result);$('stream-estimate-result').title=result.basis;message(result.basis);}else if(kind==='run'){commandId=result.id;await host().refresh();execution();message('Run started. This submission is frozen; edits apply to the next run.');await host().inspect(result.id);}else{$('stream-artifacts').innerHTML=host().fileActions({path:result.path},kind==='source'?'SAS source':'template JSON');message(kind==='source'?'Source ready in card order.':'Portable template ready, including all source files and choices.');}}catch(e){if(current===generation)message(e.message,true);}finally{busy--;updateStatus();}}
  function sourceFocus(r){const root=cardElement(r.id);if(r.source_kind==='file')root?.querySelector('[data-stream-upload]').click();else if(r.source_kind==='inline')root?.querySelector('textarea').focus();else root?.querySelector('[data-stream-field="search"], [data-stream-action="browse-project"]').focus();}
  globalThis.PySASStream={update,helpers};render();
  $('stream-new').addEventListener('click',startNew);
  $('stream-add').addEventListener('click',()=>{const r=row();model.rows.push(r);changed();renderRows({card:r.id,action:'focus-source'});});
  $('stream-browse-egp').addEventListener('click',()=>$('stream-egp-upload').click());
  $('stream-egp-upload').addEventListener('change',event=>{chooseConnection(event.target.files[0]);event.target.value='';});
  $('stream-egp').addEventListener('change',()=>{model.connection_mode=$('stream-egp').value?'chosen':'auto';loadConnection($('stream-egp').value);});
  for(const [key,field] of [['stream-name','name'],['stream-server-program','server_program']])$(key).addEventListener('input',()=>{model[field]=$(key).value;changed();});
  for(const [key,field] of [['stream-html','export_html'],['stream-tables','export_tables'],['stream-consolidate','consolidate_tables']])$(key).addEventListener('change',()=>{model[field]=$(key).checked;changed();});
  $('stream-shared-work').addEventListener('change',()=>{model.shared_work={...(snapshot?.shared_work||model.shared_work),enabled:$('stream-shared-work').checked};changed();});
  $('stream-shared-settings').addEventListener('click',()=>{refreshShared=true;host().navigate?.('files');const group=$('settings-shared-work');group.open=true;group.scrollIntoView?.({block:'start'});$('shared-work-path').focus();});
  for(const kind of ['estimate','source','export','run'])$('stream-'+kind).addEventListener('click',()=>action(kind));
  $('stream-rows').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;const card=button.closest('[data-stream-row]'),r=findRow(card?.dataset.streamRow);if(!r)return;
    if(button.dataset.clearSections){const unit=findUnit(button.dataset.clearSections),available=analysisFor(unit)?.sections||[];unit.sections=chosenSections(unit).filter(s=>available.some(name=>name.toLowerCase()===s.toLowerCase()));unit.section='';changed();updateUnitOptions(unit);return;}
    if(button.dataset.programAction){const key=button.closest('[data-stream-program]').dataset.streamProgram,index=r.programs.findIndex(p=>p.id===key),p=r.programs[index],kind=button.dataset.programAction;if(kind==='retry'){loadProgram(r,p);return;}if(kind==='delete'){r.programs.splice(index,1);view(key).token++;}else{const next=index+(kind==='up'?-1:1);if(next>=0&&next<r.programs.length)[r.programs[index],r.programs[next]]=[r.programs[next],r.programs[index]];}changed();renderPrograms(r);return;}
    const kind=button.dataset.streamAction;
    if(kind==='focus-source'){sourceFocus(r);return;}
    if(kind==='delete'){const index=model.rows.indexOf(r);model.rows.splice(index,1);view(r.id).token++;changed();renderRows();const next=model.rows[Math.min(index,model.rows.length-1)];if(next)cardElement(next.id)?.querySelector('[data-stream-action="focus-source"]').focus();else $('stream-add').focus();return;}
    if(kind==='up'||kind==='down'){model.rows=move(model,r.id,kind==='up'?-1:1).rows.map(item=>findRow(item.id));changed();renderRows({card:r.id,action:kind});return;}
    if(kind==='browse-project'){card.querySelector('[data-project-upload]').click();return;}
    if(kind==='use-connection'){r.project=model.egp?clone(model.egp):null;r.programs=[];changed();loadProject(r);return;}
    if(kind==='read-project'){loadProject(r);return;}
    if(kind==='more-programs'){view(r.id).visible+=100;card.querySelector('.stream-program-catalog').innerHTML=catalogChoices(r);}
  });
  function fieldChanged(event){
    const input=event.target,element=input.closest('[data-stream-row]'),r=findRow(element?.dataset.streamRow);if(!r)return;
    if(input.hasAttribute('data-stream-upload')){chooseFile(input.files[0],r.id);input.value='';return;}
    if(input.hasAttribute('data-project-upload')){chooseFile(input.files[0],r.id,true);input.value='';return;}
    if(input.dataset.egpProgram){const selected=r.programs.find(p=>p.program_id===input.dataset.egpProgram);if(!input.checked){if(selected){r.programs=r.programs.filter(p=>p!==selected);view(selected.id).token++;}changed();renderPrograms(r);}else if(!selected){const original=view(r.id).catalog.programs.find(p=>p.id===input.dataset.egpProgram),p={id:id(),program_id:original.id,name:original.name,flow:original.flow,file:null,...selection()};r.programs.push(p);changed();loadProgram(r,p);}return;}
    const unit=findUnit(input.closest('[data-unit]')?.dataset.unit||r.id);
    if(input.dataset.unitSection){const names=analysisFor(unit)?.sections||[],chosen=new Set(chosenSections(unit).map(s=>s.toLowerCase()));if(input.checked)chosen.add(input.dataset.unitSection.toLowerCase());else chosen.delete(input.dataset.unitSection.toLowerCase());unit.sections=names.filter(name=>chosen.has(name.toLowerCase()));unit.section='';changed();return;}
    const key=input.dataset.unitField;
    if(key){unit[key]=key.startsWith('row_')?(input.value===''?null:Number(input.value)):input.value;changed();if(key==='mode')updateUnitOptions(unit);return;}
    const field=input.dataset.streamField;if(!field)return;
    if(field==='source_kind'){view(r.id).token++;view(r.id).loading='';view(r.id).error='';r.source_kind=input.value;changed();if(r.source_kind==='egp'){if(!r.project)r.project=model.egp?clone(model.egp):null;loadProject(r);}else if(r.source_kind==='inline'&&r.code.trim())analyzeInline(r);renderRow(r.id);return;}
    if(field==='flow'||field==='search'){view(r.id)[field]=input.value;view(r.id).visible=100;element.querySelector('.stream-program-catalog').innerHTML=catalogChoices(r);return;}
    r[field]=input.value;changed();if(field==='code')analyzeInline(r);if(field==='name')element.querySelector('.stream-source-title').textContent=r.name||'Inline code';
  }
  $('stream-rows').addEventListener('change',fieldChanged);
  $('stream-rows').addEventListener('input',event=>{if(['code','name','search'].includes(event.target.dataset.streamField))fieldChanged(event);else if(event.target.dataset.unitField?.startsWith('row_'))fieldChanged(event);});
  $('stream-rows').addEventListener('dragstart',event=>{if(!event.target.closest('.stream-grip'))return;const element=event.target.closest('[data-stream-row]');dragged=element.dataset.streamRow;event.dataTransfer?.setData('text/plain',dragged);if(event.dataTransfer)event.dataTransfer.effectAllowed='move';element.classList.add('dragging');});
  $('stream-rows').addEventListener('dragover',event=>{if(!dragged)return;const target=event.target.closest('[data-stream-row]');if(!target||target.dataset.streamRow===dragged)return;event.preventDefault();for(const element of $('stream-rows').querySelectorAll('.drop-before,.drop-after'))element.classList.remove('drop-before','drop-after');const rect=target.getBoundingClientRect(),after=event.clientY>rect.top+rect.height/2;target.classList.add(after?'drop-after':'drop-before');if(event.dataTransfer)event.dataTransfer.dropEffect='move';});
  $('stream-rows').addEventListener('drop',event=>{const target=event.target.closest('[data-stream-row]');if(!dragged||!target)return;event.preventDefault();const key=dragged;model.rows=reorder(model,key,target.dataset.streamRow,target.classList.contains('drop-after')).rows.map(item=>findRow(item.id));dragged=null;changed();renderRows({card:key,action:'focus-source'});});
  $('stream-rows').addEventListener('dragend',()=>{dragged=null;for(const element of $('stream-rows').querySelectorAll('.dragging,.drop-before,.drop-after'))element.classList.remove('dragging','drop-before','drop-after');});
  $('stream-restore').addEventListener('click',()=>$('stream-import').click());
  $('stream-use-template').addEventListener('click',()=>{if(pendingTemplate)applyTemplate(pendingTemplate);});
  $('stream-import').addEventListener('change',async event=>{const file=event.target.files[0];event.target.value='';if(!file)return;const current=generation,originalRevision=revision;message('Restoring template…',false,'stream-import-status');try{if(file.size>128*1024*1024)throw Error('Template JSON exceeds 128 MB.');const result=await upload(file,'/api/stream-import',text=>message(text,false,'stream-import-status'));if(current!==generation)return;if(result.stream?.format!==FORMAT||!Array.isArray(result.stream.rows))throw Error('The server returned an invalid template.');if(originalRevision!==revision){pendingTemplate=result.stream;$('stream-use-template').hidden=false;message('Template ready. Your editor changed while loading; choose Use imported template to replace it.',false,'stream-import-status');return;}applyTemplate(result.stream);}catch(e){if(current===generation)message(e.message,true,'stream-import-status');}});
})();

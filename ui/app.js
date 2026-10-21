"use strict";
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let state = null, page = "overview", selectedCommand = null, selectedPath = null, selectedPreview = null, inspectingFolder = false, pendingUnpack = null, polling = false, clockAnchor = null, renderSignature = null, bundlePathsInitialized = false, foldersInitialized = false, parametersInitialized = false, parameterLoading = false, parameterRevision = null, parameterLoadedName = "";
let inspectorTab="files", inspectorDetail=null, inspectorTrail=[], inspectorReturnScroll=0;
let copyTarget=null, copyBusy=false, detailsReturnFocus=null;
let sharedWorkInitialized=false, preferencesInitialized=false, inspectorPolling=false;
let runPlan=null, runPlanKey="", runPlanRequest=0, runPlanPending=null, runPlanTimer=null, singleLaunching=false;
let logView={path:null,kind:"all",offset:0,issue:null,revision:""}, logRequest=0;
let previewBuilderSignature=null, previewResult=null, previewResultId=null, previewLoadingId=null, previewPage=0, dictionarySignature=null, dictionaryOffset=0, dictionaryTimer=null, dictionaryRequest=0, dictionaryJob=null;
let selectedServerTable=null;
let serverCatalog=null, serverLoadedId=null, serverLoadingId=null, serverPage=0;
const monotonic = () => globalThis.performance?.now?.() ?? Date.now();
function syncClock(now) { if(clockAnchor===null)clockAnchor={server:now,local:monotonic()}; }
function clockSeconds() { return clockAnchor ? clockAnchor.server+(monotonic()-clockAnchor.local)/1000 : Date.now()/1000; }
function renderIfChanged() { if(globalThis.PySASKeys?.active)return; const {now,token,remaining,...stable}=state; const signature=JSON.stringify(stable);if(signature!==renderSignature){renderSignature=signature;render();} }
const active = c => ["RUNNING", "STOPPING", "CANCELLING"].includes(c.status);
const titles = {servers:"Servers & libraries", overview:"Workspace overview", runner:"Run", stream:"Run stream", graph:"Dependency graph", tools:"Projects", files:"Settings"};
function duration(seconds) { if (seconds == null || !Number.isFinite(Number(seconds))) return "—"; seconds = Math.max(0, Math.floor(seconds)); return `${String(Math.floor(seconds/3600)).padStart(2,"0")}:${String(Math.floor(seconds%3600/60)).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`; }
function elapsed(item) { return item.status === "UNKNOWN" ? "—" : active(item) && item.started ? duration((item.elapsed_base||0) + clockSeconds() - (item.active_started||item.started)) : duration(item.elapsed); }
function timer(item) { return `<span class="elapsed" ${active(item)&&item.started?`data-start="${Number(item.active_started||item.started)}" data-base="${Number(item.elapsed_base)||0}"`:""}>${elapsed(item)}</span>`; }
function date(value) { return value ? new Date(Number(value)*1000).toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}) : "—"; }
function badge(status, override) { const label = {PARTIAL:"Partial snapshot",CANCELLED:"Stopped by you",CANCELLING:"Stopping file",RUNNING:"Running",STOPPING:"Finishing files",STOPPED:"Stopped",STOPPED_ON_ERROR:"Stopped after error",SUCCESS:"Success",FAILED:"Failed",SAS_ERROR:"SAS error",EXPORT_ERROR:"Export error",TIMED_OUT:"Timed out",CONNECTION_LOST:"Connection lost",ALWAYS_RUN_DEFINITION:"Shared setup",PENDING:"Pending",BLOCKED_DEPENDENCY:"Blocked",SKIPPED_SUCCESS:"Skipped",SKIPPED_PREVIOUS:"Previously completed",UNKNOWN:"Unknown"}[status] || status; const cls = active({status})?"running": status.includes("SUCCESS")||status==="SKIPPED_PREVIOUS"?"success":/FAIL|ERROR|LOST|BLOCKED|TIMED_OUT/.test(status)?"error":["PENDING","PARTIAL"].includes(status)?"pending":""; return `<span class="badge ${cls}">${esc(override || label)}</span>`; }
function empty(title, text) { return `<div class="empty"><span class="empty-icon" aria-hidden="true">◇</span><strong>${esc(title)}</strong><p>${esc(text)}</p></div>`; }
function readOnlyTable(headers,rows,label){return table(headers,rows).replace('<div class="table-wrap">',`<div class="table-wrap" tabindex="0" role="region" aria-label="${esc(label)}">`);}
function table(headers, rows) { return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`; }
async function api(path, data) { const response = await fetch(path, data === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-PySAS-Token":state?.token || ""},body:JSON.stringify(data)}); const result = await response.json(); if (!response.ok) throw new Error(result.error || "Request failed"); return result; }
function error(message) { $("error").textContent = message; $("error").hidden = !message; }
function navigate(next) { if(next==="history")next="overview"; if($("details-dialog").open)closeInspector(true); if(next==="scheduler"){next="runner";$("run-mode").value="multiple";} page = titles[next] ? next : "overview"; document.querySelectorAll(".page").forEach(p=>p.hidden = p.id !== `page-${page}`); document.querySelectorAll(".nav").forEach(n=>{n.classList.toggle("active", n.dataset.page===page); if(n.dataset.page===page)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current");}); document.body?.classList.toggle("graph-page",page==="graph");$("page-title").textContent=titles[page]; history.replaceState(null,"",`#${page}`); runFlow(); render(); if(state)globalThis.PySASGraph?.update(state,page);globalThis.PySASStream?.update(state,page); }
function fillSelect(select, values) { const signature = JSON.stringify(values); if (select.dataset.signature === signature) return; const current=select.value, first=select.options[0]?.textContent || "Select a file"; select.innerHTML=`<option value="">${esc(first)}</option>` + values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join(""); if(values.includes(current))select.value=current; select.dataset.signature=signature; }
function files() { if(globalThis.PySASKeys?.active)return; fillSelect($("parameter-files"),state.parameters_settings?.files || []); if(state.folders && !foldersInitialized){for(const key of ["inputs","init","inbox"])$("folder-"+key).value=state.folders[key];foldersInitialized=true;}const settings=state.bundle_settings || {paths:[],last:""};fillSelect($("saved-bundle-path"),settings.paths);$("recent-code-folders").innerHTML=settings.paths.map(p=>`<option value="${esc(p)}"></option>`).join("");if(!bundlePathsInitialized){$("bundle-code-root").value=settings.last;$("saved-bundle-path").value=settings.paths.includes(settings.last)?settings.last:"";bundlePathsInitialized=true;} document.querySelectorAll("select[data-files]").forEach(s=>{const values=state.files.filter(f=>f.toLowerCase().endsWith("."+s.dataset.files));if(s.value&&!values.includes(s.value))values.push(s.value);fillSelect(s,values);}); fillSelect($("previous-schedule"),state.history.filter(h=>h.kind==="schedule"&&!active(h)&&!["UNKNOWN","SUCCESS"].includes(h.status)).map(h=>h.path)); }
function taskScope(task) {
  const parts=[];
  if(task.section)parts.push(`Section ${task.section}`);
  const first=Number(task.row_start)||0,last=Number(task.row_end)||0;
  if(first&&last)parts.push(first===last?`Row ${first}`:`Rows ${first}–${last}`);
  else if(first)parts.push(`From row ${first} to end`);
  else if(last)parts.push(`Rows 1–${last}`);
  else if(!task.section&&(Object.prototype.hasOwnProperty.call(task,"row_start")||Object.prototype.hasOwnProperty.call(task,"row_end")))parts.push("Whole program");
  return parts.join(" · ");
}
function expectedText(estimate) {
  if(!estimate || estimate.seconds == null)return "Expected: unknown — no matching successful history";
  if(Number(estimate.seconds)===0 && !estimate.unknown)return "Expected: no execution time (skipped tasks)";
  const seconds=Math.ceil(Number(estimate.seconds)/60)*60;
  const hours=Math.floor(seconds/3600), minutes=Math.floor(seconds%3600/60);
  const time=hours?`${hours}h${minutes?` ${minutes}m`:""}`:`${Math.max(1,minutes)}m`;
  return `Expected: ~${time}${estimate.unknown?"+":""}${estimate.unknown?` · ${estimate.unknown} task(s) unknown`:estimate.samples?` · ${estimate.samples} previous run(s)`:""}`;
}
function estimateMarkup(estimate) { return `<small class="expected-time" title="${esc(estimate?.basis || 'Historical estimate, accounting for dependencies and parallel tasks. Actual duration can vary. A + means only part of the work has known timings.')}">${esc(expectedText(estimate))}</small>`; }
function keyList(markup,label,key){return markup.replace('<div class="table-wrap">',`<div class="table-wrap" data-key-list data-keytip="${esc(key)}" tabindex="0" aria-label="${esc(label)}" aria-describedby="list-keyboard-help">`);}
function taskTable(tasks, commandId) { return keyList(table(["File / task","Status","Elapsed",""], tasks.map(t=>`<tr data-key-row><td>${esc(t.display_name||t.name)}${taskScope(t)?`<small class="task-scope">${esc(taskScope(t))}</small>`:""}${t.kind==="task"?`<small>${esc(t.key)}${t.depends_on?.length?` · After ${esc(t.depends_on.join(", "))}`:""}</small>`:""}${t.setup?.length?`<small>Shared setup: ${t.setup.map(s=>esc(s.program)+(taskScope(s)?` (${esc(taskScope(s))})`:"" )).join(" → ")}</small>`:""}${t.progress&&["RUNNING","CANCELLING"].includes(t.status)?`<small class="task-progress">${esc(t.progress)}</small>`:""}${t.message?`<small>${esc(t.message)}</small>`:""}</td><td>${badge(t.status)}</td><td>${timer(t)}${t.estimate?estimateMarkup(t.estimate):""}</td><td>${t.path?`<button class="subtle" data-path="${esc(t.path)}">Inspect →</button>`:`<button class="subtle" disabled title="Available when task output is created">Inspect →</button>`}${t.status==="RUNNING"&&t.can_cancel_file!==false&&t.path&&(t.command_id||commandId)?`<button class="subtle" title="Stop this file; partial SAS outputs may remain" data-cancel-command="${esc(t.command_id||commandId)}" data-cancel-key="${esc(t.key)}">Stop file</button>`:""}</td></tr>`)),"Tasks","T"); }
function live() { const tasks=state.commands.filter(active).flatMap(c=>Object.values(c.tasks).filter(t=>["RUNNING","CANCELLING"].includes(t.status)).map(t=>({...t,command_id:c.id}))); return tasks.length?taskTable(tasks):empty("No files running", "Start a program, a watcher, or a schedule to see live elapsed time here."); }
function taskRecords(history,commands){
  const key=value=>String(value||"").replace(/\\/g,"/").toLowerCase();
  const rows=new Map(history.map(h=>[key(h.path),{...h,search:h.path}])),seen=new Set();
  for(const c of commands){
    const path=c.path||((c.action==="run")?Object.values(c.tasks||{}).find(t=>t.path)?.path:null);
    const merge=path&&["run","schedule","continue","stream"].includes(c.action);
    if(merge&&seen.has(key(path)))continue;
    if(merge)seen.add(key(path));
    const existing=merge?rows.get(key(path)):null;
    const record={...existing,...c,command_id:c.id,path:path||null,kind:c.action,search:[path,c.action,...(c.args||[])].join(" "),updated:c.updated||c.finished||c.started};
    // Watcher sessions and their individual files are separate tasks.
    rows.set(merge?key(path):"command:"+c.id,record);
  }
  return Array.from(rows.values()).sort((a,b)=>(b.updated||b.started)-(a.updated||a.started));
}
function tasksTable(records){return records.length?keyList(table(["Task","Status","Last activity","Elapsed",""],records.map(h=>`<tr data-key-row><td>${esc(h.name)}<small>${esc(h.kind||"File")}</small></td><td>${badge(h.status)}</td><td>${date(h.updated||h.started)}</td><td>${timer(h)}</td><td><button class="subtle" ${h.path?`data-path="${esc(h.path)}"`:`data-command="${esc(h.command_id)}"`}>Inspect →</button>${h.command_id?scheduleStopControl(h):""}</td></tr>`)),"Tasks","T"):empty("No tasks yet","Programs, schedules and project commands will appear here.");}
function scheduleStopControl(command) {
  if(!command || !["schedule","continue"].includes(command.action) || !active(command))return "";
  const stopping=command.status==="STOPPING";
  return `<button class="subtle" data-stop-schedule="${esc(command.id)}" ${stopping?"disabled":""} title="Stop this entire schedule and its active files">${stopping?"Stopping schedule…":"Stop schedule"}</button>`;
}
function fileActions(target, label="file") {
  const query=Object.entries(target).map(([key,value])=>`${encodeURIComponent(key)}=${encodeURIComponent(value)}`).join("&");
  return `<span class="file-actions"><a class="subtle" href="/api/download?${query}" download>Download ${esc(label)} ↓</a><button type="button" class="subtle" data-copy-target="${esc(JSON.stringify(target))}" ${state?.windows?"":"disabled"} title="Copy the actual file to the Windows clipboard">Copy file</button><span class="hint file-action-status" role="status"></span></span>`;
}
function scheduleLogLink(command) { const path=command?.schedule_log||command?.run_log;return path?fileActions({path},command.schedule_log?"schedule log":"full run log"):""; }
function commandCards(commands, showTasks=false) { if(!commands.length)return empty("No command activity", "Commands launched from this workbench will appear here.");return commands.map(c=>`<article class="command-card"><div class="command-head"><div><strong>${esc(c.name)}</strong>${badge(c.status,c.status==="STOPPING"&&["schedule","continue"].includes(c.action)?"Stopping schedule":null)}${timer(c)}${c.estimate?estimateMarkup(c.estimate):""}<small>${date(c.started)}${c.code_root?` · ${esc(c.code_root)}`:""}${c.parameters?` · Parameters: ${esc(c.parameters.name)}`:""}${c.shared_work?` · Shared WORK: ${esc(c.shared_work.libref)}`:""}</small></div>${scheduleStopControl(c)}<button class="subtle" data-command="${esc(c.id)}">Console →</button></div>${c.parts>1?`<p class="hint">Continued in ${c.parts} parts · total active time excludes pauses${c.timing_estimated?" · earlier time estimated":""}. Final task outputs and consolidated log are in one folder.</p>`:""}${c.message?`<p class="empty-small">${esc(c.message)}</p>`:""}${c.egp_result&&c.path?`<p><button class="secondary" data-path="${esc(c.path)}">Inspect extracted programs →</button></p>`:""}${c.bundle_result?`<p class="hint">${c.bundle_result.added} added · ${c.bundle_result.changed} changed · ${c.bundle_result.deleted} deleted (other files retained)${c.bundle_result.backup?` <button class="subtle" data-open-backup="${esc(c.id)}" ${state?.windows?"":"disabled"}>Open backup folder</button>`:""}</p>`:""}${c.download?fileActions({command:c.id},"bundle"):""}${scheduleLogLink(c)}${showTasks&&Object.keys(c.tasks).length?taskTable(Object.values(c.tasks),c.id):""}</article>`).join(""); }
function focusIdentity(){const el=document.activeElement;return el?{el,id:el.id,data:JSON.stringify(el.dataset||{}),tag:el.tagName,list:el.closest?.("[data-key-list]")?.getAttribute("aria-label"),scope:el.closest?.("dialog,.page,.run-inspector")?.id}:null;}
function focusTarget(saved){return !saved?null:saved.el.isConnected?saved.el:saved.id?$(saved.id):saved.data!=="{}"?Array.from(document.querySelectorAll("button,a[href]")).find(el=>el.tagName===saved.tag&&JSON.stringify(el.dataset)===saved.data&&(!saved.scope||el.closest?.("dialog,.page,.run-inspector")?.id===saved.scope)&&(!saved.list||el.closest?.("[data-key-list]")?.getAttribute("aria-label")===saved.list)):null;}
function restoreFocus(saved){if(saved&&!saved.el.isConnected)focusTarget(saved)?.focus({preventScroll:true});}
function render(){const saved=focusIdentity();renderContents();restoreFocus(saved);globalThis.PySASKeys?.refreshLists();}
function renderContents() { if(!state||globalThis.PySASKeys?.active)return; $("saved-storage").textContent=state.saved_storage?`${storageSize(state.saved_storage.bytes)} saved data${state.saved_storage.export_bytes?` · ${storageSize(state.saved_storage.export_bytes)} prepared ZIPs`:""}`:"Measuring saved storage…";$("saved-storage").title=state.scan_errors?.storage?`Last measurement retained. ${state.scan_errors.storage}`:state.saved_storage?`Last measured ${date(state.saved_storage.measured)}`:"Storage is measured in the background."; if(!state)return;$("watch-inbox-path").textContent=state.folders?.inbox || "runner/inbox";$("keep-awake").checked=!!state.awake?.enabled;$("keep-awake").disabled=!state.awake?.supported;$("awake-status").textContent=state.awake?.error || (state.awake?.enabled?"On · Windows and display idle sleep are prevented.":state.awake?.supported?"Off · Normal power settings apply.":"Available on Windows. No mouse or keyboard input is generated.");uploadDestination(); const watcher=state.commands.find(c=>c.action==="watch"&&active(c)); $("running-count").textContent=state.commands.filter(active).flatMap(c=>Object.values(c.tasks).filter(t=>t.status==="RUNNING")).length; $("queue-count").textContent=state.queued.length; $("completed-count").textContent=state.history.filter(h=>!["RUNNING","UNKNOWN"].includes(h.status)).length; $("watcher-state").textContent=watcher?(watcher.status==="STOPPING"?"Finishing":"Watching"):"Stopped"; $("watcher-time").innerHTML=watcher?`${timer(watcher)} · ${watcher.status==="STOPPING"?"Waiting for active files":"Session elapsed"}`:"Ready when you are"; $("start-watch").disabled=!!watcher||!state.windows; $("stop-watch").disabled=!watcher||watcher.status==="STOPPING";
document.querySelectorAll("[data-watcher-monitor]").forEach(node=>{node.innerHTML=`<span><strong>Inbox watcher · ${watcher?esc(watcher.status==="STOPPING"?"finishing files":"watching"):"stopped"}</strong><small>${esc(state.folders?.inbox||"")} · ${state.queued.length} queued</small></span>${watcher&&watcher.status!=="STOPPING"?'<button class="secondary" data-watcher-stop>Stop after current files</button>':'<button class="subtle" data-watcher-settings>Watcher settings</button>'}`;});
if(page==="overview"){$("live-overview").innerHTML=live();const q=$("history-search").value.toLowerCase(),filter=$("history-filter").value;const records=taskRecords(state.history,state.commands).filter(h=>(h.name+" "+h.search).toLowerCase().includes(q)&&(filter==="all"||filter==="RUNNING"&&active(h)||filter==="errors"&&/FAIL|ERROR|LOST|BLOCKED|TIMED_OUT/.test(h.status)||h.status===filter));$("all-history").innerHTML=tasksTable(records);}
$("overview-stop-watch").disabled=!watcher||watcher.status==="STOPPING";
$("init-file-list").innerHTML=state.initialization_files?.length?state.initialization_files.map(p=>`<div class="queue-item"><code>${esc(p)}</code></div>`).join(""):'<p class="hint">No _*.sas files were found in the initialization folder or inbox.</p>';if(page==="runner"){$("live-runner").innerHTML=live();$("inbox").innerHTML=state.queued.length?state.queued.map((name,i)=>`<div class="queue-item"><span class="badge pending">${i+1}</span><span>${esc(name)}</span><small>Waiting · ${esc(expectedText(state.queued_estimates?.[name]))}</small></div>`).join(""):'<p class="hint">The inbox is empty. Add job .sas files through Files & folders or your configured inbox.</p>';}
if(page==="runner")$("schedule-activity").innerHTML=commandCards(state.commands.filter(c=>["schedule","continue"].includes(c.action)).slice(0,10),true);
if(page==="servers")renderServers();
if(page==="tools")$("tools-activity").innerHTML=commandCards(state.commands.filter(c=>c.action.startsWith("bundle-")||c.action.startsWith("egp-")).slice(0,10));
}

async function refresh(force=false) { if(polling)return; polling=true;try{state=await api(force?"/api/state?refresh=1":"/api/state");if($("error").textContent.startsWith("The local server is unavailable"))error("");syncClock(state.now);initializeSharedWork();renderRemaining();$("workspace").textContent=state.workspace;if(state.migration?.status==="WORKING")showMigration(state.migration);if(state.data_locations&&!$("data-tasks").dataset.initialized){$("data-tasks").value=state.data_locations.tasks;$("data-settings").value=state.data_locations.settings;$("data-tasks").dataset.initialized="1";}$("version").textContent=`v${state.version} · This computer only`;$("connection").textContent="Connected locally";$("connection-dot").className="online";const notices=[];if(state.startup_error)notices.push(state.startup_error);if(!state.windows)notices.push("SAS execution requires Windows with Enterprise Guide. You can use file tools and inspect history on this computer.");if(!state.openpyxl)notices.push("Install openpyxl for schedules and Excel table previews (see START_HERE.txt).");$("notice").textContent=notices.join(" ");$("notice").hidden=!notices.length;document.querySelectorAll(".sas-action").forEach(b=>b.disabled=!state.windows||b.dataset.blocked==="1");files();initializePreferences();runFlow();initializeParameters().catch(e=>{$("parameters-status").textContent=e.message;});renderIfChanged();globalThis.PySASGraph?.update(state,page);globalThis.PySASStream?.update(state,page);refreshInspector();}catch(e){$("connection").textContent="Connection lost";$("connection-dot").className="offline";error("The local server is unavailable. The app may have closed. Displayed job states may be stale.");}finally{polling=false;}}
async function refreshInspector(){
  if(inspectorPolling||!$("details-dialog").open||globalThis.PySASKeys?.active)return;
  inspectorPolling=true;
  try{if(selectedCommand)await showCommand(selectedCommand,true);else if(inspectingFolder&&selectedPath)await showPath(selectedPath,true);}
  catch(e){$("file-preview").textContent=e.message;}finally{inspectorPolling=false;}
}
function runFlow(){
  const override=$("run-init-mode").value==="override";
  $("run-init-file").hidden=!override;$("run-init").disabled=!override;$("run-init").required=override;
  renderRunInitialization();
  runPlanButton();
  const multiple=$("run-mode").value==="multiple";
  $("run-form").hidden=multiple;$("multiple-options").hidden=!multiple;
  $("single-options").hidden=!$("run-source").value;
  $("schedule-form").hidden=$("schedule-mode").value==="continue";
  $("continue-form").hidden=$("schedule-mode").value!=="continue";
}
function initializePreferences(){
  if(preferencesInitialized||!state?.preferences)return;
  const p=state.preferences;
  function savedSelection(field,value){if(value&&!Array.from(field.options).some(o=>o.value===value))field.insertAdjacentHTML("beforeend",`<option value="${esc(value)}">${esc(value)} (saved)</option>`);field.value=value||"";}
  savedSelection($("default-egp"),p.default_egp);savedSelection($("default-lib"),p.default_lib);
  for(const [key,value] of Object.entries(p.watcher||{})){
    const field=$("watch-form").elements?.[key];if(!field)continue;
    if(field.type==="checkbox")field.checked=value===true;else if(field.tagName==="SELECT")savedSelection(field,value);else field.value=value;
  }
  preferencesInitialized=true;
}
function formData(form) { const data=Object.fromEntries(new FormData(form));form.querySelectorAll('input[type="checkbox"]').forEach(c=>data[c.name]=c.checked);return data; }
function runPlanSelection(data){return {program:data.program||"",initialization_mode:data.initialization_mode||"default",lib:data.initialization_mode==="override"?data.lib||"":"",use_parameters:data.use_parameters===true,...(data.use_parameters?{parameters_name:data.parameters_name,parameters_text:data.parameters_text}:{})};}
function runPlanSignature(data){return JSON.stringify([runPlanSelection(data),state?.folders,state?.preferences?.default_lib,state?.initialization_files]);}
function runInitializationMarkup(plan){
  const description=plan.mode==="override"?`One initialization override replaces the shared _*.sas list: ${plan.override}`:`Shared initialization, alphabetically. Folders: ${plan.folders.join(" · ")}`;
  return `<p class="hint">${esc(description)}</p>${plan.files.some(f=>f.role==="initialization")?"":'<p class="hint">No initialization files found. Check Shared initialization and Watcher inbox in Settings.</p>'}<ol>${plan.files.map(f=>`<li><strong>${esc(f.name)}</strong><span class="badge">${esc({initialization:"Initialization",parameters:"Parameters",program:"Program"}[f.role]||f.role)}</span><code>${esc(f.path||"Current parameter editor contents")}</code></li>`).join("")}</ol>`;
}
function runPlanButton(){const button=$("run-submit");button.dataset.blocked=runPlan&&!runPlanPending?"0":"1";button.disabled=!state?.windows||button.dataset.blocked==="1"||singleLaunching;}
async function updateRunPlan(data,force=false){
  const signature=runPlanSignature(data);
  if(!force&&signature===runPlanKey)return runPlanPending||runPlan;
  const request=++runPlanRequest;runPlanKey=signature;runPlan=null;
  if(!data.program){runPlanPending=null;$("run-initialization").textContent="Select a program to see exactly which files will be submitted.";$("run-plan-status").textContent="";runPlanButton();return null;}
  $("run-initialization").textContent="Checking the selected files…";$("run-plan-status").textContent="";
  runPlanPending=(async()=>{
    try{const plan=await api("/api/run-plan",runPlanSelection(data));if(request!==runPlanRequest)return null;runPlan=plan;$("run-initialization").innerHTML=runInitializationMarkup(plan);$("run-plan-status").textContent="Ready. These files will be prepended in this order; their contents are checked again at launch.";return plan;}
    catch(e){if(request===runPlanRequest){$("run-initialization").textContent="Execution plan unavailable.";$("run-plan-status").textContent=e.message;}return null;}
    finally{if(request===runPlanRequest){runPlanPending=null;runPlanButton();}}
  })();runPlanButton();return runPlanPending;
}
function renderRunInitialization(force=false){if(state)return updateRunPlan(formData($("run-form")),force);}
$("run-init-mode").addEventListener("change",runFlow);
$("run-init").addEventListener("change",()=>renderRunInitialization());
$("refresh-run-plan").addEventListener("click",()=>renderRunInitialization(true));
for(const id of ["parameter-name","parameter-text"]){$(id).addEventListener("input",()=>{clearTimeout(runPlanTimer);runPlan=null;runPlanButton();runPlanTimer=setTimeout(()=>renderRunInitialization(true),200);});}
async function launch(data, form) {
  const single=data.action==="run";
  if(single&&singleLaunching)return;
  if(single&&data.use_parameters&&parameterLoading){$("run-plan-status").textContent="Wait for the parameter file to finish loading.";return;}
  const button=form?.querySelector('[type="submit"]');if(button)button.disabled=true;if(single)singleLaunching=true;error("");
  try{
    if(single){const previewed=runPlan?.revision;const plan=await updateRunPlan(data,true);if(!plan)return;
      if(!previewed||previewed!==plan.revision){$("run-plan-status").textContent="The files changed. Review the updated list, then click Run program again. No code was submitted.";return;}
      if(form&&runPlanSignature(formData(form))!==runPlanSignature(data)){$("run-plan-status").textContent="The selection changed while checking. Review the file list, then run again.";await renderRunInitialization(true);return;}
      data={...data,plan_revision:plan.revision};
    }
    const result=await api("/api/launch",data);await refresh();await showCommand(result.id);
  }catch(e){if(single){$("run-plan-status").textContent=e.message;runPlan=null;}else error(e.message);}
  finally{if(single){singleLaunching=false;runPlanButton();}else if(button)button.disabled=false;}
}
function bindForm(id, action) { $(id).addEventListener("submit",event=>{event.preventDefault();launch({...formData(event.currentTarget),action},event.currentTarget);}); }
function putMarkup(id,html){const node=$(id);if(node.dataset.markup===html)return;const saved=focusIdentity();node.innerHTML=html;node.dataset.markup=html;restoreFocus(saved);globalThis.PySASKeys?.refreshLists();}
function rememberInspector(){if(!$("details-dialog").open)return;inspectorTrail.push({path:selectedPath,command:selectedCommand,tab:inspectorTab,preview:selectedPreview,scroll:$("details-dialog").scrollTop});}
function openDialog(title){
  resetLogSummary();$("copy-log-text").hidden=true;
  if(!$("details-dialog").open){detailsReturnFocus=focusIdentity();inspectorReturnScroll=globalThis.scrollY||0;inspectorTrail=[];}
  inspectorDetail=null;inspectorTab="files";setInspectorTab("files");
  for(const id of ["rename-run","open-run-folder","download-folder"])$(id).hidden=false;
  for(const id of ["open-run-folder","download-folder","run-display-name"])$(id).disabled=true;
  $("rename-run").querySelectorAll("button,input").forEach(b=>b.disabled=true);
  $("inspector-execution-controls").innerHTML="";$("inspector-result").innerHTML="";$("inspector-status").textContent="";$("listing-notice").hidden=true;
  delete $("file-list").dataset.markup;delete $("detail-tasks").dataset.markup;setCopyTarget(null);
  $("detail-title").textContent=title;$("detail-tasks").innerHTML="";$("file-list").innerHTML="";$("preview-name").textContent="Select an output";$("download").hidden=true;$("file-preview").innerHTML="";$("folder-export-status").innerHTML="";delete $("folder-export-status").dataset.exportSignature;
  $("details-dialog").open=true;$("details-dialog").hidden=false;document.body?.classList.add("inspector-open");$("details-dialog").scrollTop=0;$("close-details").focus?.({preventScroll:true});
}
async function applyInspector(detail,updating){
  inspectorDetail=detail;
  if(!updating){inspectorTab=detail.status==="SUCCESS"?"files":"logs";$("detail-title").textContent=detail.name||"Task";$("run-display-name").value=detail.name||"";}
  const command=state.commands.find(c=>c.id===detail.command_id),task=detail.self_task;
  $("inspector-result").innerHTML=badge(detail.status||"UNKNOWN")+((task||command)?timer(task||command):"");
  putMarkup("inspector-execution-controls",task&&active(task)&&task.can_cancel_file!==false&&command?`<button class="secondary" data-cancel-command="${esc(command.id)}" data-cancel-key="${esc(task.key)}">Stop file</button>`:scheduleStopControl(command)||(command?.action==="watch"&&active(command)?`<button class="secondary" data-watcher-stop ${command.status==="STOPPING"?"disabled":""}>Stop after current files</button>`:""));
  $("rename-run").querySelectorAll("button,input").forEach(b=>b.disabled=!(detail.can_rename||detail.whole_run));
  $("open-run-folder").disabled=!state.windows||!detail.folder_path;
  $("open-run-folder").dataset.path=detail.folder_path||"";
  $("download-folder").disabled=!detail.export_scope||active(detail);
  $("download-folder").dataset.exportScope=detail.export_scope||"run";$("download-folder").dataset.exportPath=detail.export_path||"";
  const prepared=folderExports.get(exportKey(detail.export_scope,detail.export_path));if(prepared){showExport(prepared,$("folder-export-status"));if(prepared.status==="WORKING")$("download-folder").disabled=true;}
  $("listing-notice").hidden=!detail.listing_limited;$("listing-notice").textContent="Showing the first 1,000 files. Open the folder or create its ZIP for all files.";
  putMarkup("detail-tasks",(detail.stop_control||"")+taskTable(detail.tasks||[]));setInspectorTab(inspectorTab);
  if(inspectorTab==="tasks")return;
  const visible=inspectorFiles(detail.files,inspectorTab),first=visible.find(f=>f.path===selectedPreview)||visible[0];
  if(first)await preview(first.path,updating&&first.path===selectedPreview);
  else{selectedPreview=null;resetLogSummary();setCopyTarget(null);$("download").hidden=true;$("copy-log-text").hidden=true;$("preview-name").textContent=inspectorTab==="logs"?"Logs":"Outputs";$("file-preview").innerHTML='<p class="empty-small">No files in this view yet.</p>';}
}
async function showCommand(identifier,updating=false){
  if(!updating){rememberInspector();openDialog("Command");inspectingFolder=false;selectedPreview=null;selectedCommand=identifier;selectedPath=null;}
  try{const detail=await api(`/api/command-details?id=${encodeURIComponent(identifier)}`);if(selectedCommand!==identifier)return;$("detail-meta").textContent=detail.description||"";await applyInspector(detail,updating);}catch(e){$("file-preview").textContent=e.message;}
}
async function showPath(path,updating=false){
  if(!updating){rememberInspector();openDialog(path.split(/[\\/]/).pop());selectedPreview=null;selectedCommand=null;selectedPath=path;inspectingFolder=true;$("detail-meta").textContent=path;}
  try{const detail=await api(`/api/details?path=${encodeURIComponent(path)}`);if(selectedPath!==path||selectedCommand)return;await applyInspector(detail,updating);}catch(e){$("file-preview").textContent=e.message;}
}
async function preview(path, updating=false) { $("copy-log-text").hidden=!/\.log$/i.test(path);if(!updating||logView.path!==path){setCopyTarget(null);resetLogSummary(path);}selectedPreview=path;const panel=$("file-preview"),scroll=panel.scrollTop,atEnd=panel.scrollHeight-panel.scrollTop-panel.clientHeight<80; $("preview-name").textContent=path.split(/[\\/]/).pop();$("download").href=`/api/download?path=${encodeURIComponent(path)}`;$("download").hidden=false;setCopyTarget(path);document.querySelectorAll(".file-item").forEach(b=>b.classList.toggle("selected",b.dataset.preview===path));if(!updating)$("file-preview").textContent="Loading preview…";const expected=$("download").href;try{const result=await api(`/api/preview?path=${encodeURIComponent(path)}`);if(selectedPreview!==path || $("download").href!==expected)return;if(result.modified)$("preview-name").textContent=`${path.split(/[\\/]/).pop()} · updated ${new Date(result.modified*1000).toLocaleTimeString()}`;if(/\.log$/i.test(path)){await refreshLogSummary(path);if(logView.path===path&&logView.issue!==null)return;}
if(selectedPreview!==path)return;
if(updating&&!result.sheets&&panel.dataset.output===result.text)return;if(result.sheets){$("file-preview").innerHTML=`<p class="hint">${esc(result.note)}</p>`+result.sheets.map(sheet=>`<h3>${esc(sheet.name)}</h3>${table((sheet.rows[0]||[]).map(esc),sheet.rows.slice(1).map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`))}`).join("");}else{panel.dataset.output=result.text;$("file-preview").innerHTML=`<pre>${result.text.split("\n").map(line=>/^\s*ERROR/i.test(line)?`<span class="log-error">${esc(line)}</span>`:/^\s*WARNING/i.test(line)?`<span class="log-warning">${esc(line)}</span>`:esc(line)).join("\n")}</pre>`;}if(updating)panel.scrollTop=atEnd?panel.scrollHeight:scroll;}catch(e){$("file-preview").textContent=e.message;}}
function toolFields(){const bundle=$("bundle-action").value;$("bundle-input-label").hidden=bundle==="bundle-pack";$("bundle-output-label").hidden=bundle!=="bundle-pack";$("recursive-label").hidden=bundle!=="bundle-pack";const egp=$("egp-action").value;$("egp-output-caption").textContent=egp==="egp-extract"?"Output folder (optional)":"Output EGP path (optional)";$("egp-source-label").hidden=egp!=="egp-pack";$("egp-output-label").hidden=egp==="egp-inspect";}
document.addEventListener("click",async e=>{const button=e.target.closest("button");if(!button)return;if(button.dataset.page)navigate(button.dataset.page);if(button.dataset.go)navigate(button.dataset.go);if(button.dataset.command)await showCommand(button.dataset.command);if(button.dataset.path)await showPath(button.dataset.path);if(button.dataset.preview)await preview(button.dataset.preview);});
bindForm("run-form","run");bindForm("watch-form","watch");bindForm("schedule-form","schedule");bindForm("continue-form","continue");
$("stop-watch").addEventListener("click",async()=>{const watcher=state.commands.find(c=>c.action==="watch"&&active(c));if(!watcher)return;try{await api("/api/stop",{id:watcher.id});await refresh();}catch(e){error(e.message);}});
$("bundle-form").addEventListener("submit",e=>{e.preventDefault();const data=formData(e.currentTarget);if(data.action==="bundle-unpack"){pendingUnpack=data;$("unpack-target").textContent=`Restore into: ${data.code_root || state.workspace}`;$("confirm-dialog").showModal();}else launch(data,e.currentTarget);});
$("confirm-unpack").addEventListener("click",()=>{$("confirm-dialog").close();launch(pendingUnpack,$("bundle-form"));pendingUnpack=null;});$("cancel-unpack").addEventListener("click",()=>{$("confirm-dialog").close();pendingUnpack=null;});
$("egp-form").addEventListener("submit",e=>{e.preventDefault();const data=formData(e.currentTarget);if(data.action==="egp-pack")data.template=data.project;launch(data,e.currentTarget);});
$("preview-schedule").addEventListener("click",async()=>{const path=$("schedule-form").elements.workbook.value;if(!path){error("Select a schedule workbook first.");return;}inspectingFolder=false;selectedCommand=null;selectedPath=path;openDialog("Schedule workbook");$("detail-meta").textContent=path;await preview(path);});
function closeInspector(all=false){
  if(!all&&inspectorTrail.length){const saved=inspectorTrail.pop();const load=saved.command?showCommand(saved.command,true):showPath(saved.path,true);selectedPath=saved.path;selectedCommand=saved.command;selectedPreview=saved.preview;inspectorTab=saved.tab;inspectingFolder=!!saved.path;load.then(()=>{$("detail-title").textContent=inspectorDetail?.name||"Task";$("run-display-name").value=inspectorDetail?.name||"";$("detail-meta").textContent=saved.path||inspectorDetail?.description||"";$("details-dialog").scrollTop=saved.scroll;});return;}
  document.body?.classList.remove("inspector-open");$("details-dialog").open=false;$("details-dialog").hidden=true;selectedCommand=null;selectedPath=null;selectedPreview=null;resetLogSummary();
  globalThis.scrollTo?.(0,inspectorReturnScroll);focusTarget(detailsReturnFocus)?.focus({preventScroll:true});detailsReturnFocus=null;inspectorTrail=[];globalThis.PySASKeys?.refreshLists();
}
$("close-details").addEventListener("click",()=>closeInspector());
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&$("details-dialog").open&&!globalThis.PySASKeys?.active&&!document.querySelector("dialog[open]")){e.preventDefault();closeInspector();}});
$("bundle-action").addEventListener("change",toolFields);$("egp-action").addEventListener("change",toolFields);$("history-search").addEventListener("input",render);$("history-filter").addEventListener("change",render);$("refresh").addEventListener("click",()=>{error("");refresh(true);});
function tick(){renderRemaining();$("clock").textContent=new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});if($("connection-dot").className!=="online")return;document.querySelectorAll("[data-start]").forEach(el=>{const value=duration((Number(el.dataset.base)||0)+clockSeconds()-Number(el.dataset.start));if(el.textContent!==value)el.textContent=value;});}
toolFields();navigate(location.hash.slice(1)||"overview");refresh();tick();setInterval(refresh,2000);setInterval(tick,200);

// Optional read-only integration for browsers that expose a page tool registry.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  window.addEventListener("pagehide", () => lifecycle.abort(), {once:true});
  try {
    Promise.resolve(document.modelContext.registerTool({
      name: "inspect_pysas_runs",
      title: "Inspect PySAS runs",
      description: "Read running filenames, job statuses, elapsed seconds, and recent completed runs in this local workspace. Does not start or stop jobs.",
      inputSchema: {type:"object", properties:{limit:{type:"integer",minimum:1,maximum:50}}, additionalProperties:false},
      annotations: {readOnlyHint:true, untrustedContentHint:true},
      async execute(input) {
        if (!input || typeof input!=="object" || Array.isArray(input) || Object.keys(input).some(k=>k!=="limit")) throw new Error("Expected an object with an optional limit.");
        const limit=input.limit ?? 10;
        if(!Number.isInteger(limit)||limit<1||limit>50)throw new Error("Limit must be between 1 and 50.");
        const snapshot=await api("/api/state");
        return {running:snapshot.commands.filter(active).flatMap(c=>Object.values(c.tasks).filter(t=>t.status==="RUNNING").map(t=>({name:t.name,status:t.status,elapsed_seconds:Math.max(0,snapshot.now-t.started)}))),recent:snapshot.history.slice(0,limit).map(h=>({name:h.name,status:h.status,elapsed_seconds:h.elapsed,path:h.path}))};
      }
    },{signal:lifecycle.signal})).catch(()=>{});
  } catch (_) { /* Standard browsers work without a tool registry. */ }
}

$("saved-bundle-path").addEventListener("change",()=>{$("bundle-code-root").value=$("saved-bundle-path").value;$("bundle-path-status").textContent="Pack, verify and unpack will use this code folder.";});
$("save-bundle-path").addEventListener("click",async()=>{try{const settings=await api("/api/bundle-paths",{operation:"save",path:$("bundle-code-root").value});$("bundle-code-root").value=settings.last;state.bundle_settings=settings;files();$("saved-bundle-path").value=settings.last;$("bundle-path-status").textContent="Path saved. It will be available next time you open the workbench.";}catch(e){error(e.message);}});
$("remove-bundle-path").addEventListener("click",async()=>{const path=$("bundle-code-root").value;if(!path)return;try{state.bundle_settings=await api("/api/bundle-paths",{operation:"remove",path});files();$("bundle-path-status").textContent="Saved shortcut removed. No folders or files were deleted.";}catch(e){error(e.message);}});

function uploadDestination(){const target=$("upload-target").value || "inputs";$("upload-folder").textContent="Destination: "+(target==="bundle"?($("bundle-code-root").value||state?.workspace||"Workspace"):state?.folders?.[target]||"Workspace");}
$("upload-target").addEventListener("change",uploadDestination);
$("folders-form").addEventListener("submit",async e=>{e.preventDefault();error("");try{const saved=await api("/api/folders",formData(e.currentTarget));state.folders=saved;for(const key of ["inputs","init","inbox"])$("folder-"+key).value=saved[key];$("folders-status").textContent="Folder settings saved.";await refresh();}catch(e){error(e.message);}});
$("keep-awake").addEventListener("change",async()=>{try{state.awake=await api("/api/awake",{enabled:$("keep-awake").checked});render();}catch(e){error(e.message);$("keep-awake").checked=!!state?.awake?.enabled;}});
function uploadFile(file,target){return new Promise((resolve,reject)=>{const request=new XMLHttpRequest();const query=new URLSearchParams({target,name:file.name});if(target==="bundle")query.set("code_root",$("bundle-code-root").value);request.open("POST","/api/upload?"+query);request.setRequestHeader("X-PySAS-Token",state.token);request.upload.onprogress=e=>{if(e.lengthComputable)$("upload-progress").value=e.loaded/e.total*100;};request.onload=()=>{let result;try{result=JSON.parse(request.responseText);}catch(_){reject(new Error("The upload server returned an invalid response."));return;}if(request.status>=200&&request.status<300)resolve(result);else reject(new Error(result.error||"Upload failed"));};request.onerror=()=>reject(new Error("The upload connection was interrupted."));request.send(file);});}
$("upload-form").addEventListener("submit",async e=>{e.preventDefault();const files=Array.from($("upload-files").files);if(!files.length)return;const target=$("upload-target").value;const button=e.currentTarget.querySelector('[type="submit"]');button.disabled=true;$("upload-progress").hidden=false;const outcomes=[];try{for(const file of files){$("upload-status").textContent=`Uploading ${file.name}…`;$("upload-progress").value=0;try{await uploadFile(file,target);outcomes.push(`${file.name}: uploaded`);}catch(e){outcomes.push(`${file.name}: ${e.message}`);}}$("upload-status").textContent=outcomes.join("\n");await refresh();}finally{button.disabled=false;$("upload-progress").hidden=true;}});

$("quit-app").addEventListener("click",async()=>{try{await api("/api/quit",{});$("notice").hidden=false;$("notice").textContent="PySAS is closing after active jobs finish. You can close this window.";}catch(e){error(e.message);}});

document.addEventListener("click",async event=>{const button=event.target.closest("[data-cancel-command]");if(!button)return;button.disabled=true;try{await api("/api/cancel-file",{id:button.dataset.cancelCommand,key:button.dataset.cancelKey});await refresh();}catch(e){error(e.message);button.disabled=false;}});

document.addEventListener("click",async event=>{const button=event.target.closest("[data-stop-schedule]");if(!button)return;button.disabled=true;try{await api("/api/stop",{id:button.dataset.stopSchedule});await refresh();}catch(e){error(e.message);button.disabled=false;}});


document.addEventListener("click", async event=>{
  const button=event.target.closest("[data-estimate-form]");if(!button)return;
  const form=$(button.dataset.estimateForm), output=$(button.dataset.estimateForm+"-estimate");
  button.disabled=true;output.textContent="Reading saved timings…";
  try{const result=await api("/api/estimate",{...formData(form),action:button.dataset.estimateAction});
    output.innerHTML=`<strong>${esc(expectedText(result))}</strong><p>Based on matching program names and sections/rows in successful runs. Changed code, data volume and server load can change timings.</p>`+(result.tasks?table(["Program / selection","Expected"],result.tasks.map(t=>`<tr><td>${esc(t.program)}<small>${esc(taskScope(t))}</small></td><td>${t.skip?"Skipped after dependencies":esc(expectedText(t.estimate))}</td></tr>`)):"");
  }catch(e){output.textContent=e.message;}finally{button.disabled=false;}
});
$("restore-form").addEventListener("submit",async event=>{
  event.preventDefault();const file=$("restore-file").files[0];if(!file)return;
  const button=event.currentTarget.querySelector('[type="submit"]');button.disabled=true;$("restore-progress").hidden=false;$("restore-status").textContent="Uploading backup…";
  try{
    const result=await new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open("POST","/api/restore");request.setRequestHeader("X-PySAS-Token",state.token);
      request.upload.onprogress=e=>{if(e.lengthComputable)$("restore-progress").value=e.loaded/e.total*100;};
      request.upload.onload=()=>{$("restore-status").textContent="Checking and restoring saved data…";};
      request.onload=()=>{try{const result=JSON.parse(request.responseText);if(request.status===200)resolve(result);else reject(new Error(result.error||"Restore failed"));}catch(e){reject(e);}};
      request.onerror=()=>reject(new Error("Connection interrupted. Check history before retrying the restore."));request.send(file);
    });
    foldersInitialized=false;bundlePathsInitialized=false;parametersInitialized=false;sharedWorkInitialized=false;preferencesInitialized=false;await refresh(true);
    $("restore-status").textContent=`Restored ${result.runs} run folders and ${result.commands} commands. Existing runs were preserved.`+(result.missing_folders.length?` Review folder settings: ${result.missing_folders.join(", ")} used the new workspace defaults because their old locations are unavailable.`:"");
  }catch(e){$("restore-status").textContent=e.message;}finally{button.disabled=false;$("restore-progress").hidden=true;}
});


function parameterFields(){ $("parameters-editor").hidden=!$("use-parameters").checked;renderRunInitialization(); }
function putParameters(result, saved){
  $("parameter-name").value=result.name;$("parameter-text").value=result.text;
  parameterLoadedName=saved?result.name:"";parameterRevision=saved?result.revision:null;
  $("parameter-files").value=saved?result.name:"";
  $("use-parameters").checked=true;parameterFields();
  $("parameters-status").textContent=saved?"Loaded saved parameters. Edits are used by your next run; Save updates the reusable file.":"Loaded into the editor. The original file is unchanged. Save to keep a reusable copy.";
}
function parameterBusy(busy){
  parameterLoading=busy;
  for(const id of ["parameter-text","parameter-name","load-parameters","save-parameters","import-parameters"])$(id).disabled=busy;
}
async function loadParameters(name, remember=false){
  if(parameterLoading)return;parameterBusy(true);
  try{const result=remember?await api("/api/parameters/select",{name}):await api(`/api/parameters?name=${encodeURIComponent(name)}`);putParameters(result,true);return true;}
  catch(e){$("parameters-status").textContent=e.message;}
  finally{parameterBusy(false);}
}
async function initializeParameters(){
  if(parametersInitialized)return;parametersInitialized=true;
  const settings=state.parameters_settings || {};
  const loaded=settings.last && settings.files?.includes(settings.last)?await loadParameters(settings.last):false;
  $("use-parameters").checked=!!settings.enabled && !!loaded;parameterFields();
}
$("use-parameters").addEventListener("change",parameterFields);
$("load-parameters").addEventListener("click",()=>{const name=$("parameter-files").value;if(name)loadParameters(name,true);else $("parameters-status").textContent="Choose a saved file, or enter new code below.";});
$("parameter-text").addEventListener("input",()=>{$("parameters-status").textContent="Editor changed. Run uses these edits; Save updates your reusable file.";});
$("save-parameters").addEventListener("click",async()=>{
  if(parameterLoading)return;
  const button=$("save-parameters");button.disabled=true;
  const name=$("parameter-name").value, text=$("parameter-text").value;
  try{const result=await api("/api/parameters/save",{name,text,revision:name.toLowerCase()===parameterLoadedName.toLowerCase()?parameterRevision:null});
    parameterLoadedName=result.name;parameterRevision=result.revision;
    // A refresh must not replace text typed while the save was in flight.
    await refresh();$("parameter-files").value=result.name;
    $("parameters-status").textContent=$("parameter-text").value===text?"Parameter file saved. It is available next time you open PySAS.":"Saved the earlier text. Your latest editor changes are still unsaved.";
  }catch(e){$("parameters-status").textContent=e.message;}finally{button.disabled=false;}
});
$("import-parameters").addEventListener("change",async()=>{
  const input=$("import-parameters"),file=input.files[0];if(!file||parameterLoading)return;
  parameterBusy(true);$("parameters-status").textContent="Loading parameters…";
  try{
    if(file.size>128*1024)throw new Error("Parameter files must be 128 KB or smaller.");
    const response=await fetch(`/api/parameters/import?name=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"X-PySAS-Token":state.token},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||"Could not load this file.");
    putParameters(result,false);
  }catch(e){$("parameters-status").textContent=e.message;}
  finally{parameterBusy(false);input.value="";}
});

function storageSize(bytes, unknown=0) {
  if(bytes==null || (unknown>0 && !bytes))return "Unknown";
  const units=["B","KB","MB","GB","TB","PB"];let size=bytes, unit=0;
  while(size>=1024 && unit<units.length-1){size/=1024;unit++;}
  return `${unknown>0?"At least ":""}${size.toLocaleString(undefined,{maximumFractionDigits:unit?2:0})} ${units[unit]}`;
}
function catalogRows(catalog, library, query, sort) {
  const q=query.trim().toLowerCase();
  return catalog.tables.filter(t=>(!library || t.libname===library) && `${t.libname}.${t.name} ${t.label||""}`.toLowerCase().includes(q)).sort((a,b)=>{
    if(sort==="size")return (b.bytes??-1)-(a.bytes??-1) || a.name.localeCompare(b.name);
    if(sort==="modified")return (b.modified||"").localeCompare(a.modified||"") || a.name.localeCompare(b.name);
    return `${a.libname}.${a.name}`.localeCompare(`${b.libname}.${b.name}`);
  });
}
async function renderServers() {
  const snapshots=state.server_snapshots || [], select=$("server-snapshots"), previous=select.value;
  select.innerHTML='<option value="">Latest available snapshot</option>'+snapshots.filter(s=>s.snapshot).map(s=>`<option value="${esc(s.id)}">${esc(s.label)} · ${esc(date(s.started))}${s.partial?" · Partial":""}</option>`).join("");select.value=previous;
  const selected=snapshots.find(s=>s.id===select.value && s.snapshot) || snapshots.find(s=>s.snapshot);
  $("server-activity").innerHTML=commandCards(state.commands.filter(c=>c.action==="server-refresh").slice(0,3),true);
  $("server-reuse").disabled=!selected;$("server-download").hidden=!selected;$("server-copy").hidden=!selected;$("server-copy").disabled=!state.windows;
  if(!selected){serverCatalog=null;serverLoadedId=null;serverLoadingId=null;$("server-library-list").innerHTML=empty("No server snapshot yet","Click Discover libraries to list the assignments for your automatic EGP connection.");$("server-table-list").innerHTML="";$("server-summary").textContent="";$("server-issues").innerHTML="";$("server-snapshot-status").textContent="No readable snapshot has been saved.";return;}
  $("server-download").href=`/api/download?path=${encodeURIComponent(selected.snapshot)}`;$("server-copy").dataset.copyTarget=JSON.stringify({path:selected.snapshot});
  if(serverLoadedId!==selected.id){
    if(serverLoadingId===selected.id)return;
    const id=selected.id;serverLoadingId=id;serverCatalog=null;serverLoadedId=null;$("server-library-list").innerHTML="";$("server-table-list").innerHTML="";$("server-summary").textContent="";$("server-issues").innerHTML="";$("server-snapshot-status").textContent="Loading saved catalog…";
    try{const catalog=await api(`/api/server-catalog?id=${encodeURIComponent(id)}`);if(serverLoadingId!==id)return;
      if(selectedServerTable&&!catalog.tables.some(t=>t.libname===selectedServerTable.libname&&t.name===selectedServerTable.name))selectedServerTable=null;
      serverCatalog=catalog;serverLoadedId=id;serverPage=0;
      fillSelect($("server-library"),catalog.libraries.map(l=>l.name));
      const chosen=new Set($("server-libraries").value.toUpperCase().split(/[,\s]+/));
      $("server-library-choices").innerHTML=catalog.libraries.map(l=>`<label class="check"><input type="checkbox" value="${esc(l.name)}" ${chosen.has(l.name)?"checked":""}>${esc(l.name)} · ${esc(l.engines.join(", "))}</label>`).join("");
      $("server-snapshot-status").textContent=`${catalog.label} · ${catalog.partial?"Partial snapshot · ":""}captured ${date(catalog.captured)}. Refresh to update; this is not a live view.`;
      renderCatalog();
    }catch(e){if(serverLoadingId===id)$("server-snapshot-status").textContent=e.message;}
    finally{if(serverLoadingId===id)serverLoadingId=null;}
  }else renderCatalog();
  refreshDictionary();renderSavedPreviews();
}
function catalogIssues(catalog){
  const issues=catalog.issues||[];if(!issues.length)return "";
  return `<details class="catalog-issues" open><summary>${issues.length} skipped-item / refresh ${issues.length===1?"warning":"warnings"}</summary><p class="hint">Readable metadata was retained. Storage totals for incomplete libraries show known storage only. Inspect the refresh log for full SAS errors.</p>${table(["Skipped item / scope","Reason"],issues.slice(0,100).map(issue=>`<tr><td>${esc([issue.libname,issue.name].filter(Boolean).join(".") || "Refresh")}</td><td>${esc(issue.message)}</td></tr>`))}${issues.length>100?'<p class="hint">Showing the first 100 warnings. Download the snapshot JSON for the full list.</p>':""}</details>`;
}
function renderCatalog(){
  if(!serverCatalog)return;
  const libs=serverCatalog.libraries;
  $("server-issues").innerHTML=catalogIssues(serverCatalog);
  $("server-summary").textContent=`${libs.length} saved libraries · ${libs.reduce((n,l)=>n+l.tables,0)} tables · ${libs.reduce((n,l)=>n+l.views,0)} ${libs.reduce((n,l)=>n+l.views,0)===1?"view":"views"}. ${serverCatalog.partial?"Partial metadata: skipped items are listed below. ":""}Storage totals are per library; aliases can overlap.`;
  $("server-library-list").innerHTML=libs.length?table(["Library / engine","Table storage","Tables / views","Location"],libs.map(l=>`<tr><td><button type="button" class="text-button" data-server-library="${esc(l.name)}">${esc(l.name)}</button>${l.assigned===false?'<small class="log-warning">Not assigned in the latest discovery · earlier metadata retained</small>':""}<button type="button" class="subtle" data-refresh-library="${esc(l.name)}" ${state.windows?"":"disabled"}>Refresh tables</button><small>${l.tables_refreshed?`Tables refreshed ${date(l.tables_refreshed.captured)}${l.tables_refreshed.partial?" · partial":""}`:"Tables not collected"}</small><small>${esc(l.engines.join(", "))}</small></td><td>${esc(l.tables_refreshed?storageSize(l.known_bytes,l.unknown_sizes+(l.incomplete?1:0)):"Not collected")}${l.unknown_sizes?`<small>${l.unknown_sizes} ${l.unknown_sizes===1?"table size":"table sizes"} unavailable</small>`:""}</td><td>${l.tables} / ${l.views}${l.incomplete?`<small>${l.skipped_members?`${l.skipped_members} skipped members`:"Incomplete library metadata"}</small>`:""}</td><td class="server-location">${l.paths.map(esc).join("<br>") || "—"}</td></tr>`)):empty("No libraries returned","Check your initialization assignments and library filter in the refresh console.");
  const rows=catalogRows(serverCatalog,$("server-library").value,$("server-search").value,$("server-sort").value).filter(t=>$("server-availability").value==="unavailable"?t.readable===false:$("server-availability").value==="readable"?t.readable!==false:true);
  const pages=Math.max(1,Math.ceil(rows.length/100));serverPage=Math.max(0,Math.min(serverPage,pages-1));
  $("server-table-list").innerHTML=rows.length?table(["Table / label","Type","Storage","Rows / columns","Created","Changed"],rows.slice(serverPage*100,(serverPage+1)*100).map(t=>`<tr><td><button class="text-button" type="button" data-server-table="${esc(JSON.stringify({libname:t.libname,name:t.name}))}">${esc(t.libname)}.${esc(t.name)}</button><small>${esc(t.label)}</small>${t.readable===false?`<small class="log-warning">Metadata unavailable · ${esc(t.warning||"Inspect refresh log")}</small>`:""}${t.stale?"<small>Retained from an earlier partial refresh</small>":""}<small>${t.captured?`Tables refreshed ${date(t.captured)}`:""}</small></td><td>${t.kind==="VIEW"?"View":t.kind==="UNKNOWN"?"Unknown":"Table"}</td><td>${t.kind==="VIEW"?"—":esc(storageSize(t.bytes))}</td><td>${t.rows==null?"Unknown":esc(t.rows.toLocaleString())} / ${t.columns==null?"Unknown":esc(t.columns.toLocaleString())}</td><td>${esc(t.created?.replace("T"," ")||"Unknown")}</td><td>${esc(t.modified?.replace("T"," ")||"Unknown")}</td></tr>`)):empty("No matching tables","Choose another library or change your search.");
  $("server-page").textContent=`${rows.length} ${rows.length===1?"match":"matches"} · page ${serverPage+1} of ${pages}`;$("server-prev").disabled=serverPage===0;$("server-next").disabled=serverPage===pages-1;renderColumns();
}
bindForm("server-form","server-refresh");
$("server-snapshots").addEventListener("change",renderServers);
for(const id of ["server-library","server-search","server-sort","server-availability"])$(id).addEventListener("input",()=>{serverPage=0;renderCatalog();});
$("server-prev").addEventListener("click",()=>{serverPage--;renderCatalog();});
$("server-next").addEventListener("click",()=>{serverPage++;renderCatalog();});
document.addEventListener("click",e=>{const button=e.target.closest("[data-server-library]");if(button){$("server-library").value=button.dataset.serverLibrary;serverPage=0;renderCatalog();}});
$("server-reuse").addEventListener("click",()=>{
  const saved=(state.server_snapshots||[]).find(s=>s.id===serverLoadedId);if(!saved)return;
  $("server-use-init").checked=saved.use_init!==false;$("server-label").value=saved.label;$("server-libraries").value=saved.libraries.join(", ");
  for(const [id,value] of [["server-template",saved.template],["server-init",saved.lib]]){
    const select=$(id), matching=state.files.find(f=>f===value || `${state.workspace}/${f}`===value || `${state.workspace}\\${f}`===value);
    if(value && !matching){error("The saved EGP or initialization path is unavailable. Select its location on this computer.");select.value="";}else select.value=matching||"";
  }
});

function setCopyTarget(path) {
  if(copyTarget!==path){$("copy-status").hidden=true;$("copy-status").textContent="";$("copy-file").textContent="Copy file";}
  copyTarget=path;$("copy-file").hidden=!path;$("copy-file").disabled=copyBusy || !state?.windows;
  $("copy-file").title=state?.windows?"Copy this file as a file attachment using the Windows clipboard":"Copy file is available on Windows. Use Download on this computer.";
}
async function copyFile() {
  const path=copyTarget;if(!path || copyBusy || !state?.windows)return;
  copyBusy=true;$("copy-file").disabled=true;$("copy-file").textContent="Copying…";
  $("copy-status").hidden=false;$("copy-status").textContent="Copying file to the Windows clipboard…";
  try {
    const result=await api("/api/copy-file",{path});
    if(copyTarget===path){$("copy-file").textContent="File copied";$("copy-status").textContent=`${result.name} copied as a file. Paste into an app that accepts file attachments.`;}
  }catch(e){
    if(copyTarget===path){$("copy-file").textContent="Copy file";$("copy-status").textContent=`Copy failed: ${e.message || "Try again, or use Download."}`;}
  }finally{copyBusy=false;$("copy-file").disabled=!state?.windows;if(copyTarget!==path)$("copy-file").textContent="Copy file";}
}
$("copy-file").addEventListener("click",copyFile);


async function copyTargetFile(button, target, output) {
  button.disabled=true;output.textContent="Copying file…";
  try { const result=await api("/api/copy-file",target);output.textContent=`Copied ${result.name}. Paste into an app that accepts files.`; }
  catch(e){output.textContent=e.message;}
  finally {button.disabled=!state.windows;}
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-copy-target]");if(!button)return;
  const output=button.id==="server-copy"?$("server-copy-status"):button.parentElement.querySelector(".file-action-status");
  copyTargetFile(button,JSON.parse(button.dataset.copyTarget),output);
});
const exportJobs=new Map(),folderExports=new Map();
function exportKey(scope,path){return scope+":"+(path||"");}
function currentExport(entry){return ["run","project","task","command"].includes(entry.scope)?entry.button.dataset.exportScope===entry.scope&&entry.button.dataset.exportPath===entry.path:entry.output.dataset.exportJob===entry.id;}
async function prepareExport(button) {
  const scope=button.dataset.exportScope;
  const output=$(["run","project","task","command"].includes(scope)?"folder-export-status":"backup-export-status");
  button.disabled=true;output.textContent="Starting ZIP preparation…";
  try {
    const job=await api("/api/export",{scope,path:button.dataset.exportPath||""});
    output.dataset.exportJob=job.id;exportJobs.set(job.id,{id:job.id,button,output,scope,path:button.dataset.exportPath||""});folderExports.set(exportKey(scope,button.dataset.exportPath),job);showExport(job,output);
  }catch(e){output.textContent=e.message;button.disabled=false;}
}
function showExport(job,output){
  const signature=JSON.stringify(job);if(output.dataset.exportSignature===signature)return;output.dataset.exportSignature=signature;
  if(job.status==="READY"){
    output.innerHTML=`<p>ZIP ready · ${esc(storageSize(job.bytes))}. Choose Download to save it, or Copy file to attach it. Prepared ZIPs are kept until the app restarts.</p>`+fileActions({export:job.id},"ZIP");
  }else if(job.status==="FAILED") output.textContent=job.message;
  else output.innerHTML=`<p>${esc(job.message)}${job.total?` · ${esc(storageSize(job.done))} / ${esc(storageSize(job.total))}`:""}</p><progress aria-label="ZIP preparation" ${job.total?`max="${job.total}" value="${job.done}"`:""}></progress>`;
}
let exportPolling=false;
async function pollExports(){
  if(exportPolling||!exportJobs.size)return;exportPolling=true;
  try{for(const [id,entry] of exportJobs){
    try{const job=await api(`/api/export-status?id=${encodeURIComponent(id)}`);folderExports.set(exportKey(entry.scope,entry.path),job);if(currentExport(entry))showExport(job,entry.output);
      if(job.status!=="WORKING"){if(currentExport(entry))entry.button.disabled=false;exportJobs.delete(id);}
    }catch(e){if(currentExport(entry))entry.output.textContent=`Could not check ZIP progress: ${e.message}. Retrying…`;}
  }}finally{exportPolling=false;}
}
document.addEventListener("click",event=>{const button=event.target.closest("[data-export-scope]");if(button)prepareExport(button);});
setInterval(pollExports,500);
let cleanupPlan=null;
document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-cleanup]");if(!button)return;
  button.disabled=true;$("cleanup-status").textContent="Checking saved runs and storage…";
  try{cleanupPlan=await api("/api/cleanup",{mode:button.dataset.cleanup});
    $("cleanup-status").textContent=`${cleanupPlan.runs} eligible runs · ${storageSize(cleanupPlan.bytes)}. Active and unknown runs are protected.`;
    if(!cleanupPlan.runs)return;
    $("cleanup-description").textContent=`Delete ${cleanupPlan.runs} ${cleanupPlan.mode==="failed"?"failed or stopped":"finished"} runs and free ${storageSize(cleanupPlan.bytes)}?${cleanupPlan.mode==="finished"?" This includes successful runs.":""}`;
    $("cleanup-dialog-status").textContent="";$("cleanup-dialog").showModal();
  }catch(e){$("cleanup-status").textContent=e.message;}finally{button.disabled=false;}
});
$("cancel-cleanup").addEventListener("click",()=>{$("cleanup-dialog").close();cleanupPlan=null;});
$("confirm-cleanup").addEventListener("click",async()=>{
  if(!cleanupPlan)return;$("confirm-cleanup").disabled=true;$("cleanup-dialog-status").textContent="Deleting reviewed run folders…";
  try{const result=await api("/api/cleanup",{token:cleanupPlan.token});$("cleanup-dialog").close();cleanupPlan=null;$("cleanup-status").textContent=`Deleted ${result.runs} runs · ${storageSize(result.bytes)} removed.`;await refresh(true);}
  catch(e){$("cleanup-dialog-status").textContent=e.message;}
  finally{$("confirm-cleanup").disabled=false;}
});

function initializeSharedWork(){
  if(sharedWorkInitialized||!state?.shared_work)return;
  const value=state.shared_work;
  $("shared-work-enabled").checked=value.enabled;
  $("shared-work-path").value=value.path;
  $("shared-work-libref").value=value.libref;
  $("shared-work-summary").textContent=value.enabled?`Shared WORK · ${value.libref} enabled for new runs`:"Shared WORK · use an open SAS session";
  sharedWorkInitialized=true;
}
$("shared-work-form").addEventListener("submit",async event=>{
  event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');button.disabled=true;
  try{const saved=await api("/api/shared-work",formData(event.currentTarget));state.shared_work=saved;sharedWorkInitialized=false;initializeSharedWork();
    $("shared-work-status").textContent=saved.enabled?`Saved: ${saved.libref} will be the default library for new runs. Restart an existing watcher to apply this change.`:"Shared WORK disabled for new runs. Restart an existing watcher to apply this change.";
  }catch(e){$("shared-work-status").textContent=e.message;}finally{button.disabled=false;}
});
function remainingText(value, now){
  if(!value?.active)return "No files running";
  if(value.seconds==null)return "Finish time unknown · waiting for timings";
  const seconds=Math.max(0,value.seconds-Math.max(0,now-value.observed));
  if(seconds<1)return value.unknown?"Finish time unknown · estimate exceeded or incomplete":"Finishing current work…";
  const minutes=Math.ceil(seconds/60), hours=Math.floor(minutes/60);
  return `~${hours?hours+"h ":""}${minutes%60}m${value.unknown?"+":""} until finished${value.unknown?" · some timings unknown":""}`;
}
function renderRemaining(){
  if(!state)return;
  const current=state.commands.filter(c=>active(c)&&c.action!=="watch");
  const longest=current.length?current.reduce((a,b)=>(a.elapsed_base||0)+clockSeconds()-a.started>(b.elapsed_base||0)+clockSeconds()-b.started?a:b):null;
  const remaining=state.remaining, finish=remaining?.active&&remaining.seconds!=null?remaining.observed+remaining.seconds:null;
  $("header-runs").textContent=longest?`${current.length===1?longest.name:current.length+" active runs"} · elapsed ${elapsed(longest)} · ${remainingText(remaining,clockSeconds())}${finish&&finish>clockSeconds()?` · ${remaining.unknown?"at least ":"expected finish "}${new Date(finish*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}`:""}`:remaining?.active?remainingText(remaining,clockSeconds()):"No active executions";
  $("header-runs").title="Elapsed refers to the longest active run, excluding pauses. Finish is an estimate for all current workloads, excluding future watcher arrivals.";
  $("running-remaining").textContent=remainingText(state.remaining,clockSeconds());
  $("running-remaining").title="Current runs, remaining schedule tasks and the current watcher queue. Historical estimate; future arrivals are excluded. Parallel commands run independently.";
}
$("discover-libraries").addEventListener("click",()=>launch({...formData($("server-form")),action:"server-refresh",level:"tables"},$("server-form")));
$("server-library-choices").addEventListener("change",()=>{
  $("server-libraries").value=Array.from($("server-library-choices").querySelectorAll('input:checked')).map(input=>input.value).join(", ");
});

function resetLogSummary(path=null){
  logRequest++;logView={path,kind:"all",offset:0,issue:null,revision:""};
  $("log-summary").hidden=true;$("log-summary").innerHTML="";delete $("log-summary").dataset.markup;
  delete $("file-preview").dataset.output;
}
function logSummaryMarkup(result,kind){
  const items=result.issues.map(i=>`<button type="button" class="log-issue log-${esc(i.severity)}" data-key-row data-log-issue="${i.index}"><strong>Line ${i.line} · ${esc(i.severity)}</strong><span>${esc(i.message)}</span></button>`).join("");
  return `<div class="log-summary-head"><strong>${result.counts.error} errors · ${result.counts.warning} warnings</strong><small>${result.lines.toLocaleString()} lines scanned${result.changed?" · file changed during scan; refresh to update":" · whole saved log"}</small></div>
<div class="log-summary-actions"><button type="button" class="secondary" data-keytip="E" data-log-issue="${result.first.error??''}" ${result.first.error==null?'disabled':''}>First error</button><button type="button" class="secondary" data-keytip="W" data-log-issue="${result.first.warning??''}" ${result.first.warning==null?'disabled':''}>First warning</button><button type="button" class="subtle" data-log-tail>Latest log output</button></div>
<section id="log-issues-details" aria-label="Errors and warnings"><div class="log-summary-actions">${[['all','All issues'],['error','Errors'],['warning','Warnings']].map(([value,label])=>`<button type="button" class="subtle" aria-pressed="${kind===value}" data-log-kind="${value}">${label}</button>`).join('')}</div>
<div class="log-issues" data-key-list data-keytip="I" tabindex="0" aria-label="Log issues" aria-describedby="list-keyboard-help">${items||'<p class="hint">No matching ERROR or WARNING diagnostics found. This does not guarantee the run succeeded.</p>'}</div>
<div class="log-summary-actions"><button type="button" class="subtle" data-log-offset="${Math.max(0,result.offset-result.page_size)}" ${result.offset===0?'disabled':''}>Previous issues</button><small>${result.total?result.offset+1:0}–${Math.min(result.total,result.offset+result.page_size)} of ${result.total}</small><button type="button" class="subtle" data-log-offset="${result.offset+result.page_size}" ${result.offset+result.page_size>=result.total?'disabled':''}>Next issues</button></div></section><p id="log-summary-status" class="hint" role="status">Select an issue to see its surrounding log lines below.</p>`;
}
function logContextMarkup(context){
  return `<p class="hint">Issue context · lines ${context.start}–${context.start+context.lines.length-1}</p><pre>${context.lines.map((line,index)=>`<span class="log-context-line ${context.start+index===context.selected_line?'log-selected-line':''}"><span class="log-line-number">${context.start+index}</span>${esc(line)}</span>`).join('\n')}</pre>`;
}
async function refreshLogSummary(path){
  if(selectedPreview!==path)return;
  const request=++logRequest, query=new URLSearchParams({path,kind:logView.kind,offset:String(logView.offset)});
  if(logView.issue!==null){query.set('issue',logView.issue);query.set('revision',logView.revision);}
  $("log-summary").hidden=false;
  if(!logView.revision)$("log-summary").textContent="Scanning the full saved log for errors and warnings…";
  try{
    const result=await api('/api/log-summary?'+query);
    if(request!==logRequest||selectedPreview!==path)return;
    logView.revision=result.revision;logView.offset=result.offset;
    putMarkup('log-summary',logSummaryMarkup(result,logView.kind));
    globalThis.PySASKeys?.refreshLists();
    if(result.context_error){$("log-summary-status").textContent=result.context_error;logView.issue=null;delete $("file-preview").dataset.output;}
    else if(result.context){const html=logContextMarkup(result.context);if($("file-preview").innerHTML!==html){$("file-preview").innerHTML=html;$("file-preview").scrollTop=0;}delete $("file-preview").dataset.output;}
  }catch(e){if(request===logRequest&&selectedPreview===path){$("log-summary").textContent='Log summary unavailable: '+e.message;delete $("log-summary").dataset.markup;}}
}
$("log-summary").addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.hasAttribute('data-log-tail')){logView.issue=null;delete $("file-preview").dataset.output;await preview(selectedPreview,true);return;}
  if(button.dataset.logIssue!==undefined)logView.issue=Number(button.dataset.logIssue);
  if(button.dataset.logKind!==undefined){logView.kind=button.dataset.logKind;logView.offset=0;}
  if(button.dataset.logOffset!==undefined)logView.offset=Number(button.dataset.logOffset);
  await refreshLogSummary(selectedPreview);
});

for(const id of ["run-mode","run-source","schedule-mode"])$(id).addEventListener("change",runFlow);
$("preferences-form").addEventListener("submit",async e=>{e.preventDefault();try{state.preferences=await api("/api/preferences",formData(e.currentTarget));$("preferences-status").textContent="Defaults saved for new runs.";}catch(e){$("preferences-status").textContent=e.message;}});
$("save-watcher").addEventListener("click",async()=>{try{state.preferences=await api("/api/preferences",{watcher:formData($("watch-form"))});$("watcher-settings-status").textContent="Watcher settings saved. Restart an active watcher to apply changes.";}catch(e){$("watcher-settings-status").textContent=e.message;}});
document.addEventListener("click",e=>{
  const b=e.target.closest("button");if(!b)return;
  if(["refresh","keyboard-help","quit-app"].includes(b.dataset.globalAction))$(b.dataset.globalAction).click();
  if(b.hasAttribute("data-watcher-stop"))$("stop-watch").click();
  if(b.hasAttribute("data-watcher-settings")){navigate("files");$("settings-watcher").open=true;$("settings-watcher").scrollIntoView();}
  if(b.dataset.uploadContext){navigate("files");$("settings-upload").open=true;$("upload-target").value=b.dataset.uploadContext;uploadDestination();$("upload-files").focus();}
});

function inspectorFiles(files,tab){return (files||[]).filter(f=>tab==="logs"?(f.is_log??/\.log$/i.test(f.name)):!(f.is_log??/\.log$/i.test(f.name))&&!f.inside_task&&!/^tasks[\\/]/i.test(f.name)&&!f.internal);}
function logSymbol(file){const level=file.severity||"pending",symbol={error:"✕",warning:"⚠",success:"✓",pending:"…",unknown:"?"}[level]||"?";return `<span class="log-state ${esc(level)}" role="img" aria-label="${esc({error:"Errors",warning:"Warnings",success:"No diagnostics found",pending:"Scanning log",unknown:"Log unavailable"}[level]||level)}">${symbol}</span>`;}
function renderInspectorFiles(){
  if(!inspectorDetail)return;
  const files=inspectorFiles(inspectorDetail.files,inspectorTab);
  putMarkup("file-list",files.map(f=>`<button class="file-item ${f.path===selectedPreview?"selected":""}" data-key-row data-preview="${esc(f.path)}" title="${esc(f.name)}">${inspectorTab==="logs"?logSymbol(f):""}<span>${esc(inspectorTab==="logs"?(f.log_label||f.name.split(/[\\/]/).pop()):f.name)}</span></button>`).join("")||'<p class="hint">No files in this view yet.</p>');
}
function setInspectorTab(tab){inspectorTab=tab;$("detail-tasks").hidden=tab!=="tasks";$("inspector-files").hidden=tab==="tasks";document.querySelectorAll("[data-inspector-tab]").forEach(b=>{b.setAttribute("aria-pressed",String(b.dataset.inspectorTab===tab));b.disabled=b.dataset.inspectorTab==="tasks"&&!inspectorDetail?.tasks?.length;});renderInspectorFiles();}
document.addEventListener("click",async e=>{
  const b=e.target.closest("button");if(!b)return;
  if(b.dataset.inspectorTab){setInspectorTab(b.dataset.inspectorTab);if(inspectorTab!=="tasks"){const file=inspectorFiles(inspectorDetail?.files,inspectorTab)[0];if(file)await preview(file.path);else{resetLogSummary();setCopyTarget(null);$("download").hidden=true;$("file-preview").innerHTML='<p class="empty-small">No files in this view yet.</p>';}}}
  if(b.dataset.openBackup){try{await api("/api/open-folder",{command:b.dataset.openBackup});}catch(e){error(e.message);}}
});
$("open-run-folder").addEventListener("click",async()=>{try{await api("/api/open-folder",{path:$("open-run-folder").dataset.path});}catch(e){$("inspector-status").textContent=e.message;}});
$("rename-run").addEventListener("submit",async e=>{e.preventDefault();try{const saved=await api("/api/run-name",{path:selectedPath,command:selectedCommand,name:$("run-display-name").value});$("detail-title").textContent=saved.name||selectedPath?.split(/[\\/]/).pop()||"Task";$("inspector-status").textContent="Name saved.";await refresh(true);}catch(e){$("inspector-status").textContent=e.message;}});
$("copy-log-text").addEventListener("click",async()=>{try{await navigator.clipboard.writeText($("file-preview").innerText);$("copy-status").hidden=false;$("copy-status").textContent="Displayed log text copied (current preview or issue context only). Download or Copy file includes the full saved log.";}catch(e){$("copy-status").hidden=false;$("copy-status").textContent="Text copy failed: "+e.message;}});
$("verify-bundle").addEventListener("click",()=>launch({...formData($("bundle-form")),action:"bundle-verify"},$("bundle-form")));

async function refreshServerScope(level,libraries,table=""){
  if(!serverLoadedId)return;
  await launch({action:"server-refresh",parent_snapshot:serverLoadedId,level,libraries,table},$("server-form"));
  $("server-snapshots").value="";
}
function renderColumns(){
  $("server-columns").hidden=!selectedServerTable;if(!selectedServerTable||!serverCatalog)return;
  const t=selectedServerTable,key=t.libname+"."+t.name;
  const stamp=serverCatalog.refreshes?.['columns:'+key];
  const columns=(serverCatalog.column_details||[]).filter(c=>c.libname===t.libname&&c.table===t.name).sort((a,b)=>(a.position||0)-(b.position||0));
  $("server-column-title").textContent=key+" · columns";
  $("server-column-status").textContent=stamp?`Refreshed ${date(stamp.captured)}${stamp.partial?" · incomplete, inspect the refresh log":""}${columns.some(c=>c.stale)?" · earlier schema retained; refresh before preview":""}`:"Columns have not been collected. Refresh opens a fresh session using this snapshot’s connection.";
  initializePreviewBuilder(columns);$("refresh-columns").disabled=!state.windows;
  $("server-column-list").innerHTML=columns.length?table(["Column","Type","Length","Label","Format","Informat"],columns.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${esc(c.length)}</td><td>${esc(c.label)}</td><td>${esc(c.format)}</td><td>${esc(c.informat)}</td></tr>`)):empty("No saved columns","Refresh this table’s columns; inaccessible metadata is recorded in the refresh log.");
}
$("refresh-columns").addEventListener("click",()=>refreshServerScope("columns",selectedServerTable.libname,selectedServerTable.name));
document.addEventListener("click",async e=>{const b=e.target.closest("button");if(!b)return;
  if(b.dataset.refreshLibrary){$("server-library").value=b.dataset.refreshLibrary;await refreshServerScope("tables",b.dataset.refreshLibrary);}
  if(b.dataset.serverTable){selectedServerTable=JSON.parse(b.dataset.serverTable);renderColumns();renderSavedPreviews();$("server-columns").scrollIntoView({block:"start"});}
});

function initializePreviewBuilder(columns){
  const blocked=!columns.length||columns.some(c=>c.stale)||serverCatalog?.refreshes?.["columns:"+selectedServerTable.libname+"."+selectedServerTable.name]?.partial;
  $("start-table-preview").dataset.blocked=blocked?"1":"0";$("start-table-preview").disabled=!state.windows||blocked;
  const signature=JSON.stringify([serverCatalog?.connection,selectedServerTable,columns.map(c=>[c.name,c.type,c.captured,c.stale])]);
  if(signature===previewBuilderSignature)return;
  previewBuilderSignature=signature;$("preview-filters").innerHTML="";$("table-preview-status").textContent="";
}
function addPreviewFilter(){
  if($("preview-filters").children.length>=10)return;
  const columns=(serverCatalog?.column_details||[]).filter(c=>selectedServerTable&&c.libname===selectedServerTable.libname&&c.table===selectedServerTable.name);
  const row=document.createElement("div");row.className="preview-filter";
  row.innerHTML=`<label>Column<select data-filter-column>${columns.map(c=>`<option value="${esc(c.name)}">${esc(c.name)} · ${esc(c.type)}</option>`).join("")}</select></label><label>Condition<select data-filter-operator>${[['eq','Equals'],['ne','Does not equal'],['lt','Less than'],['le','At most'],['gt','Greater than'],['ge','At least'],['contains','Contains text'],['starts','Starts with text'],['missing','Missing'],['not_missing','Not missing']].map(([v,label])=>`<option value="${v}">${label}</option>`).join("")}</select></label><label>Value<input data-filter-value maxlength="512"></label><button type="button" class="subtle" data-remove-filter>Remove</button>`;
  $("preview-filters").append(row);
}
$("add-preview-filter").addEventListener("click",addPreviewFilter);
document.addEventListener("click",e=>{const b=e.target.closest("[data-remove-filter]");if(b)b.closest(".preview-filter").remove();});
$("table-preview-form").addEventListener("submit",async e=>{
  e.preventDefault();if(!selectedServerTable||!serverLoadedId)return;
  const button=$("start-table-preview");button.disabled=true;$("table-preview-status").textContent="Starting bounded preview…";
  const filters=Array.from($("preview-filters").children).map(row=>({column:row.querySelector("[data-filter-column]").value,operator:row.querySelector("[data-filter-operator]").value,value:row.querySelector("[data-filter-value]").value}));
  try{const result=await api("/api/launch",{action:"server-refresh",level:"preview",parent_snapshot:serverLoadedId,libraries:selectedServerTable.libname,table:selectedServerTable.name,limit:$("preview-limit").value,join:$("preview-join").value,filters});$("table-preview-status").textContent="Preview running. Its console has a Stop file control; completed rows appear below.";await refresh();await showCommand(result.id);}
  catch(e){$("table-preview-status").textContent=e.message;}finally{button.disabled=!state.windows||button.dataset.blocked==="1";}
});
async function renderSavedPreviews(){
  const previews=(state?.server_previews||[]).filter(p=>p.sample&&(!serverCatalog?.connection||p.connection===serverCatalog.connection)&&(!selectedServerTable||p.library===selectedServerTable.libname&&p.table===selectedServerTable.name));
  const select=$("server-preview-select"),previous=select.value;
  select.innerHTML='<option value="">Latest preview for this table / connection</option>'+previews.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${esc(date(p.started))}</option>`).join("");select.value=previous;
  const chosen=previews.find(p=>p.id===select.value)||previews[0];
  if(!chosen){previewResult=null;previewResultId=null;$("preview-result-status").textContent="No completed preview for this selection.";$("preview-result-table").innerHTML="";$("preview-result-actions").innerHTML="";return;}
  if(previewResultId!==chosen.id){
    if(previewLoadingId===chosen.id)return;
    const id=chosen.id;previewLoadingId=id;$("preview-result-status").textContent="Loading bounded saved result…";
    try{const result=await api('/api/server-preview?id='+encodeURIComponent(id));if(previewLoadingId!==id)return;previewResult=result;previewResultId=id;previewPage=0;}
    catch(e){if(previewLoadingId===id)$("preview-result-status").textContent=e.message;return;}
    finally{if(previewLoadingId===id)previewLoadingId=null;}
  }
  $("preview-result-actions").innerHTML=fileActions({path:chosen.sample_csv},"sample CSV")+fileActions({path:chosen.sample},"sample JSON");renderPreviewRows();
}
function renderPreviewRows(){
  if(!previewResult)return;
  const r=previewResult,pages=Math.max(1,Math.ceil(r.rows.length/50));previewPage=Math.max(0,Math.min(previewPage,pages-1));
  $("preview-result-status").textContent=`${r.library}.${r.table} · ${r.rows.length} saved rows · ${date(r.captured)}${r.more_rows?" · more rows exist":""}${r.transport_limited?" · transport limit reached":""}${r.cells_truncated?" · long text cells truncated":""}${r.omitted_columns?` · ${r.omitted_columns} columns omitted`:""}${r.partial?" · SAS reported errors; inspect its log":""}. Unordered bounded sample; CSV exports these rows only and escapes formula-like text. Numeric dates remain raw SAS values.`;
  $("preview-result-table").innerHTML=readOnlyTable(r.columns.map(c=>`${esc(c.name)}<small>${esc(c.type)}${c.format?' · '+esc(c.format):''}</small>`),r.rows.slice(previewPage*50,(previewPage+1)*50).map(row=>`<tr>${row.map(v=>`<td>${v===null?'<span class="hint">Missing</span>':esc(v)}</td>`).join("")}</tr>`),"Saved table preview · scroll to see more columns");
  $("preview-result-page").textContent=`Page ${previewPage+1} of ${pages} · 50 rows per page`;$("preview-page-prev").disabled=previewPage===0;$("preview-page-next").disabled=previewPage===pages-1;
}
$("server-preview-select").addEventListener("change",renderSavedPreviews);
$("preview-page-prev").addEventListener("click",()=>{previewPage--;renderPreviewRows();});$("preview-page-next").addEventListener("click",()=>{previewPage++;renderPreviewRows();});
async function refreshDictionary(force=false){
  if(!serverLoadedId)return;
  const signature=JSON.stringify([serverLoadedId,$("dictionary-libraries").value,$("dictionary-search").value,dictionaryOffset]);
  if(!force&&signature===dictionarySignature)return;dictionarySignature=signature;
  const request=++dictionaryRequest;$("dictionary-status").textContent="Reading saved dictionary…";
  try{const result=await api('/api/dictionary?'+new URLSearchParams({id:serverLoadedId,libraries:$("dictionary-libraries").value,q:$("dictionary-search").value,offset:String(dictionaryOffset)}));if(request!==dictionaryRequest)return;
    dictionaryOffset=result.offset;$("dictionary-status").textContent=`${result.total.toLocaleString()} matching metadata rows. Unavailable and uncollected tables stay explicit.`;
    $("dictionary-results").innerHTML=readOnlyTable(result.headers.map(esc),result.rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`),"Data dictionary · scroll to see more columns");
    $("dictionary-page").textContent=`${result.total?result.offset+1:0}–${Math.min(result.total,result.offset+result.page_size)} of ${result.total}`;
    $("dictionary-prev").disabled=dictionaryOffset===0;$("dictionary-next").disabled=dictionaryOffset+result.page_size>=result.total;
  }catch(e){if(request===dictionaryRequest)$("dictionary-status").textContent=e.message;}
}
for(const id of ['dictionary-libraries','dictionary-search'])$(id).addEventListener('input',()=>{clearTimeout(dictionaryTimer);dictionaryOffset=0;dictionaryTimer=setTimeout(()=>refreshDictionary(),350);});
$("dictionary-prev").addEventListener("click",()=>{dictionaryOffset=Math.max(0,dictionaryOffset-200);refreshDictionary();});$("dictionary-next").addEventListener("click",()=>{dictionaryOffset+=200;refreshDictionary();});
async function pollDictionaryJob(id){
  try{const job=await api('/api/metadata-job?id='+encodeURIComponent(id));if(dictionaryJob!==id)return;
    $("dictionary-job-status").textContent=`${job.done}/${job.total} · ${job.message}`;$("stop-dictionary").hidden=job.operation!=="collect"||job.status!=="WORKING";
    if(job.status==="WORKING"){setTimeout(()=>pollDictionaryJob(id),1000);return;}
    $("dictionary-job-actions").innerHTML=job.path?fileActions({path:job.path},"dictionary"):job.snapshot?`<button class="secondary" data-load-snapshot="${esc(job.snapshot)}">View collected metadata</button>`:"";
    dictionarySignature=null;refreshDictionary();
  }catch(e){$("dictionary-job-status").textContent=e.message;}
}
document.addEventListener("click",async e=>{const b=e.target.closest("button");if(!b)return;
  if(b.dataset.dictionaryOperation){b.disabled=true;$("dictionary-job-status").textContent="Starting dictionary operation…";
    try{const job=await api('/api/metadata-job',{snapshot:serverLoadedId,libraries:$("dictionary-libraries").value,query:$("dictionary-search").value,operation:b.dataset.dictionaryOperation});dictionaryJob=job.id;$("dictionary-job-actions").innerHTML="";pollDictionaryJob(job.id);}
    catch(e){$("dictionary-job-status").textContent=e.message;}finally{b.disabled=b.dataset.dictionaryOperation==="collect"&&!state.windows;}
  }
  if(b.dataset.loadSnapshot){$("server-snapshots").value=b.dataset.loadSnapshot;await renderServers();}
});
$("stop-dictionary").addEventListener("click",async()=>{if(!dictionaryJob)return;try{await api('/api/metadata-job/stop',{id:dictionaryJob});$("dictionary-job-status").textContent="Stopping after the current table. Use its Stop file control to cancel that file immediately.";}catch(e){$("dictionary-job-status").textContent=e.message;}});

$("data-locations-form").addEventListener("submit",async event=>{event.preventDefault();const button=event.currentTarget.querySelector("button");button.disabled=true;$("data-locations-status").textContent="Checking data folders…";try{const result=await api("/api/data-locations",formData(event.currentTarget));$("data-locations-status").textContent=result.message;foldersInitialized=false;parametersInitialized=false;preferencesInitialized=false;bundlePathsInitialized=false;sharedWorkInitialized=false;await refresh(true);}catch(e){$("data-locations-status").textContent=e.message;}finally{button.disabled=false;}});

let migrationRunning=false,migrationPolling=false;
function showMigration(job){$("migration-status").textContent=job.message+(job.status==="WORKING"&&job.total?` · ${storageSize(job.done)} / ${storageSize(job.total)}`:"");migrationRunning=job.status==="WORKING";$("import-legacy-runs").disabled=migrationRunning;}
$("import-legacy-runs").addEventListener("click",async()=>{try{showMigration(await api("/api/import-legacy-runs",{}));}catch(e){$("migration-status").textContent=e.message;}});
setInterval(async()=>{if(!migrationRunning||migrationPolling)return;migrationPolling=true;try{showMigration(await api("/api/data-migration"));if(!migrationRunning)await refresh(true);}catch(e){$("migration-status").textContent=e.message;}finally{migrationPolling=false;}},1000);

globalThis.PySASGraphHost={request:api,refresh,inspect:showCommand,inspectPath:showPath,fileActions,timer,badge,expectedText};

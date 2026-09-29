/* Mnemonic navigation, scoped action hints, and arrow-key browsing. */
(function () {
  "use strict";
  const alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const navigation={overview:"O",runner:"R",scheduler:"S",tools:"B",history:"H",files:"F",servers:"V"};
  function codes(count){const width=Math.max(1,Math.ceil(Math.log(Math.max(1,count))/Math.log(26)));return Array.from({length:count},(_,i)=>{let code="";for(let n=0;n<width;n++){code=alphabet[i%26]+code;i=Math.floor(i/26);}return code;});}
  // Reserve explicit hints first. Allocate fallback letters from the control's
  // label, across the whole scope (including off-screen and disabled controls).
  function assignHints(items){
    const used=new Set(), answer=new Map();
    const free=code=>code&&!Array.from(used).some(other=>other.startsWith(code)||code.startsWith(other));
    const ordered=items.map((item,index)=>({...item,index})).sort((a,b)=>Number(!!b.preferred)-Number(!!a.preferred)||String(a.identity).localeCompare(String(b.identity))||a.index-b.index);
    for(const item of ordered){
      const preferred=(item.preferred||"").toUpperCase();
      let code=free(preferred)?preferred:Array.from((item.label||"").toUpperCase().replace(/[^A-Z]/g,"")).find(c=>c!=="Z"&&free(c));
      if(!code){code=codes(items.length+26).map(c=>"Z"+c).find(free);}
      used.add(code);answer.set(item.index,code);
    }
    return items.map((_,i)=>answer.get(i));
  }
  let entries=[], typed="", layer=null, altOnly=false, level="root";
  const api={active:false,codes,assignHints,navigation,show,hide,showPage:()=>show("page"),enterList,refreshLists};
  globalThis.PySASKeys=api;
  function hide(){api.active=false;typed="";entries=[];layer?.remove();layer=null;}
  function visible(el){return !!el&&!el.closest('[hidden],[inert]')&&!!el.getClientRects().length;}
  function viewport(el){const b=el.getBoundingClientRect();return b.bottom>0&&b.top<innerHeight&&b.right>0&&b.left<innerWidth;}
  function currentDialog(){return Array.from(document.querySelectorAll("dialog[open]")).at(-1);}
  function label(el){return el.getAttribute('aria-label')||el.labels?.[0]?.textContent||el.textContent||el.title||el.name||"Action";}
  function rowItems(list){
    return Array.from(list.querySelectorAll('[data-key-row]')).filter(row=>row.closest('[data-key-list]')===list).map(row=>{
      const buttons=row.matches('button,a[href]')?[row]:Array.from(row.querySelectorAll('button,a[href]')).filter(el=>el.closest('[data-key-list]')===list);
      return {row,buttons:buttons.filter(el=>!el.disabled&&visible(el))};
    }).filter(item=>item.buttons.length);
  }
  function refreshLists(){
    document.querySelectorAll('[data-key-list]').forEach(list=>{
      const items=rowItems(list), buttons=items.flatMap(i=>i.buttons);
      const focused=buttons.includes(document.activeElement)?document.activeElement:null;
      buttons.forEach(button=>button.tabIndex=button===focused?0:-1);
      list.tabIndex=focused?-1:0;
    });
  }
  function enterList(list,last=false){
    if(!list)return false;
    const items=rowItems(list);if(!items.length){list.focus();return false;}
    const remembered=items.find(i=>i.buttons.some(b=>(list.dataset.lastPath&&b.dataset.path===list.dataset.lastPath)||(list.dataset.lastPreview&&b.dataset.preview===list.dataset.lastPreview)));
    const item=last?items.at(-1):(remembered||items[0]);
    focusItem(list,item,0);return true;
  }
  function focusItem(list,item,column){
    const button=item.buttons[Math.min(column,item.buttons.length-1)];
    rowItems(list).flatMap(i=>i.buttons).forEach(b=>b.tabIndex=b===button?0:-1);list.tabIndex=-1;
    if(button.dataset.path)list.dataset.lastPath=button.dataset.path;
    if(button.dataset.preview)list.dataset.lastPreview=button.dataset.preview;
    button.focus({preventScroll:true});item.row.scrollIntoView({block:'nearest',inline:'nearest'});
  }
  function listKey(event){
    if(event.ctrlKey||event.metaKey||event.altKey||event.shiftKey||event.target?.matches('input,textarea,select,[contenteditable="true"]'))return;
    const list=event.target?.closest('[data-key-list]');if(!list)return;
    const items=rowItems(list);if(!items.length)return;
    const index=items.findIndex(i=>i.buttons.includes(document.activeElement));
    const column=index<0?0:items[index].buttons.indexOf(document.activeElement);
    let next=index, cell=Math.max(0,column);
    if(event.key==='ArrowDown')next=index<0?0:Math.min(items.length-1,index+1);
    else if(event.key==='ArrowUp')next=index<0?items.length-1:Math.max(0,index-1);
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=items.length-1;
    else if(event.key==='PageDown')next=Math.min(items.length-1,Math.max(0,index)+10);
    else if(event.key==='PageUp')next=Math.max(0,index-10);
    else if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&index>=0){cell=Math.max(0,Math.min(items[index].buttons.length-1,cell+(event.key==='ArrowRight'?1:-1)));}
    else if(event.key==='Enter'&&index<0){event.preventDefault();enterList(list);return;}
    else return; // Enter/Space on a focused button retain normal browser behaviour.
    event.preventDefault();event.stopPropagation();focusItem(list,items[next],cell);
  }
  function show(requested="root"){
    hide();level=requested;
    const dialog=currentDialog();if(dialog)level="page";
    const scope=dialog||document.querySelector('.page:not([hidden])')||document;
    let candidates;
    if(level==="root"){
      candidates=Array.from(document.querySelectorAll('[data-page]')).map(el=>({el,code:navigation[el.dataset.page]}));
      for(const [id,code] of [['refresh','U'],['quit-app','Q'],['page-title','X']]){
        const el=document.getElementById(id);if(el)candidates.push({el,code,action:id==='page-title'?()=>show('page'):null});
      }
    }else{
      const controls=Array.from(scope.querySelectorAll('button,a[href],input:not([type="hidden"]),select,textarea,summary,[tabindex="0"],[data-key-list]')).filter(el=>{
        const list=el.closest('[data-key-list]');return !list||list===el;
      });
      const labels=assignHints(controls.map(el=>({preferred:el.dataset.keytip,label:label(el),identity:el.id||`${el.form?.id||""}/${el.name||""}/${label(el)}`})));
      candidates=controls.map((el,i)=>({el,code:labels[i]}));
    }
    candidates=candidates.filter(({el,code})=>code&&!el.disabled&&visible(el)&&viewport(el));
    api.active=true;layer=document.createElement('div');layer.className='keytips';layer.setAttribute('aria-hidden','true');
    const help=document.createElement('div');help.className='keytips-help';help.textContent=level==='root'?'Choose a page · X page commands · Esc cancel':'Choose a command or list · Lists: ↑ ↓ then Enter · Esc back';layer.append(help);
    entries=candidates.map(entry=>{
      const {el,code}=entry,badge=document.createElement('span');badge.className='keytip';badge.textContent=code;
      const anchor=el.type==='file'&&el.closest('label')?el.closest('label'):el,rect=anchor.getBoundingClientRect();
      badge.style.left=Math.max(2,Math.min(innerWidth-38,rect.left+8))+'px';badge.style.top=Math.max(2,Math.min(innerHeight-26,rect.top-7))+'px';
      layer.append(badge);return {...entry,badge};
    });
    (dialog||document.body).append(layer);
  }
  document.addEventListener('keydown',event=>{
    if(event.key==='Alt'&&!event.ctrlKey&&!event.metaKey&&!event.getModifierState?.('AltGraph')){if(!event.repeat)altOnly=true;event.preventDefault();return;}
    if(event.altKey||event.ctrlKey||event.metaKey){altOnly=false;return;}
    if(event.key==='F10'&&!event.shiftKey){event.preventDefault();api.active?hide():show();return;}
    if(!api.active){listKey(event);return;}
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(level==='page'&&!currentDialog())show();else hide();return;}
    if(event.key==='Tab'){hide();return;}
    if(event.key==='Backspace'){event.preventDefault();typed=typed.slice(0,-1);}
    else if(/^[a-z]$/i.test(event.key)&&!event.repeat){event.preventDefault();event.stopPropagation();typed+=event.key.toUpperCase();}
    else return;
    const matches=entries.filter(entry=>entry.code.startsWith(typed));
    if(!matches.length){typed="";entries.forEach(entry=>entry.badge.hidden=false);return;}
    entries.forEach(entry=>entry.badge.hidden=!entry.code.startsWith(typed));
    const target=matches.find(entry=>entry.code===typed);if(!target)return;
    const el=target.el;hide();if(!el.isConnected||el.disabled)return;
    if(target.action){target.action();return;}
    if(el.hasAttribute('data-key-list')){enterList(el);return;}
    el.focus();
    if(el.matches('select,textarea,input:not([type="file"]):not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"])'))return;
    el.click();
    if(el.dataset.page||el.dataset.go)requestAnimationFrame(()=>{
      if(el.dataset.page==='history'||el.dataset.go==='history'){
        const list=document.querySelector('#all-history [data-key-list]');if(list)enterList(list);else document.getElementById('history-search')?.focus();
      }else show('page');
    });
  },true);
  document.addEventListener('keyup',event=>{if(event.key==='Alt'&&altOnly){event.preventDefault();altOnly=false;api.active?hide():show();}},true);
  document.addEventListener('focusin',event=>{if(event.target.closest('[data-key-list]'))refreshLists();});
  document.addEventListener('pointerdown',()=>{if(api.active)hide();},true);
  document.addEventListener('scroll',()=>{if(api.active)show(level);},true);
  window.addEventListener('resize',()=>{if(api.active)show(level);});
  window.addEventListener('blur',()=>{altOnly=false;hide();});
  document.getElementById('keyboard-help')?.addEventListener('click',()=>show());
  refreshLists();
})();

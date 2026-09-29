/* Excel-style key hints: tap Alt (or F10), then type the displayed letters. */
(function () {
  "use strict";
  const alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  function codes(count) {
    const width=Math.max(1,Math.ceil(Math.log(Math.max(1,count))/Math.log(26)));
    return Array.from({length:count},(_,index)=>{
      let value=index, code="";
      for(let digit=0;digit<width;digit++){code=alphabet[value%26]+code;value=Math.floor(value/26);}
      return code;
    });
  }
  let entries=[], typed="", layer=null, altOnly=false;
  const api={active:false,codes,show,hide};
  globalThis.PySASKeys=api;
  function hide(){api.active=false;typed="";entries=[];layer?.remove();layer=null;}
  function show(){
    hide();
    const dialog=Array.from(document.querySelectorAll("dialog[open]")).at(-1);
    const scope=dialog||document;
    const controls=Array.from(scope.querySelectorAll('button,a[href],input:not([type="hidden"]),select,textarea,summary,[tabindex="0"]')).filter(el=>{
      if(el.disabled||el.closest('[hidden],[inert]')||!el.getClientRects().length)return false;
      const box=el.getBoundingClientRect();
      return box.bottom>0&&box.top<innerHeight&&box.right>0&&box.left<innerWidth;
    });
    const labels=codes(controls.length);
    api.active=true;
    layer=document.createElement('div');layer.className='keytips';layer.setAttribute('aria-hidden','true');
    const help=document.createElement('div');help.className='keytips-help';help.textContent='Type a hint · Esc to cancel · Scroll for more';layer.append(help);
    entries=controls.map((el,index)=>{
      const badge=document.createElement('span');badge.className='keytip';badge.textContent=labels[index];
      const anchor=el.type==='file'&&el.closest('label')?el.closest('label'):el;
      const rect=anchor.getBoundingClientRect();
      badge.style.left=Math.max(2,Math.min(innerWidth-38,rect.left+8))+'px';
      badge.style.top=Math.max(2,Math.min(innerHeight-26,rect.top-7))+'px';
      layer.append(badge);return {el,code:labels[index],badge};
    });
    (dialog||document.body).append(layer);
  }
  document.addEventListener('keydown',event=>{
    if(event.key==='Alt'&&!event.ctrlKey&&!event.metaKey&&!event.getModifierState?.('AltGraph')){
      if(!event.repeat)altOnly=true;event.preventDefault();return;
    }
    if(event.altKey||event.ctrlKey||event.metaKey){altOnly=false;return;}
    if(event.key==='F10'&&!event.shiftKey){event.preventDefault();api.active?hide():show();return;}
    if(!api.active)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();hide();return;}
    if(event.key==='Tab'){hide();return;}
    if(event.key==='Backspace'){event.preventDefault();typed=typed.slice(0,-1);}
    else if(/^[a-z]$/i.test(event.key)&&!event.repeat){event.preventDefault();event.stopPropagation();typed+=event.key.toUpperCase();}
    else return;
    const matches=entries.filter(entry=>entry.code.startsWith(typed));
    if(!matches.length){typed="";entries.forEach(entry=>entry.badge.hidden=false);return;}
    entries.forEach(entry=>entry.badge.hidden=!entry.code.startsWith(typed));
    const target=matches.find(entry=>entry.code===typed);
    if(!target)return;
    const el=target.el;hide();
    if(!el.isConnected||el.disabled)return;
    el.focus();
    if(el.matches('select,textarea,input:not([type="file"]):not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"])'))return;
    el.click();
    if(el.dataset.page||el.dataset.go)requestAnimationFrame(show);
  },true);
  document.addEventListener('keyup',event=>{
    if(event.key==='Alt'&&altOnly){event.preventDefault();altOnly=false;api.active?hide():show();}
  },true);
  document.addEventListener('pointerdown',()=>{if(api.active)hide();},true);
  document.addEventListener('scroll',()=>{if(api.active)show();},true);
  window.addEventListener('resize',()=>{if(api.active)show();});
  window.addEventListener('blur',()=>{altOnly=false;hide();});
  document.getElementById('keyboard-help')?.addEventListener('click',show);
})();

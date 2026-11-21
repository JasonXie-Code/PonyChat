/* Site-owned controls. Hidden selects retain values and change handlers only. */
(function (root) {
  "use strict";
  function keyboardAction(key,index,length) {
    if (key === "ArrowDown") return {type:"move",index:(index+1)%length};
    if (key === "ArrowUp") return {type:"move",index:(index+length-1)%length};
    if (key === "Home") return {type:"move",index:0};
    if (key === "End") return {type:"move",index:length-1};
    if (key === "Enter" || key === " ") return {type:"choose",index};
    if (key === "Escape" || key === "Tab") return {type:"close",restoreFocus:true};
    return null;
  }
  function popupPlacement(rect,naturalHeight,viewportWidth,viewportHeight) {
    const margin=8,gap=6,width=Math.max(1,Math.min(Math.max(rect.width,144),viewportWidth-margin*2));
    const below=viewportHeight-margin-rect.bottom-gap,above=rect.top-margin-gap,down=below>=naturalHeight || below>=above;
    const height=Math.max(1,Math.min(naturalHeight,down?below:above,viewportHeight-margin*2));
    return {width,height,left:Math.max(margin,Math.min(rect.left,viewportWidth-margin-width)),top:Math.max(margin,Math.min(down?rect.bottom+gap:rect.top-gap-height,viewportHeight-margin-height))};
  }
  function tooltipPlacement(rect,width,height,viewportWidth,viewportHeight,avoid=rect) {
    const margin=8,gap=8;
    const left=Math.max(margin,Math.min(rect.left+rect.width/2-width/2,viewportWidth-width-margin));
    const top=Math.max(margin,Math.min(rect.top+rect.height/2-height/2,viewportHeight-height-margin));
    return [
      {left,top:avoid.top-height-gap},
      {left,top:avoid.bottom+gap},
      {left:avoid.right+gap,top},
      {left:avoid.left-width-gap,top},
    ].find(p=>p.left>=margin && p.top>=margin && p.left+width<=viewportWidth-margin && p.top+height<=viewportHeight-margin) || null;
  }
  function loadUnifiedCursor(doc) {
    if (doc.querySelector(".follow-panel") && !doc.getElementById("musicStableScrollLoader")) {
      const stable = doc.createElement("script"); stable.id = "musicStableScrollLoader";
      stable.src = "/follow-extensions/stable-scroll-v1.js?v=20261027-1"; stable.async = true; doc.head.append(stable);
    }
    if (!doc.querySelector(".follow-panel") || doc.getElementById("musicUnifiedCursorLoader")) return;
    const script=doc.createElement("script");script.id="musicUnifiedCursorLoader";
    script.src="/follow-extensions/unified-cursor-v1.js?v=20261010-3";script.async=true;doc.head.append(script);
  }
  function installUnifiedCursor(win) {
    loadUnifiedCursor(win.document);
    loadPrintedLyrics(win.document);
    const frame=win.document.getElementById("followFrame");
    if (!frame) return;
    const inject=()=>{try {if(frame.contentWindow.location.origin===win.location.origin){loadUnifiedCursor(frame.contentDocument);loadPrintedLyrics(frame.contentDocument);}} catch (_) {}};
    frame.addEventListener("load",inject);inject();
  }
  function loadPrintedLyrics(doc) {
    if (!doc.querySelector(".follow-panel") || doc.getElementById("musicPrintedLyricsLoader")) return;
    const script=doc.createElement("script");script.id="musicPrintedLyricsLoader";
    script.src="/follow-extensions/printed-lyrics-v1.js?v=20261010-1";script.async=true;doc.head.append(script);
  }
  if (typeof module !== "undefined" && module.exports) {module.exports={keyboardAction,popupPlacement,tooltipPlacement,loadUnifiedCursor,loadPrintedLyrics,installUnifiedCursor};return;}
  const controllers=new Map();
  let active=null,tooltipTarget=null,previousDescription=null;
  const tooltip=document.createElement("div");
  tooltip.id="musicControlTooltip";tooltip.className="glass-tooltip";tooltip.setAttribute("role","tooltip");tooltip.hidden=true;document.body.append(tooltip);
  function hideTooltip() {
    tooltip.hidden=true;
    if (tooltipTarget) {if(previousDescription)tooltipTarget.setAttribute("aria-describedby",previousDescription);else tooltipTarget.removeAttribute("aria-describedby");}
    tooltipTarget=null;
  }
  function showTooltip(target) {
    if(!target || !target.dataset.tooltip || active || tooltipTarget===target)return;
    hideTooltip();tooltipTarget=target;previousDescription=target.getAttribute("aria-describedby");tooltip.textContent=target.dataset.tooltip;tooltip.hidden=false;
    target.setAttribute("aria-describedby",[previousDescription,tooltip.id].filter(Boolean).join(" "));
    const r=target.getBoundingClientRect(),w=tooltip.offsetWidth,h=tooltip.offsetHeight;
    const controls=target.closest(".player-controls, .expanded-follow-tools");
    const p=tooltipPlacement(r,w,h,innerWidth,innerHeight,controls?.getBoundingClientRect() || r);
    if(!p){hideTooltip();return;}
    tooltip.style.left=p.left+"px";
    tooltip.style.top=p.top+"px";
  }
  function close(restoreFocus=false) {
    if(!active)return false;
    const control=active;active=null;control.menu.hidden=true;control.button.setAttribute("aria-expanded","false");
    if(restoreFocus && control.button.isConnected)control.button.focus();return true;
  }
  function position(control) {
    const p=popupPlacement(control.button.getBoundingClientRect(),control.menu.scrollHeight,innerWidth,innerHeight);
    Object.assign(control.menu.style,{left:p.left+"px",top:p.top+"px",width:p.width+"px",maxHeight:p.height+"px"});
  }
  function focusOption(control,index) {
    control.index=index;control.options.forEach((option,i)=>{option.tabIndex=i===index?0:-1;option.dataset.active=String(i===index);});
    control.options[index]?.focus({preventScroll:true});control.options[index]?.scrollIntoView({block:"nearest"});
  }
  function refreshControl(control) {
    const entries=[...control.select.options].filter(option=>!option.disabled);
    const signature=entries.map(option=>option.value+"\n"+option.textContent).join("\0");
    if(signature!==control.signature) {
      control.signature=signature;control.menu.replaceChildren();control.options=[];
      entries.forEach((entry,index)=>{
        const option=document.createElement("button");option.type="button";option.className="glass-select-option";option.setAttribute("role","option");option.tabIndex=-1;
        option.dataset.value=entry.value;option.textContent=entry.textContent;option.onclick=()=>choose(control,index);control.menu.append(option);control.options.push(option);
      });
    }
    control.button.disabled=control.select.disabled || !entries.length;
    const text=control.select.selectedOptions[0]?.textContent || "请选择";
    if(control.label.textContent!==text)control.label.textContent=text;
    control.button.setAttribute("aria-label",(control.select.getAttribute("aria-label") || "选项")+"："+text);
    control.options.forEach(option=>option.setAttribute("aria-selected",String(option.dataset.value===control.select.value)));
  }
  function choose(control,index) {
    const option=control.options[index];if(!option)return;
    control.select.value=option.dataset.value;refreshControl(control);close(true);control.select.dispatchEvent(new Event("change",{bubbles:true}));
  }
  function open(control) {
    close();hideTooltip();refreshControl(control);if(control.button.disabled)return;
    active=control;control.menu.hidden=false;control.button.setAttribute("aria-expanded","true");position(control);
    focusOption(control,Math.max(0,control.options.findIndex(option=>option.dataset.value===control.select.value)));
  }
  function customize(select) {
    if(controllers.has(select)){refreshControl(controllers.get(select));return;}
    select.hidden=true;select.tabIndex=-1;select.setAttribute("aria-hidden","true");
    const id=select.id || "musicSelect"+(controllers.size+1),button=document.createElement("button"),label=document.createElement("span"),arrow=document.createElement("span");
    button.type="button";button.id=id+"Button";button.className="glass-select-trigger";button.setAttribute("aria-haspopup","listbox");button.setAttribute("aria-expanded","false");button.setAttribute("aria-controls",id+"Options");
    label.className="glass-select-value";arrow.className="glass-select-arrow";arrow.setAttribute("aria-hidden","true");button.append(label,arrow);select.after(button);
    const menu=document.createElement("div");menu.id=id+"Options";menu.className="glass-select-menu";menu.hidden=true;menu.setAttribute("role","listbox");menu.setAttribute("aria-label",(select.getAttribute("aria-label") || "选项")+"选项");document.body.append(menu);
    const control={select,button,label,menu,options:[],index:0,signature:null};controllers.set(select,control);
    button.onclick=()=>{if(active===control)close(true);else open(control);};
    button.onkeydown=e=>{
      if(["ArrowDown","ArrowUp","Home","End"].includes(e.key)){e.preventDefault();open(control);if(e.key==="Home" || e.key==="End")focusOption(control,e.key==="Home"?0:control.options.length-1);}
    };
    menu.onkeydown=e=>{
      const action=keyboardAction(e.key,control.index,control.options.length);if(!action)return;
      if(e.key!=="Tab")e.preventDefault();e.stopPropagation();
      if(action.type==="move")focusOption(control,action.index);else if(action.type==="choose")choose(control,action.index);else close(action.restoreFocus);
    };
    select.addEventListener("change",()=>refreshControl(control));refreshControl(control);
  }
  function rangeFill(input) {
    const min=Number(input.min || 0),max=Number(input.max || 100);
    input.style.setProperty("--fill",Math.max(0,Math.min(100,(Number(input.value)-min)/(max-min || 1)*100))+"%");
  }
  function refresh() {
    document.querySelectorAll("select").forEach(customize);document.querySelectorAll('input[type="range"]').forEach(rangeFill);
    document.querySelectorAll("[title]").forEach(el=>{
      if(el.tagName==="IFRAME")el.setAttribute("aria-label",el.title);
      else {
        el.dataset.tooltip=el.title;
        if(!el.hasAttribute("aria-label") && (el.tagName==="CANVAS" || !el.textContent.trim() || /^[‹›↓☰×•]+$/.test(el.textContent.trim())))el.setAttribute("aria-label",el.title);
        if(el.matches(".score-canvas-wrap canvas") && !el.dataset.keyboardBound){
          el.dataset.keyboardBound="true";el.setAttribute("role","button");el.tabIndex=0;
          el.addEventListener("keydown",e=>{if(e.key==="Enter" || e.key===" "){e.preventDefault();e.stopPropagation();el.click();}});
        }
      }
      el.removeAttribute("title");
    });
    const q=document.querySelector("#q"),clear=document.querySelector("#clearSearch");if(q && clear)clear.hidden=!q.value;
    for(const [select,control]of controllers)if(!select.isConnected){if(active===control)close();control.menu.remove();controllers.delete(select);}
  }
  const q=document.querySelector("#q");
  if(q){
    const clear=document.createElement("button");clear.type="button";clear.id="clearSearch";clear.className="search-clear";clear.setAttribute("aria-label","清空搜索");clear.textContent="×";clear.hidden=true;q.after(clear);
    clear.onclick=()=>{q.value="";q.focus();q.dispatchEvent(new Event("input",{bubbles:true}));};q.addEventListener("input",()=>{clear.hidden=!q.value;});
  }
  document.addEventListener("input",e=>{if(e.target.matches('input[type="range"]'))rangeFill(e.target);});
  document.addEventListener("pointerdown",e=>{
    hideTooltip();if(active && e.target!==active.button && !active.button.contains(e.target) && !active.menu.contains(e.target))close();
    document.querySelectorAll("details.song-actions[open],details.player-tools[open]").forEach(details=>{if(!details.contains(e.target))details.open=false;});
    document.querySelector("#followFrame")?.contentWindow?.postMessage({type:"music-close-controls"},location.origin);
  },true);
  document.addEventListener("keydown",e=>{
    if(e.key!=="Escape")return;
    if(close(true)){e.preventDefault();e.stopImmediatePropagation();return;}
    const details=[...document.querySelectorAll("details.song-actions[open],details.player-tools[open]")].at(-1);
    if(details){details.open=false;details.querySelector("summary")?.focus();e.preventDefault();e.stopImmediatePropagation();}hideTooltip();
  },true);
  document.addEventListener("toggle",e=>{
    if(!e.target.matches("details.song-actions,details.player-tools"))return;
    e.target.querySelector("summary")?.setAttribute("aria-expanded",String(e.target.open));
    if(e.target.open)document.querySelectorAll("details.song-actions[open],details.player-tools[open]").forEach(details=>{if(details!==e.target)details.open=false;});
    else if(e.target.contains(document.activeElement) && document.activeElement!==e.target.querySelector("summary"))e.target.querySelector("summary")?.focus();
  },true);
  document.addEventListener("pointerover",e=>showTooltip(e.target.closest("[data-tooltip]")));
  document.addEventListener("pointerout",e=>{if(tooltipTarget && !tooltipTarget.contains(e.relatedTarget))hideTooltip();});
  document.addEventListener("focusin",e=>showTooltip(e.target.closest("[data-tooltip]")));document.addEventListener("focusout",hideTooltip);
  document.addEventListener("scroll",()=>{hideTooltip();if(active)position(active);},true);
  window.addEventListener("resize",()=>{hideTooltip();if(active)position(active);});
  window.addEventListener("message",e=>{if(e.origin===location.origin && e.source===parent && e.data?.type==="music-close-controls")close();});
  let refreshQueued=false;
  new MutationObserver(records=>{
    if(!records.some(record=>record.type==="attributes" || (record.target.nodeType===1 && record.target.closest("select")) || [...record.addedNodes,...record.removedNodes].some(node=>node.nodeType===1)))return;
    if(refreshQueued)return;refreshQueued=true;queueMicrotask(()=>{refreshQueued=false;refresh();});
  }).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:["title"]});
  root.MusicControls={refresh,close,keyboardAction,popupPlacement};refresh();installUnifiedCursor(root);
})(typeof window === "undefined" ? {} : window);

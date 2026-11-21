/* A shared reading line; source music and the existing playback controller stay intact. */
(function (root) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const finite = (v) => typeof v === "number" && Number.isFinite(v);
  function coalescedRefresh(win, refresh) {
    let queued = false, alive = true;
    const enqueue = typeof win.queueMicrotask === "function" ? win.queueMicrotask.bind(win) : fn => Promise.resolve().then(fn);
    const schedule = () => {
      if (queued || !alive) return;
      queued = true;
      enqueue(() => {queued=false;if(alive)refresh();});
    };
    schedule.stop = () => {alive=false;};
    return schedule;
  }
  function endedByOwner(win, song) {
    try {
      const matches = (audio, expected) => audio?.ended === true && typeof expected === "string" && expected &&
        new URL(audio.currentSrc || audio.getAttribute?.("src") || audio.src,win.location.href).href === new URL(expected,win.location.href).href;
      if (!song?.id) return false;
      if (!win.parent || win.parent === win) return matches(win.document.querySelector("#audio") || win.document.querySelector("audio"),song.audio);
      if (win.parent.location.origin !== win.location.origin || win.parent.document.getElementById("followFrame")?.contentWindow !== win) return false;
      const selected = win.parent.MusicPlayer?.current?.();
      if (selected?.followId !== song.id || (song.sourceSongId && selected.id !== song.sourceSongId)) return false;
      return matches(win.parent.document.querySelector("#audio"),selected.src);
    } catch (_) { return false; }
  }
  function systemFor(song, event, index) {
    const row = song?.events?.find((item) => item.eventIndex === index), v = event?.visual;
    if (!row || !v || row.time !== event.time || row.measure !== String(event.measure ?? "") ||
        ["x","y","width","height","page"].some((k) => row.visual[k] !== v[k]) ||
        JSON.stringify(row.visual.noteheadCenter || null) !== JSON.stringify(v.noteheadCenter || null) ||
        !finite(row.top) || !finite(row.bottom) || row.top < 0 || row.bottom > 1 || row.bottom <= row.top ||
        !Number.isInteger(row.system) || !Number.isInteger(row.staffCount) || row.staffCount < 1) return null;
    return row;
  }
  function jpPoint(row, measure, beat, scale = 1) {
    const f = row.fragments.find((f) => String(f.measure.measure) === String(measure) && beat >= f.start-.00001 && beat <= f.end+.00001);
    if (!f) return null;
    const u = f.units.find((u) => beat >= u.start-.00001 && beat < u.end) || f.units.at(-1);
    const next = f.units[f.units.indexOf(u)+1];
    const center = u.x+u.width/2, target = next ? next.x+next.width/2 : f.x+f.width-8*scale;
    const progress = Math.max(0,Math.min(1,(beat-u.start)/(u.end-u.start)));
    return {x:center+(target-center)*progress,top:row.y+4*scale,bottom:row.y+row.height-8*scale};
  }
  function create(win, data, source) {
    const doc = win.document, wrap = doc.getElementById("scoreWrap"), geometries = new WeakMap(), styles = new WeakMap();
    const overlayClass = "unified-score-cursor", set = (node,k,v) => {if(node.getAttribute(k)!==String(v))node.setAttribute(k,String(v));};
    const style = (node,k,v) => {let old=styles.get(node);if(!old){old={};styles.set(node,old);}if(old[k]!==v){old[k]=v;node.style[k]=v;}};
    function line(parent, svg) {
      let node = parent.querySelector("."+overlayClass);
      if (!node) {
        node = svg ? doc.createElementNS(NS,"line") : doc.createElement("div");
        node.setAttribute("class",overlayClass); node.setAttribute("aria-hidden","true");
        parent.append(node);
      }
      return node;
    }
    function geometry(svg) {
      if (geometries.has(svg)) return geometries.get(svg);
      let score = data.jianpu;
      const section = svg.closest(".jp-key-section");
      if (section && score.sourceKeyChanges) {
        const sections = [...section.parentNode.querySelectorAll(".jp-key-section")], i = sections.indexOf(section);
        const points = score.sourceKeyChanges.changes;
        score = {...score,measures:score.measures.filter(m => (!i || m.measure >= points[i].measure) && (!points[i+1] || m.measure < points[i+1].measure))};
      }
      const context = doc.createElement("canvas").getContext("2d");
      const selected = Number(doc.getElementById("notationSize")?.value);
      const scale = selected > 0 ? selected : Math.round(parseFloat(svg.style.getPropertyValue("--note-size"))/24*1e12)/1e12 || 1;
      const result = win.MusicNotation.layout(score,Number(svg.getAttribute("width")),scale,(s,fs) => {
        context.font = `${fs}px Arial`; return context.measureText(s).width;
      });
      geometries.set(svg,result); return result;
    }
    function anchor(node, time, index, extra) {
      set(node,"data-audio-clock",time); set(node,"data-event-index",index ?? "");
      for (const [key,value] of Object.entries(extra)) set(node,"data-"+key,value);
    }
    function refresh() {
      const time = Number(wrap.dataset.playbackTime || 0), policy = win.MusicFollowPolicy;
      const staffMode = wrap.dataset.mode !== "jianpu";
      const finished = endedByOwner(win,data.song);
      if (wrap.classList.contains("unified-cursor-ended") !== finished) wrap.classList.toggle("unified-cursor-ended",finished);
      const caps = policy.capabilities(data);
      const pair = policy.cursorPair(policy.cursorEvents(data.sync),policy.playbackTokens(data.jianpu,data.sync),time,caps.canonicalCursor,caps.section);
      const visiblePage = wrap.querySelector(".auto-page.has-current");
      let resolvedStaff = false;
      for (const page of wrap.querySelectorAll(".auto-page")) {
        const cursor = page.querySelector(".auto-cursor"), index = cursor?.dataset.eventIndex;
        const event = index !== undefined ? data.sync.events[Number(index)] : pair.event;
        const actualIndex = event ? data.sync.events.indexOf(event) : -1;
        const system = !finished && staffMode && page === visiblePage ? systemFor(source,event,actualIndex) : null;
        const node = page.querySelector("."+overlayClass);
        if (page.classList.contains("has-unified-system") !== !!system) page.classList.toggle("has-unified-system",!!system);
        if (!system) {if(node)style(node,"display","none"); continue;}
        const current = line(page,false);
        resolvedStaff = true;
        style(current,"display","block"); style(current,"left",cursor.style.left);
        style(current,"top",system.top*100+"%"); style(current,"height",(system.bottom-system.top)*100+"%");
        anchor(current,time,actualIndex,{mode:"staff",page:system.page,system:system.system,"staff-count":system.staffCount});
      }
      const activeRow = !finished && !staffMode ? wrap.querySelector(".jp-row-active") : null, active = activeRow?.querySelector(".jp-active");
      set(wrap,"data-unified-cursor-status",finished ? "ended" : staffMode && visiblePage ? (resolvedStaff ? "source-system" : "unmapped-source-system") : activeRow ? "jianpu-row" : "idle");
      for (const svg of wrap.querySelectorAll(".jp-svg")) {
        const node = svg.querySelector("."+overlayClass);
        if (!active || active.closest("svg") !== svg) {if(node)style(node,"display","none"); continue;}
        const token = data.jianpu.tokens.find(t => String(t.id ?? t.eventIndex) === active.dataset.id);
        const bar = active.querySelector(".jp-progress"), range = Number(active.dataset.end)-Number(active.dataset.start);
        const ratio = Number(bar.getAttribute("width"))/Number(bar.dataset.width);
        const beat = Number(active.dataset.start)+Math.max(0,Math.min(1,ratio))*range;
        const rows = [...svg.querySelectorAll(".jp-row")], layout = geometry(svg), row = layout.rows[rows.indexOf(activeRow)];
        const point = row && token ? jpPoint(row,token.measure,beat,layout.scale) : null;
        if (!point) {if(node)style(node,"display","none");continue;}
        const current = line(svg,true); style(current,"display","block");
        set(current,"x1",point.x);set(current,"x2",point.x);set(current,"y1",point.top);set(current,"y2",point.bottom);
        anchor(current,time,active.dataset.eventIndex ?? token.eventIndex,{mode:"jianpu",row:activeRow.dataset.row,"token-id":active.dataset.id,"source-beat":beat,"lane-count":row.lanes});
      }
      if (!wrap.classList.contains("unified-cursor-enabled")) wrap.classList.add("unified-cursor-enabled");
    }
    // The core has already painted this time. A second RAF can be throttled
    // even while the document reports visible, leaving an old line at a gap.
    // Attribute/style writes above are idempotent, so our own observer batch
    // settles after one follow-up refresh without an animation dependency.
    const schedule = coalescedRefresh(win, refresh);
    const observer = new win.MutationObserver(schedule);
    observer.observe(wrap,{subtree:true,childList:true,attributes:true,attributeFilter:["class","style","width","data-playback-time","data-mode"]});
    refresh();
    return {refresh,stop:()=>{schedule.stop();observer.disconnect();}};
  }
  async function start(win) {
    if (!win.document.getElementById("scoreWrap") || !win.MusicFollowPolicy) return;
    const song = new URLSearchParams(win.location.search).get("song") || "catchy-song";
    const response = await win.fetch("/api/follow/demo?song="+encodeURIComponent(song),{cache:"no-store"});
    if (!response.ok) throw Error("Unified source systems unavailable");
    const data = await response.json(), id = data.song?.id;
    if (!/^[a-z0-9-]+$/.test(id || "")) throw Error("Invalid follow identity");
    const metadata = await win.fetch("/follow-extensions/unified-cursor-systems-v1/"+id+".json?v=20261010-1",{cache:"no-store"});
    if (!metadata.ok) throw Error("No exact source system geometry");
    const systems = await metadata.json();
    if (systems.schema !== "original-score-systems/v1" || systems.song?.followId !== id) throw Error("No exact source system geometry");
    const css = win.document.createElement("link");css.rel="stylesheet";css.href="/follow-extensions/unified-cursor-v1.css?v=20261010-1";
    await new Promise((resolve,reject) => {css.onload=resolve;css.onerror=()=>reject(Error("Unified cursor style unavailable"));win.document.head.append(css);});
    win.MusicUnifiedCursor = create(win,data,systems.song);
  }
  const api = {systemFor,jpPoint,endedByOwner,coalescedRefresh,create,start};
  if (typeof module === "object" && module.exports) module.exports=api;
  else {
    let started = false;
    const winReady = () => {
      if (started) return;
      started = true;
      start(root).catch(error => {const wrap=root.document.getElementById("scoreWrap");if(wrap)wrap.dataset.unifiedCursorError=error.message;});
    };
    // Async injection can reach an interactive document before deferred score
    // scripts and their signed-frame fetch wrapper have executed.
    if(root.document.readyState==="complete")winReady();
    else {
      root.document.addEventListener("DOMContentLoaded",winReady,{once:true});
      root.addEventListener("load",winReady,{once:true});
    }
  }
})(typeof window === "object" ? window : {});

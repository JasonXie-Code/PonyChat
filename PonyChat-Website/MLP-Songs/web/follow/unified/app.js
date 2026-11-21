/* Winter Wrap Up's reader, shared by all admitted songs. Parent owns time and sound. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const wrap = $("#scoreWrap"), status = $("#stageStatus"), resume = $("#resumeFollow");
  let data = null, events = [], tokens = [], seekEvents = [], mode = "staff", time = 0;
  let paused = true, manualCursor = null, recordingEnded = false;
  let ending = null;
  let following = true, visible = true, scale = 1, lastWidth = 0, resizeFrame = 0;
  let activeEvent = null, activeToken = null, activeRow = null, lastScrollRow = "";
  let noteElements = new Map(), rows = [], pages = new Map(), notationGeometry = null;
  let scrollFrame = 0, scrollTarget = null;
  let seekRevision = null;
  let capabilities = null;
  let sectionNotation = false, focusedSection = null, sectionMarkers = [];
  let noteReferences = [], activeReference = null;
  let harmonyReferences = [], harmonyEvent = null, harmonyFrame = 0;
  const harmonyMarkers = new Map();
  const sectionMeasures = new Set();
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
  function send(type, extra = {}) { if (parent !== window) parent.postMessage({type, ...extra}, location.origin); }
  function updateStatus() {
    if (!capabilities) return;
    const interaction = sectionNotation && mode === "jianpu" ? "点按小节编号定位段落" : capabilities.interaction;
    status.textContent = capabilities.hasSync ? `${following ? "自动跟随" : "自由浏览"} · ${interaction}` : interaction;
  }
  function stopScroll() {cancelAnimationFrame(scrollFrame); scrollFrame = 0; scrollTarget = null;}
  function scrollTo(top, smooth) {
    const target = clamp(top, 0, Math.max(0, wrap.scrollHeight-wrap.clientHeight));
    if (scrollTarget !== null && Math.abs(scrollTarget-target)<2) return;
    stopScroll();
    const from = wrap.scrollTop;
    if (!smooth || reducedMotion.matches || Math.abs(from-target)<2) {wrap.scrollTop = target; return;}
    scrollTarget = target;
    const started = performance.now();
    function step(now) {
      const p = Math.min(1, (now-started)/340);
      wrap.scrollTop = from+(target-from)*(1-Math.pow(1-p, 3));
      if (p<1) scrollFrame = requestAnimationFrame(step);
      else {scrollFrame = 0; scrollTarget = null;}
    }
    scrollFrame = requestAnimationFrame(step);
  }
  function browse() {
    following = false; stopScroll(); resume.hidden = false;
    updateStatus();
  }
  function restoreFollow() {
    following = true; resume.hidden = true; lastScrollRow = "";
    updateStatus();
  }
  function keepRow(rect, key, force) {
    if (!visible || !following || !rect || !wrap.clientHeight) return;
    const bounds = wrap.getBoundingClientRect();
    if (key === lastScrollRow && !force) return;
    lastScrollRow = key;
    scrollTo(wrap.scrollTop + rect.top-bounds.top - wrap.clientHeight*.23, !force);
  }
  function renderNotation(force = false) {
    if (!data || !capabilities.hasNotation || !wrap.clientWidth) return;
    const score = $("#jianpuScore"), width = Math.floor(wrap.clientWidth-16);
    if (!force && width === lastWidth) return;
    lastWidth = width;
    const previous = [...score.querySelectorAll(".jp-note")].find((el) => el.getBoundingClientRect().bottom >= wrap.getBoundingClientRect().top);
    const anchor = previous?.dataset.id, anchorOffset = previous ? previous.getBoundingClientRect().top-wrap.getBoundingClientRect().top : 0;
    const rendered = window.MusicNotation.render(data.jianpu, width, scale, sectionMeasures);
    notationGeometry = rendered.geometry;
    if (mode === "jianpu") paintHarmony(null, time);
    score.innerHTML = rendered.html;
    noteElements = new Map();
    score.querySelectorAll(".jp-note").forEach((el) => {
      if (!noteElements.has(el.dataset.id)) noteElements.set(el.dataset.id, []);
      noteElements.get(el.dataset.id).push(el);
    });
    rows = [...score.querySelectorAll(".jp-row")];
    activeToken = null; activeRow = null;
    focusedSection = null; sectionMarkers = []; activeReference = null;
    update(true);
    if (!following && mode === "jianpu" && anchor) {
      const node = noteElements.get(anchor)?.[0];
      if (node) wrap.scrollTop += node.getBoundingClientRect().top-wrap.getBoundingClientRect().top-anchorOffset;
    }
  }
  function renderPages() {
    const staff = $("#staffScore"); staff.replaceChildren(); pages.clear();
    for (const [i, src] of (data.song.charts || []).entries()) {
      const page = document.createElement("div"); page.className = "auto-page"; page.dataset.page = i+1;
      const img = document.createElement("img"); img.alt = `乐谱第 ${i+1} 页`; img.src = src;
      const band = document.createElement("div"); band.className = "staff-row-band";
      const cursor = document.createElement("div"); cursor.className = "auto-cursor";
      page.append(img, band, cursor); staff.append(page); pages.set(i+1, {page, band, cursor});
      img.addEventListener("load", () => update(true));
      img.addEventListener("error", () => {status.textContent = "部分谱页加载失败，可打开原谱 PDF 查看。";});
    }
  }
  function paintStaff(ev, force) {
    if (!ev?.visual) {
      for (const item of pages.values()) {item.page.classList.remove("has-current"); item.cursor.removeAttribute("data-event-index");}
      activeEvent = null;
      return;
    }
    const v = ev.visual, pageNo = Number(v.page || ev.page || 1), entry = pages.get(pageNo);
    if (!entry) return;
    if (ev !== activeEvent || force) {
      for (const item of pages.values()) item.page.classList.toggle("has-current", item === entry);
      const {cursor, band} = entry;
      const head = window.MusicFollowPolicy.headCenter(ev, capabilities.canonicalCursor);
      if (capabilities.canonicalCursor && Number.isInteger(ev.eventIndex)) cursor.dataset.eventIndex = String(ev.eventIndex);
      else cursor.removeAttribute("data-event-index");
      band.style.top = v.y*100+"%"; band.style.height = v.height*100+"%";
      if (capabilities.section) {band.style.left = v.x*100+"%"; band.style.width = v.width*100+"%"; band.style.right = "auto";}
      cursor.style.top = v.y*100+"%"; cursor.style.height = v.height*100+"%";
      cursor.style.left = (head?.x ?? v.x+v.width/2)*100+"%";
      cursor.classList.toggle("has-head-center", !!head);
      if (head) cursor.style.setProperty("--cursor-head-y", (head.y-v.y)/v.height*100+"%");
      else cursor.style.removeProperty("--cursor-head-y");
      cursor.classList.toggle("rest", !!ev.isRest); activeEvent = ev;
    }
    keepRow(entry.band.getBoundingClientRect(), `staff:${pageNo}:${Math.round(v.y*100)}`, force);
    if (following && visible && wrap.clientWidth < 600 && entry.page.clientWidth > wrap.clientWidth) {
      const c = entry.cursor.getBoundingClientRect(), bounds = wrap.getBoundingClientRect();
      if (force || c.left < bounds.left + wrap.clientWidth * .18 || c.right > bounds.right - wrap.clientWidth * .18) {
        wrap.scrollLeft = Math.max(0, wrap.scrollLeft + c.left - bounds.left - wrap.clientWidth * .5);
      }
    }
  }
  function paintJianpu(t, force) {
    const svg=$("#jianpuScore .jp-svg");
    let line=svg?.querySelector(".unified-score-cursor");
    if (!t) {
      if(line)line.style.display="none";
      if (activeToken) (noteElements.get(String(activeToken.id ?? activeToken.eventIndex)) || []).forEach((el) => {el.classList.remove("jp-active"); el.removeAttribute("aria-current");});
      activeRow?.classList.remove("jp-row-active"); activeToken = null; activeRow = null;
      return;
    }
    const elements = noteElements.get(String(t.id ?? t.eventIndex)) || [];
    const tokenIndex = tokens.indexOf(t), next = tokenIndex >= 0 ? tokens[tokenIndex+1] : null;
    const duration = Math.max(.04, Math.min(t.mappedDurationSeconds || t.durationSeconds || 1, next ? next.time-t.time : Infinity));
    const progress = clamp((time-t.time)/duration, 0, 1), beat = t.beat + progress*t.durationBeats;
    const current = elements.find((el) => beat >= Number(el.dataset.start) && beat < Number(el.dataset.end)) || elements.at(-1);
    const row = current ? rows[Number(current.dataset.row)] : null;
    if (activeToken !== t || force) {
      if (activeToken) (noteElements.get(String(activeToken.id ?? activeToken.eventIndex)) || []).forEach((el) => {el.classList.remove("jp-active"); el.removeAttribute("aria-current");});
      elements.forEach((el) => {el.classList.add("jp-active"); el.setAttribute("aria-current", "true");
        if (t.occurrenceId) el.dataset.eventIndex = String(t.eventIndex);}); activeToken = t;
    }
    if (row !== activeRow) {activeRow?.classList.remove("jp-row-active"); row?.classList.add("jp-row-active"); activeRow = row;}
    elements.forEach((el) => {
      const p = clamp((beat-Number(el.dataset.start))/(Number(el.dataset.end)-Number(el.dataset.start)), 0, 1);
      const bar = el.querySelector(".jp-progress"); bar.setAttribute("width", Number(bar.dataset.width)*p);
    });
    const geometry=row && notationGeometry?.rows[Number(current.dataset.row)];
    const fragment=geometry?.fragments.find(f=>String(f.measure.measure)===String(t.measure) && beat>=f.start-.00001 && beat<=f.end+.00001);
    if(svg && geometry && fragment) {
      const unit=fragment.units.find(u=>beat>=u.start-.00001 && beat<u.end) || fragment.units.at(-1);
      const next=fragment.units[fragment.units.indexOf(unit)+1],from=unit.x+unit.width/2;
      const to=next?next.x+next.width/2:fragment.x+fragment.width-8*scale;
      const x=from+(to-from)*clamp((beat-unit.start)/(unit.end-unit.start),0,1);
      if(!line){line=document.createElementNS("http://www.w3.org/2000/svg","line");line.setAttribute("class","unified-score-cursor");line.setAttribute("aria-hidden","true");svg.append(line);}
      line.style.display="block";
      for(const [key,value]of Object.entries({x1:x,x2:x,y1:geometry.y+(29+geometry.chordHeader+geometry.labelHeader)*scale,y2:geometry.y+geometry.height-8*scale}))line.setAttribute(key,value);
    }
    if (row) {
      const rect = row.getBoundingClientRect();
      const tall = rect.height > wrap.clientHeight*.65;
      // A multi-voice system may be taller than a phone's reading area.
      keepRow(tall ? current.getBoundingClientRect() : rect, `jianpu:${current.dataset.row}${tall ? ":"+(t.lane || 0) : ""}`, force);
    }
  }
  function paintJianpuSection(event, focus, force) {
    if (!notationGeometry || (!force && focus === focusedSection && !!event === !!sectionMarkers.length)) return;
    sectionMarkers.forEach(marker => marker.remove());
    sectionMarkers = [];
    focusedSection = focus;
    if (!focus) return;
    const {firstMeasure, lastMeasure} = focus.jianpuSection;
    let anchor = null;
    for (const geometry of notationGeometry.rows) {
      const row = rows[geometry.index];
      for (const fragment of geometry.fragments) {
        const measure = fragment.measure.measure;
        if (measure < firstMeasure || measure > lastMeasure) continue;
        anchor ??= row;
        if (!event) continue;
        const marker = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        for (const [key, value] of Object.entries({
          class:"jp-section-cue", "aria-hidden":"true", "pointer-events":"none", "data-measure":measure,
          x:fragment.x, y:geometry.y, width:fragment.width, height:geometry.height-4*scale, rx:4*scale,
          fill:"#a78bfa25", stroke:"#8b5cf680"
        })) marker.setAttribute(key, value);
        row.insertBefore(marker, row.children[1] || null);
        sectionMarkers.push(marker);
      }
    }
    if (anchor) keepRow(anchor.getBoundingClientRect(), `jianpu-section:${focus.eventIndex}`, force);
  }
  function paintNoteReference(reference) {
    if (reference === activeReference) return;
    for (const node of noteElements.get(String(activeReference?.id)) || []) node.classList.remove("jp-note-reference");
    for (const node of noteElements.get(String(reference?.id)) || []) node.classList.add("jp-note-reference");
    activeReference = reference;
  }
  function paintHarmony(event, clock) {
    if (!harmonyReferences.length) return;
    const active = harmonyReferences.filter(ref => ref.primary === event && ref.time <= clock && clock < ref.endTime);
    for (const [ref, remove] of harmonyMarkers) {
      if (active.includes(ref)) continue;
      remove();
      harmonyMarkers.delete(ref);
    }
    for (const ref of active) {
      if (harmonyMarkers.has(ref)) continue;
      if (mode === "jianpu") {
        const nodes = noteElements.get(ref.id) || [];
        nodes.forEach(node => node.classList.add("jp-harmony-reference"));
        harmonyMarkers.set(ref, () => nodes.forEach(node => node.classList.remove("jp-harmony-reference")));
      } else {
        const {page, x, y, width, height} = ref.head;
        const entry = pages.get(page);
        if (!entry) continue;
        const marker = document.createElement("div");
        marker.className = "auto-harmony-reference";
        marker.dataset.sourcePhysicalId = ref.sourcePhysicalId;
        marker.setAttribute("aria-hidden", "true");
        Object.assign(marker.style, {left:x*100+"%", top:y*100+"%", width:width*100+"%", height:height*100+"%"});
        entry.page.append(marker);
        harmonyMarkers.set(ref, () => marker.remove());
      }
    }
  }
  function animateHarmony() {
    harmonyFrame = 0;
    if (!visible || paused) return;
    const audio = ownerAudio();
    if (!audio || audio.paused || audio.ended) return;
    paintHarmony(harmonyEvent, audio.currentTime);
    harmonyFrame = requestAnimationFrame(animateHarmony);
  }
  function updateHarmony(event) {
    if (!harmonyReferences.length) return;
    harmonyEvent = event;
    const audio = visible && !paused ? ownerAudio() : null;
    paintHarmony(visible ? event : null, audio?.currentTime ?? time);
    if (audio && !audio.paused && !audio.ended) {
      if (!harmonyFrame) harmonyFrame = requestAnimationFrame(animateHarmony);
    } else {
      cancelAnimationFrame(harmonyFrame);
      harmonyFrame = 0;
    }
  }
  function findEnding() {
    const last = events.at(-1);
    if (!last) return null;
    const id = window.MusicUnifiedModel.id;
    const finalId = id(last);
    const matchingTokens = data.jianpu.tokens.filter(token => id(token) === finalId);
    const allEndsKnown = events.every(event => Number.isFinite(event.endTime) && event.endTime > event.time);
    return {
      time: allEndsKnown ? events.reduce((end, event) => Math.max(end, event.endTime), 0) : null,
      staffEvent: events.reduce((lastVisual, event) => event.visual ? event : lastVisual, null),
      jianpuToken: matchingTokens.length === 1 ? matchingTokens[0] : tokens.at(-1)
    };
  }
  function ownerAudio() {
    if (!data || parent === window) return null;
    try {
      if (parent.document.getElementById("followFrame")?.contentWindow !== window) return null;
      const selected = parent.MusicPlayer?.current?.();
      const song = data.song;
      const sameRecording = song.sourceSongId ? selected?.id === song.sourceSongId : selected?.followId === song.id;
      if (!sameRecording || !selected.src) return null;
      const audio = parent.document.getElementById("audio");
      return audio?.currentSrc === new URL(selected.src, location.href).href ? audio : null;
    } catch (_) {
      return null;
    }
  }
  function ownerPlaybackEnded(currentTime) {
    const audio = paused ? ownerAudio() : null;
    return audio?.ended === true && Math.abs(audio.currentTime-currentTime) < .05;
  }
  function keepEnding(force) {
    if (!following) return;
    if (mode === "staff") {
      const event = ending.staffEvent;
      if (!event) return;
      const visual = event.visual, pageNo = Number(visual.page || event.page || 1);
      const page = pages.get(pageNo)?.page;
      if (!page) return;
      const rect = page.getBoundingClientRect();
      keepRow({top:rect.top + visual.y*rect.height}, `staff-ending:${pageNo}:${visual.y}`, force);
      if (wrap.clientWidth < 600 && page.clientWidth > wrap.clientWidth) {
        const head = window.MusicFollowPolicy.headCenter(event, capabilities.canonicalCursor);
        const x = head?.x ?? visual.x + visual.width/2;
        const left = rect.left + x*rect.width - wrap.getBoundingClientRect().left;
        wrap.scrollLeft = Math.max(0, wrap.scrollLeft + left - wrap.clientWidth*.5);
      }
    } else if (ending.jianpuToken) {
      const token = ending.jianpuToken;
      const element = noteElements.get(String(token.id ?? token.eventIndex))?.at(-1);
      const row = element && rows[Number(element.dataset.row)];
      if (!row) return;
      const rect = row.getBoundingClientRect();
      keepRow(rect.height > wrap.clientHeight*.65 ? element.getBoundingClientRect() : rect,
        `jianpu-ending:${element.dataset.row}`, force);
    }
  }
  function update(force = false) {
    if (!data || !visible) return;
    wrap.dataset.playbackTime = String(time);
    const finished = recordingEnded || time >= data.sync.duration;
    const pair = finished ? {event:null,token:null} : manualCursor && paused ? manualCursor : window.MusicFollowPolicy.cursorPair(events, tokens, time, capabilities.canonicalCursor, capabilities.section);
    const numberedSection = mode === "jianpu" && sectionNotation;
    const staffEvent = pair.event;
    const ev = numberedSection && !staffEvent?.jianpuSection ? null : staffEvent;
    const reference = numberedSection && ev ? window.MusicFollowPolicy.eventAt(noteReferences,time,true) : null;
    const token = pair.token, label = reference || (mode === "jianpu" && !sectionNotation ? token : ev);
    const sectionPreview = preview && capabilities.section;
    const tail = !ev && !token && ending && (finished || (!preview && ending.time !== null && time >= ending.time));
    wrap.dataset.sourcePhysicalId = ev ? window.MusicUnifiedModel.id(ev) : "";
    const range = numberedSection && ev?.jianpuSection;
    let position = window.MusicFollowPolicy.position(label, capabilities.section, time, events);
    if (tail) position = "尾声";
    else if (reference) position = `第 ${reference.measure} 小节 · 音符参考`;
    else if (range) position = `第 ${range.firstMeasure}–${range.lastMeasure} 小节 · 段落`;
    else if (numberedSection && staffEvent) position = "简谱节选以外";
    else if (preview && !label) {
      if (sectionPreview && time > 0) position = "未定位谱行";
      else if (time > (events[0]?.time ?? Infinity)) position = "未定位音符";
    }
    $("#nowMeasure").textContent = position;
    $("#nowChord").textContent = window.MusicFollowPolicy.formatChord(label?.chord || "", data.song.sourceScoreId || data.song.scorePdf);
    $("#nowLyric").textContent = label?.isRest ? "休止" : label?.lyric || "";
    if (mode === "staff") paintStaff(ev, force);
    else if (numberedSection) paintJianpuSection(ev, tail && ending.staffEvent?.jianpuSection ? ending.staffEvent : ev, force);
    else paintJianpu(token, force);
    paintNoteReference(reference);
    updateHarmony(ev);
    if (tail && !numberedSection) keepEnding(force);
  }
  function setMode(value) {
    closeSize();
    paintHarmony(null, time);
    mode = value === "jianpu" && capabilities.hasNotation ? "jianpu" : "staff"; stopScroll(); lastScrollRow = "";
    $("#staffScore").hidden = mode !== "staff"; $("#jianpuScore").hidden = mode !== "jianpu";
    $("#notationSizeLabel").hidden = mode !== "jianpu";
    document.querySelectorAll("[data-score-view]").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.scoreView === mode)));
    wrap.dataset.mode = mode; renderNotation(); updateStatus(); update(true);
  }
  function seek(timeValue, eventIndex = null) {
    if (!Number.isFinite(timeValue)) return;
    manualCursor = paused ? window.MusicFollowPolicy.manualCursor(data.sync, data.jianpu, eventIndex) : null;
    time = timeValue; recordingEnded = false; restoreFollow(); update(true); send("music-seek", {time});
  }
  function nearest(page, x, y) {
    const rect = page.getBoundingClientRect(), nx = (x-rect.left)/rect.width, ny = (y-rect.top)/rect.height;
    return window.MusicFollowPolicy.nearestScoreEvent(seekEvents, page.dataset.page, nx, ny, time, capabilities.section, capabilities.canonicalCursor);
  }
  function seekNote(note) {
    if (!note?.hasAttribute("data-time")) return;
    const selected = window.MusicFollowPolicy.tokenAtSource(data.jianpu, data.sync, note.dataset.id, time);
    if (selected) seek(selected.time, selected.eventIndex);
  }
  function seekSection(control) {
    const event = window.MusicFollowPolicy.sectionAtMeasure(seekEvents, Number(control.dataset.sectionMeasure), time);
    if (event) seek(event.time);
  }
  wrap.addEventListener("click", (e) => {
    const control = e.target.closest(".jp-section-seek");
    if (control) seekSection(control);
  });
  wrap.addEventListener("dblclick", (e) => {
    const note = e.target.closest(".jp-note"), page = e.target.closest(".auto-page");
    if (note?.hasAttribute("data-time")) seekNote(note);
    else if (page) {const ev = nearest(page, e.clientX, e.clientY); if (ev) seek(ev.time, data.sync.events.indexOf(ev));}
  });
  wrap.addEventListener("wheel", browse, {passive: true});
  wrap.addEventListener("touchstart", browse, {passive: true});
  wrap.addEventListener("pointerdown", (e) => {if (e.target === wrap) browse();});
  wrap.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"].includes(e.key)) browse();
    const control = e.target.closest(".jp-section-seek");
    if (control && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault(); e.stopPropagation(); seekSection(control); return;
    }
    const note = e.target.closest(".jp-note");
    if (note?.hasAttribute("data-time") && e.key === "Enter") {e.preventDefault(); seekNote(note);}
  });
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !["BUTTON", "SELECT", "INPUT"].includes(e.target.tagName)) {e.preventDefault(); send("music-toggle");}
  });
  resume.onclick = () => {restoreFollow(); update(true);};
  $("#notationSize").onchange = (e) => {scale = Number(e.target.value); renderNotation(true);};
  const sizeButton = $("#sizeButton"), sizeMenu = $("#sizeMenu"), sizeControl = $("#notationSize");
  function closeSize() {sizeMenu.hidden=true;sizeButton.setAttribute("aria-expanded","false");}
  window.addEventListener("message",event=>{
    if(event.origin===location.origin && event.source===parent && event.data?.type==="music-close-controls")closeSize();
  });
  for (const option of sizeControl.options) {
    const button=document.createElement("button");button.type="button";button.textContent=option.text;
    button.setAttribute("role","menuitemradio");button.dataset.value=option.value;
    button.setAttribute("aria-checked",String(option.selected));
    button.onclick=()=>{
      sizeControl.value=option.value;sizeControl.onchange({target:sizeControl});
      sizeButton.textContent="字号 · "+option.text;
      [...sizeMenu.children].forEach(b=>b.setAttribute("aria-checked",String(b===button)));
      closeSize();sizeButton.focus();
    };sizeMenu.append(button);
  }
  sizeButton.onclick=()=>{
    const open=sizeMenu.hidden;closeSize();if(!open)return;
    const r=sizeButton.getBoundingClientRect();sizeMenu.hidden=false;
    sizeMenu.style.left=Math.min(r.left,innerWidth-sizeMenu.offsetWidth-8)+"px";
    sizeMenu.style.top=Math.max(8,Math.min(r.bottom+6,innerHeight-sizeMenu.offsetHeight-8))+"px";
    sizeButton.setAttribute("aria-expanded","true");sizeMenu.querySelector('[aria-checked="true"]').focus();
  };
  document.addEventListener("pointerdown",e=>{if(!sizeMenu.contains(e.target)&&!sizeButton.contains(e.target))closeSize();});
  document.addEventListener("keydown",e=>{
    if(sizeMenu.hidden)return;
    if(e.key==="Escape"){e.preventDefault();closeSize();sizeButton.focus();}
    else if(["ArrowDown","ArrowUp","Home","End"].includes(e.key)){
      e.preventDefault();const buttons=[...sizeMenu.children],at=buttons.indexOf(document.activeElement);
      const next=e.key==="Home"?0:e.key==="End"?buttons.length-1:(at+(e.key==="ArrowDown"?1:-1)+buttons.length)%buttons.length;
      buttons[next].focus();
    }
  });
  document.querySelectorAll("[data-score-view]").forEach((tab) => tab.onclick = () => setMode(tab.dataset.scoreView));
  new ResizeObserver(() => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {renderNotation(); update(true);});
  }).observe(wrap);
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || e.source !== parent || e.data?.type !== "music-time") return;
    const t = Number(e.data.time); if (!Number.isFinite(t) || t<0) return;
    const nextRevision = e.data.seekRevision;
    const jump = nextRevision != null ? seekRevision !== null && nextRevision !== seekRevision : t < time-.15 || t > time+1.2;
    if (nextRevision != null) seekRevision = nextRevision;
    if (typeof e.data.paused === "boolean") paused = e.data.paused;
    recordingEnded = ownerPlaybackEnded(t);
    manualCursor = window.MusicFollowPolicy.updateManualCursor(manualCursor, t, paused, jump);
    const wasVisible = visible; visible = e.data.visible !== false; time = t;
    if (jump && visible) restoreFollow();
    if (visible) {renderNotation(); update(jump || !wasVisible);}
    else if (wasVisible) updateHarmony(null);
  });
  const query = new URLSearchParams(location.search);
  const song = query.get("song") || "catchy-song";
  const preview = query.get("preview") === "1";
  window.MusicUnifiedModel.load(song, preview)
    .then((result) => {
      data = result;
      document.title = data.song.title + (preview ? " · 跟谱试用" : " · 歌曲跟谱");
      document.documentElement.dataset.readerStyle = "winter-wrap-up-v1";
      wrap.dataset.physicalTokenCount = String(data.jianpu.tokens.length);
      const tempo = data.jianpu.sourceTempoBeats?.points || data.jianpu.sourceTempoMap;
      const tempoNotice = $("#sourceTempoNotice");
      if (tempo?.length) {
        tempoNotice.textContent = "原谱速度 · " + tempo.map((p,i)=>(i?`第 ${p.measure} 小节 `:"")+`♩ = ${p.bpm}`).join(" · ");
        tempoNotice.hidden = false;
      }
      capabilities = window.MusicFollowPolicy.capabilities(data);
      if (preview && capabilities.section && data.jianpu.tokens.length && data.sync.events.length) {
        const measures = new Set(data.jianpu.measures.map(measure => measure.measure));
        const mapped = data.sync.events.filter(event => event.jianpuSection);
        const excerpt = data.song.jianpuExcerpt === true;
        sectionNotation = mapped.length > 0 && (excerpt || mapped.length === data.sync.events.length) && mapped.every(({jianpuSection}) => {
          const {firstMeasure, lastMeasure} = jianpuSection || {};
          if (!Number.isInteger(firstMeasure) || !Number.isInteger(lastMeasure) || firstMeasure > lastMeasure ||
              lastMeasure - firstMeasure >= measures.size) return false;
          for (let measure = firstMeasure; measure <= lastMeasure; measure++) if (!measures.has(measure)) return false;
          return true;
        });
      }
      if (sectionNotation) {
        capabilities.hasNotation = true;
        capabilities.notice = "未匹配的段落不会标记。";
        noteReferences = window.MusicFollowPolicy.sectionNoteReferences(data.jianpu, data.sync);
      }
      wrap.dataset.precision = capabilities.section ? "score-section" : "note";
      document.querySelector('[data-score-view="staff"]').textContent = capabilities.staffTitle;
      const jianpuTab = document.querySelector('[data-score-view="jianpu"]');
      jianpuTab.hidden = !capabilities.hasNotation;
      jianpuTab.disabled = !capabilities.hasNotation;
      resume.textContent = capabilities.resumeTitle;
      const previewNotice = preview && typeof data.song.previewNotice === "string" ? data.song.previewNotice : "";
      const notices = [preview ? "跟谱试用 · 部分谱面和同步时间仍在校对。" : "", previewNotice, capabilities.notice];
      $("#followNotice").textContent = notices.filter(Boolean).join(" ");
      $("#followNotice").hidden = !notices.some(Boolean);
      const keyNotice = $("#recordingKeyNotice");
      keyNotice.textContent = window.MusicFollowPolicy.recordingNotice(data);
      keyNotice.hidden = !keyNotice.textContent;
      const original = $("#originalScore");
      original.hidden = !data.song.scorePdf;
      const download = $("#downloadOriginal"); download.hidden = original.hidden;
      if (data.song.scorePdf) {
        download.href = data.song.scorePdf;
        original.onclick = () => {
          const scorePdf = data.song.scorePdf, title = data.song.title;
          if (parent !== window) send("music-open-score", {scorePdf,title});
          else location.href = "/?score="+encodeURIComponent(scorePdf)+"&title="+encodeURIComponent(title || "原谱");
        };
      }
      events = window.MusicFollowPolicy.cursorEvents(data.sync);
      if (preview) harmonyReferences = window.MusicFollowPolicy.harmonyReferences(data, events);
      tokens = window.MusicFollowPolicy.playbackTokens(data.jianpu, data.sync);
      ending = findEnding();
      seekEvents = window.MusicFollowPolicy.seekableEvents(data.sync);
      if (sectionNotation) {
        for (const {measure} of data.jianpu.measures) {
          if (window.MusicFollowPolicy.sectionAtMeasure(seekEvents, measure, 0)) sectionMeasures.add(measure);
        }
      }
      renderPages(); setMode(mode); restoreFollow(); update(true); send("music-ready");
    })
    .catch(() => {status.textContent = "跟谱暂时加载失败，请重新打开。";});
})();

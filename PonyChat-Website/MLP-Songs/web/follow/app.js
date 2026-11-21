/* The parent player owns time and sound. This frame only renders and navigates. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const wrap = $("#scoreWrap"), status = $("#stageStatus"), resume = $("#resumeFollow");
  let data = null, events = [], tokens = [], seekEvents = [], mode = "staff", time = 0;
  let paused = true, manualCursor = null;
  let following = true, visible = true, scale = 1, lastWidth = 0, resizeFrame = 0;
  let activeEvent = null, activeToken = null, activeRow = null, lastScrollRow = "";
  let noteElements = new Map(), rows = [], pages = new Map();
  let scrollFrame = 0, scrollTarget = null;
  let seekRevision = null;
  let capabilities = null;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
  function send(type, extra = {}) { if (parent !== window) parent.postMessage({type, ...extra}, location.origin); }
  function updateStatus() {
    if (!capabilities) return;
    status.textContent = capabilities.hasSync ? `${following ? "自动跟随" : "自由浏览"} · ${capabilities.interaction}` : capabilities.interaction;
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
    score.innerHTML = window.MusicNotation.render(data.jianpu, width, scale).html;
    noteElements = new Map();
    score.querySelectorAll(".jp-note").forEach((el) => {
      if (!noteElements.has(el.dataset.id)) noteElements.set(el.dataset.id, []);
      noteElements.get(el.dataset.id).push(el);
    });
    rows = [...score.querySelectorAll(".jp-row")];
    activeToken = null; activeRow = null;
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
  function renderRecordingKeyNotice() {
    if (!data) return;
    const notice = $("#recordingKeyNotice");
    notice.textContent = window.MusicFollowPolicy.recordingNotice(data);
    notice.hidden = !notice.textContent;
    const jianpuNotice = $("#jianpuKeyNotice");
    jianpuNotice.textContent = mode === "jianpu" ? window.MusicFollowPolicy.jianpuKeyNotice(data) : "";
    jianpuNotice.hidden = !jianpuNotice.textContent;
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
  }
  function paintJianpu(t, force) {
    if (!t) {
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
    if (row) {
      const rect = row.getBoundingClientRect();
      const tall = rect.height > wrap.clientHeight*.65;
      // A multi-voice system may be taller than a phone's reading area.
      keepRow(tall ? current.getBoundingClientRect() : rect, `jianpu:${current.dataset.row}${tall ? ":"+(t.lane || 0) : ""}`, force);
    }
  }
  function update(force = false) {
    if (!data || !visible) return;
    wrap.dataset.playbackTime = String(time);
    const pair = manualCursor && paused ? manualCursor : window.MusicFollowPolicy.cursorPair(events, tokens, time, capabilities.canonicalCursor, capabilities.section);
    const ev = pair.event, token = pair.token, label = mode === "jianpu" ? token : ev;
    $("#nowMeasure").textContent = window.MusicFollowPolicy.position(label, capabilities.section, time, events);
    $("#nowChord").textContent = window.MusicFollowPolicy.formatChord(label?.chord || "", data.song.sourceScoreId || data.song.scorePdf);
    $("#nowLyric").textContent = label?.isRest ? "休止" : label?.lyric || "";
    if (mode === "staff") paintStaff(ev, force); else paintJianpu(token, force);
  }
  function setMode(value) {
    mode = value === "jianpu" && capabilities.hasNotation ? "jianpu" : "staff"; stopScroll(); lastScrollRow = "";
    $("#staffScore").hidden = mode !== "staff"; $("#jianpuScore").hidden = mode !== "jianpu";
    $("#notationSizeLabel").hidden = mode !== "jianpu";
    renderRecordingKeyNotice();
    document.querySelectorAll("[data-score-view]").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.scoreView === mode)));
    wrap.dataset.mode = mode; renderNotation(); update(true);
  }
  function seek(timeValue, eventIndex = null) {
    if (!Number.isFinite(timeValue)) return;
    manualCursor = paused ? window.MusicFollowPolicy.manualCursor(data.sync, data.jianpu, eventIndex) : null;
    time = timeValue; restoreFollow(); update(true); send("music-seek", {time});
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
    const note = e.target.closest(".jp-note");
    if (note?.hasAttribute("data-time") && e.key === "Enter") {e.preventDefault(); seekNote(note);}
  });
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !["BUTTON", "SELECT", "INPUT"].includes(e.target.tagName)) {e.preventDefault(); send("music-toggle");}
  });
  resume.onclick = () => {restoreFollow(); update(true);};
  $("#notationSize").onchange = (e) => {scale = Number(e.target.value); renderNotation(true);};
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
    manualCursor = window.MusicFollowPolicy.updateManualCursor(manualCursor, t, paused, jump);
    const wasVisible = visible; visible = e.data.visible !== false; time = t;
    if (jump && visible) restoreFollow();
    if (visible) {renderNotation(); update(jump || !wasVisible);}
  });
  const song = new URLSearchParams(location.search).get("song") || "catchy-song";
  fetch("/api/follow/demo?song="+encodeURIComponent(song), {cache: "no-store"})
    .then((r) => {if (!r.ok) throw new Error("Score unavailable"); return r.json();})
    .then((result) => {
      data = result;
      capabilities = window.MusicFollowPolicy.capabilities(data);
      wrap.dataset.precision = capabilities.section ? "score-section" : "note";
      document.querySelector('[data-score-view="staff"]').textContent = capabilities.staffTitle;
      document.querySelector('[data-score-view="jianpu"]').hidden = !capabilities.hasNotation;
      resume.textContent = capabilities.resumeTitle;
      $("#followNotice").textContent = capabilities.notice;
      $("#followNotice").hidden = !capabilities.notice;
      renderRecordingKeyNotice();
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
      tokens = window.MusicFollowPolicy.playbackTokens(data.jianpu, data.sync);
      seekEvents = window.MusicFollowPolicy.seekableEvents(data.sync);
      renderPages(); setMode(mode); restoreFollow(); update(true); send("music-ready");
    })
    .catch(() => {status.textContent = "跟谱暂时加载失败，请重新打开。";});
})();

(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const panel = $("#lyricsLines");
  let rows = [], active = -1, generation = 0, follow = true, manualUntil = 0, offset = 0, strictExplicitEnd = false;
  let focusIndex = 0, browseTimer = 0, centerFrame = 0;
  let scrollFrame = 0, scrollTarget = null;
  let drag = null, suppressClick = false;
  function stopScroll() {
    cancelAnimationFrame(scrollFrame); scrollFrame = 0; scrollTarget = null;
  }
  function scrollToLine(top, smooth) {
    const target = Math.max(0, Math.min(top, panel.scrollHeight - panel.clientHeight));
    if (smooth && scrollFrame && scrollTarget === target) return;
    stopScroll();
    const from = panel.scrollTop;
    if (!smooth || Math.abs(target - from) < 1) {
      panel.scrollTop = target; return;
    }
    // Own the easing so automatic lyric changes animate consistently across browsers.
    const started = performance.now(), duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 180 : 560;
    scrollTarget = target;
    function step(now) {
      const progress = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      panel.scrollTop = from + (target - from) * eased;
      if (progress < 1) scrollFrame = requestAnimationFrame(step);
      else {scrollFrame = 0; scrollTarget = null;}
    }
    scrollFrame = requestAnimationFrame(step);
  }
  function canFollow() { return follow && Date.now() >= manualUntil; }
  function lyricAnchor() {
    const edge = Math.min(48, panel.clientHeight / 2);
    // Match the marked current-line band, measured against the whole viewport.
    const top = document.documentElement.clientHeight * .42 - panel.getBoundingClientRect().top;
    return Math.max(edge, Math.min(panel.clientHeight - edge, top));
  }
  function paintWheel() {
    panel.classList.toggle("browsing", !canFollow());
    Array.from(panel.children).forEach((line, i) => {
      line.classList.toggle("active", i === active);
      line.classList.toggle("drag-preview", !!drag?.moved && i === focusIndex);
      line.dataset.distance = String(Math.min(4, Math.abs(i - focusIndex)));
      line.setAttribute("aria-current", i === active ? "true" : "false");
    });
  }
  function centerCurrent(smooth = true, explicit = false) {
    if ((!explicit && !canFollow()) || $("#nowPlaying").hidden || $("#lyricsPane").hidden || !panel.clientHeight) return;
    const line = panel.children[focusIndex];
    if (!line) return;
    // offsetTop is already relative to this positioned scroll container.
    const top = line.offsetTop + line.offsetHeight / 2 - lyricAnchor();
    scrollToLine(top, smooth);
  }
  function layoutWheel() {
    if (!panel.clientHeight) return;
    const anchor = lyricAnchor();
    panel.style.paddingTop = Math.round(anchor) + "px";
    panel.style.paddingBottom = Math.round(panel.clientHeight - anchor) + "px";
    cancelAnimationFrame(centerFrame);
    centerFrame = requestAnimationFrame(() => centerCurrent(false));
  }
  new ResizeObserver(layoutWheel).observe(panel);
  const statuses = {excluded: "此版本不提供歌词，歌词仅用于正式发行的人声版本", instrumental: "纯音乐版本，没有人声歌词", "no-vocals-detected": "暂未识别到可靠的人声歌词", missing: "这首歌的歌词正在补充", "low-confidence": "这版音频的歌词识别仍需校对"};
  async function load(song) {
    stopScroll();
    const token = ++generation; rows = []; active = -1; focusIndex = 0; manualUntil = 0; offset = 0; strictExplicitEnd = false; clearTimeout(browseTimer); $("#lyricOffset").value = "0"; $("#offsetLabel").textContent = "0.0 秒";
    panel.replaceChildren(); $("#lyricsNotice").textContent = song ? "正在加载歌词…" : "选一首歌，查看双语歌词";
    $("#lyricsEmpty").hidden = false; $("#lyricsEmpty").textContent = $("#lyricsNotice").textContent; panel.hidden = true;
    if (!song) return;
    try {
      const res = await fetch("/api/lyrics?song=" + encodeURIComponent(song.id));
      if (!res.ok) throw new Error("Lyrics unavailable");
      const data = await res.json(); if (token !== generation) return;
      if (data.status !== "available") { $("#lyricsNotice").textContent = statuses[data.status] || statuses.missing; $("#lyricsEmpty").textContent = $("#lyricsNotice").textContent; return; }
      rows = data.lines || [];
      strictExplicitEnd = data.timingPolicy?.verified === true && data.timingPolicy.mode === "strict-explicit-end";
      $("#lyricsEmpty").hidden = true; panel.hidden = false;
      $("#lyricsNotice").textContent = data.reviewed ? "双语歌词 · 点击歌词跳转" : "自动对齐 · 中文意译 · 部分内容待校对";
      rows.forEach((row, i) => {
        const button = document.createElement("button"); button.type = "button"; button.className = "lyric-line";
        const en = document.createElement("span"); en.className = "lyric-en"; en.textContent = row.en;
        const zh = document.createElement("span"); zh.className = "lyric-zh"; zh.textContent = row.zh || "";
        if (row.kind === "dialogue") {
          const label = document.createElement("span"); label.className = "lyric-kind";
          label.textContent = row.speaker ? "对白 · " + row.speaker : "对白";
          button.append(label);
        }
        button.append(en, zh); button.onclick = () => seekSelected(i);
        button.setAttribute("aria-label", "跳转到 " + row.en); panel.append(button);
      });
      update($("#audio").currentTime);
      paintWheel(); layoutWheel();
    } catch (_) { if (token === generation) {$("#lyricsNotice").textContent = "歌词暂时加载失败，切换歌曲后可重试"; $("#lyricsEmpty").textContent = $("#lyricsNotice").textContent;} }
  }
  function update(time) {
    const t = time + offset;
    const audio = $("#audio");
    // A completed recording clears the line even when legacy display grace
    // extends beyond its duration. Pausing or seeking within it still follows.
    const completed = audio.ended === true;
    let lo = 0, hi = rows.length - 1;
    // Media seeks may settle a few microseconds below the requested timestamp.
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (rows[mid].start <= t + .00001) lo = mid + 1; else hi = mid - 1; }
    const next = !completed && hi >= 0 && (strictExplicitEnd ? t < rows[hi].end : t <= rows[hi].end + 1.5) ? hi : -1;
    const nextFocus = next >= 0 ? next : Math.min(rows.length - 1, Math.max(0, hi + 1));
    if (next === active && (drag?.moved || focusIndex === nextFocus)) return;
    active = next;
    if (!drag?.moved) focusIndex = nextFocus;
    paintWheel(); centerCurrent();
  }
  function browse() {
    stopScroll();
    manualUntil = Date.now() + 7000; paintWheel(); clearTimeout(browseTimer);
    browseTimer = setTimeout(() => { if (!$("#audio").paused) {paintWheel(); centerCurrent();} }, 7100);
  }
  function seekSelected(i) {
    if (!rows[i]) return;
    manualUntil = 0; clearTimeout(browseTimer); drag = null;
    window.MusicPlayer.seek(rows[i].start - offset); update(rows[i].start - offset);
    focusIndex = i; paintWheel(); centerCurrent(true, true);
  }
  function nearestToAnchor() {
    const rect = panel.getBoundingClientRect(), center = rect.top + lyricAnchor();
    let best = 0, distance = Infinity;
    Array.from(panel.children).forEach((line, i) => { const r = line.getBoundingClientRect(), d = Math.abs(r.top + r.height / 2 - center); if (d < distance) {distance = d; best = i;} });
    return best;
  }
  panel.addEventListener("wheel", browse, {passive: true});
  panel.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    suppressClick = false; browse();
    drag = {id: e.pointerId, x: e.clientX, y: e.clientY, scroll: panel.scrollTop, moved: false};
  });
  panel.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dy) < 6) return;
    if (!drag.moved) {drag.moved = true; panel.setPointerCapture(e.pointerId); panel.classList.add("dragging");}
    e.preventDefault(); panel.scrollTop = drag.scroll - dy; focusIndex = nearestToAnchor(); paintWheel();
  });
  panel.addEventListener("pointerup", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const moved = drag.moved, picked = focusIndex;
    if (panel.hasPointerCapture(e.pointerId)) panel.releasePointerCapture(e.pointerId);
    panel.classList.remove("dragging"); drag = null;
    if (moved) {suppressClick = true; seekSelected(picked);}
  });
  panel.addEventListener("pointercancel", () => {panel.classList.remove("dragging"); drag = null; paintWheel();});
  panel.addEventListener("click", (e) => {if (suppressClick) {e.preventDefault(); e.stopImmediatePropagation(); suppressClick = false;}}, true);
  $("#followLyrics").onclick = (e) => {follow = !follow; e.currentTarget.setAttribute("aria-pressed", String(follow)); manualUntil = 0; clearTimeout(browseTimer); if (!follow) stopScroll(); paintWheel(); centerCurrent();};
  $("#lyricOffset").oninput = (e) => {offset = Number(e.target.value); $("#offsetLabel").textContent = offset.toFixed(1) + " 秒"; active = -1; update($("#audio").currentTime);};
  $("#resumeLyrics").onclick = () => {manualUntil = 0; follow = true; $("#followLyrics").setAttribute("aria-pressed", "true"); $("#playerTools").open = false; paintWheel(); centerCurrent();};
  window.MusicLyrics = {load, update, refresh: () => {paintWheel(); layoutWheel();}};
})();

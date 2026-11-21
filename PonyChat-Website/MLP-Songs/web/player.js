/* In-memory listening session. A fresh page never restores or starts playback. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const audio = $("#audio");
  const modes = ["sequence", "shuffle", "single", "loop"];
  const names = { sequence: "顺序播放", shuffle: "随机播放", single: "单曲循环", loop: "列表循环" };
  let queue = [], index = -1, mode = "sequence", normalize = false, request = 0, status = "选一首歌，开始听吧", savedVolume = 1;
  let onSong = () => {}, onQueue = () => {}, onTime = () => {};
  let pendingSeek = null;
  let followRaf = 0, lastFollow = 0, followSeekRevision = 0;
  const preload = new Audio(); preload.preload = "metadata";
  function preloadNext() {
    if (navigator.connection?.saveData || mode === "shuffle") {preload.removeAttribute("src"); return;}
    const song = queue[index + 1] || (mode === "loop" ? queue[0] : null);
    if (song && song.src !== preload.getAttribute("src")) preload.src = song.src;
  }
  function sendFollow() {
    const frame = $("#followFrame");
    if (frame.contentWindow && frame.getAttribute("src")) frame.contentWindow.postMessage({type: "music-time", time: audio.currentTime, paused: audio.paused, seekRevision: followSeekRevision, visible: !$("#followPane").hidden && !$("#nowPlaying").hidden}, location.origin);
  }
  function visibleLyrics() { return !$("#lyricsPane").hidden && !$("#nowPlaying").hidden; }
  function visibleClock() { return !$("#nowPlaying").hidden && (!$("#followPane").hidden || visibleLyrics()); }
  function syncFollow() {
    cancelAnimationFrame(followRaf); sendFollow();
    if (visibleLyrics()) onTime(audio.currentTime);
    function tick(stamp) {
      if (audio.paused || !visibleClock()) { followRaf = 0; return; }
      if (stamp - lastFollow >= 40) {
        if (visibleLyrics()) onTime(audio.currentTime);
        if (!$("#followPane").hidden) sendFollow();
        lastFollow = stamp;
      }
      followRaf = requestAnimationFrame(tick);
    }
    if (!audio.paused && visibleClock()) followRaf = requestAnimationFrame(tick);
  }
  const escape = (s) => { const el = document.createElement("span"); el.textContent = s || ""; return el.innerHTML; };
  function current() { return queue[index] || null; }
  function setStatus(text, retry = false) {
    status = text; $("#playbackStatus").textContent = text;
    $("#retryPlayback").hidden = !retry;
    $(".playback-alert").hidden = !retry;
  }
  function volume() {
    const gain = normalize ? Number(current()?.normalizationGain || 1) : 1;
    audio.volume = Math.max(0, Math.min(1, savedVolume * gain));
  }
  function renderQueue() {
    const list = $("#queueList"); list.replaceChildren();
    queue.forEach((song, i) => {
      const row = document.createElement("li"); row.className = i === index ? "current" : "";
      const play = document.createElement("button"); play.type = "button"; play.className = "queue-song";
      play.innerHTML = `<span>${i + 1}</span><span>${escape(song.title)}</span>`;
      play.setAttribute("aria-label", "播放 " + song.title); play.onclick = () => playAt(i);
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "queue-remove"; remove.textContent = "×";
      remove.setAttribute("aria-label", "移除 " + song.title); remove.onclick = () => removeAt(i);
      row.append(play, remove); list.append(row);
    });
    $("#queueCount").textContent = `${queue.length} 首 · 本次收听`;
    $("#queueEmpty").hidden = queue.length > 0;
    preloadNext();
    onQueue(queue, index);
  }
  function mediaSession(song) {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = song ? new MediaMetadata({title: song.title, artist: (song.characters || []).join("、") || "My Little Pony", album: song.albumTitle || "MLP Music", artwork: song.cover ? [{src: new URL(song.cover, location.href).href}] : []}) : null;
    const actions = {play: resume, pause: () => audio.pause(), previoustrack: previous, nexttrack: next, seekto: (d) => seek(d.seekTime), seekbackward: (d) => seek(audio.currentTime - (d.seekOffset || 10)), seekforward: (d) => seek(audio.currentTime + (d.seekOffset || 10))};
    Object.entries(actions).forEach(([key, fn]) => { try { navigator.mediaSession.setActionHandler(key, fn); } catch (_) {} });
  }
  async function resume() {
    if (!current()) return;
    const token = ++request; setStatus("正在加载…");
    try { await audio.play(); if (token !== request) return; setStatus("正在播放"); }
    catch (err) { if (token !== request || err.name === "AbortError") return; setStatus(err.name === "NotAllowedError" ? "请点击播放开始收听" : "暂时无法播放，点击重试", true); }
  }
  function playAt(i, autoplay = true) {
    if (i < 0 || i >= queue.length) return;
    ++request; audio.pause(); index = i;
    pendingSeek = null;
    audio.src = current().src; volume();
    $("#seek").value = "0"; $("#seek").style.setProperty("--fill", "0%");
    const duration = current().duration || 0;
    const total = Math.floor(duration / 60) + ":" + String(Math.floor(duration % 60)).padStart(2, "0");
    $("#timeLabel").textContent = "0:00 / " + total; $("#timeCurrent").textContent = "0:00"; $("#timeTotal").textContent = total;
    $("#playerTitle").textContent = current().title;
    $("#playerSub").textContent = current().albumTitle || "My Little Pony";
    $("#playerArt").style.backgroundImage = current().cover ? `url(${JSON.stringify(current().cover)})` : "";
    $("#downloadCurrent").href = current().src;
    $("#downloadCurrent").hidden = false;
    $("#downloadCurrent").setAttribute("download", current().title + ".mp3");
    $("#nowTitle").textContent = current().title;
    $("#nowSubtitle").textContent = [current().alias, current().albumTitle, current().episode, ...(current().characters || [])].filter(Boolean).join(" · ");
    $("#nowCover").src = current().cover || "/logo.png";
    $("#nowQuality").textContent = current().bitrate ? `MP3 · ${current().bitrate} kbps` : "";
    $("#followTab").hidden = !current().followId;
    $("#songScoreLink").hidden = !current().scoreId;
    $("#followFrame").removeAttribute("src");
    window.MusicAmbient?.setSong(current());
    mediaSession(current()); renderQueue(); onSong(current()); setStatus("已就绪");
    if (autoplay) resume();
  }
  function play(song, songs = [song]) { queue = songs.slice(); index = queue.findIndex((s) => s.id === song.id); if (index < 0) { queue.unshift(song); index = 0; } playAt(index); }
  function add(song, immediatelyNext = false) {
    if (!current()) { queue.push(song); playAt(0, false); }
    else { if (immediatelyNext) queue.splice(index + 1, 0, song); else queue.push(song); renderQueue(); }
    setStatus(immediatelyNext ? "已加入下一首" : "已加入本次队列");
  }
  function removeAt(i) {
    if (i === index) { queue.splice(i, 1); if (queue.length) playAt(Math.min(i, queue.length - 1), !audio.paused); else clear(); }
    else { queue.splice(i, 1); if (i < index) index--; renderQueue(); }
  }
  function clear() {
    ++request; audio.pause(); audio.removeAttribute("src"); audio.load(); queue = []; index = -1;
    pendingSeek = null;
    preload.removeAttribute("src"); preload.load();
    window.MusicAmbient?.setSong(null);
    mediaSession(null); renderQueue(); $("#playerTitle").textContent = "未播放"; $("#playerSub").textContent = "";
    $("#nowTitle").textContent = "选一首歌，开始听吧"; $("#nowSubtitle").textContent = "";
    $("#followFrame").removeAttribute("src"); onSong(null); setStatus("队列已清空");
    $("#nowCover").src = "/logo.png"; $("#nowQuality").textContent = "";
    $("#followTab").hidden = true; $("#songScoreLink").hidden = true;
    $("#downloadCurrent").href = "#";
    $("#downloadCurrent").hidden = true;
  }
  function next(ended = false) {
    if (!queue.length) return;
    if (mode === "single" && ended) { seek(0); resume(); return; }
    if (mode === "shuffle" && queue.length > 1) { const step = 1 + Math.floor(Math.random() * (queue.length - 1)); playAt((index + step) % queue.length); }
    else if (index + 1 < queue.length) playAt(index + 1);
    else if (mode === "loop") playAt(0);
    else if (ended) setStatus("本次队列已播完");
  }
  function previous() { if (audio.currentTime > 3) seek(0); else if (index > 0) playAt(index - 1); }
  function seek(t) {
    if (!current() || !Number.isFinite(t)) return;
    if (Number.isFinite(audio.duration)) {audio.currentTime = Math.max(0, Math.min(audio.duration, t)); pendingSeek = null;}
    else pendingSeek = {songId: current().id, time: Math.max(0, t)};
  }
  audio.addEventListener("loadedmetadata", () => {if (pendingSeek?.songId === current()?.id) seek(pendingSeek.time);});
  audio.addEventListener("seeking", () => {followSeekRevision++; sendFollow();});
  function toggle() { audio.paused ? resume() : audio.pause(); }
  $("#btnPlay").onclick = toggle; $("#btnPrev").onclick = previous; $("#btnNext").onclick = () => next();
  $("#retryPlayback").onclick = () => { const t = audio.currentTime, songId = current()?.id, token = ++request; audio.addEventListener("loadedmetadata", () => { if (current()?.id === songId && token === request) {seek(t); resume();} }, {once: true}); audio.load(); };
  $("#playMode").onclick = () => { mode = modes[(modes.indexOf(mode) + 1) % modes.length]; $("#playMode").textContent = names[mode]; preloadNext(); };
  $("#normalizeVolume").onclick = (e) => { normalize = !normalize; e.currentTarget.setAttribute("aria-pressed", String(normalize)); volume(); };
  $("#vol").addEventListener("input", (e) => { savedVolume = Number(e.target.value) / 100; volume(); });
  $("#clearQueue").onclick = clear;
  ["waiting", "stalled"].forEach((event) => audio.addEventListener(event, () => { if (!audio.paused) setStatus("正在缓冲…"); }));
  audio.addEventListener("error", () => { if (current()) setStatus("音频加载失败，点击重试", true); });
  audio.addEventListener("playing", () => setStatus("正在播放"));
  audio.addEventListener("pause", () => { if (current() && !audio.ended && !audio.error) setStatus("已暂停"); });
  audio.addEventListener("ended", () => {next(true); onTime(audio.currentTime); syncFollow();});
  ["play", "pause"].forEach((event) => audio.addEventListener(event, () => {
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
    $("#nowPlay").textContent = audio.paused ? "播放" : "暂停";
    syncFollow();
  }));
  $("#nowPlay").onclick = toggle;
  $("#nowPrev").onclick = previous; $("#nowNext").onclick = () => next();
  audio.addEventListener("timeupdate", () => {
    onTime(audio.currentTime);
    sendFollow();
    if ("mediaSession" in navigator && navigator.mediaSession.setPositionState && Number.isFinite(audio.duration) && audio.duration > 0) {
      try { navigator.mediaSession.setPositionState({duration: audio.duration, playbackRate: 1, position: Math.min(audio.duration, audio.currentTime)}); } catch (_) {}
    }
  });
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || e.source !== $("#followFrame").contentWindow) return;
    if (e.data?.type === "music-seek" && Number.isFinite(e.data.time)) seek(e.data.time);
    if (e.data?.type === "music-ready") sendFollow();
    if (e.data?.type === "music-toggle") toggle();
    if (e.data?.type === "music-open-score") window.MusicScores?.open(e.data.scorePdf,e.data.title);
  });
  window.MusicPlayer = { play, add, clear, current, seek, toggle, syncFollow, getQueue: () => queue.slice(), setCallbacks: (callbacks) => {onSong = callbacks.onSong || onSong; onQueue = callbacks.onQueue || onQueue; onTime = callbacks.onTime || onTime;}, getStatus: () => status };
})();

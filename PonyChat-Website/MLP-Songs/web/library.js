(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const credits = window.MusicRecordingCredits;
  const labels = {original: "正式版", instrumental: "伴奏", demo: "Demo", credits: "片尾", alternate: "其他版本"};
  let data = null, searchRequest = 0, lastFocus = null, shareTimer = 0;
  let followPreloadTimer = 0;
  let followFeedback = null;
  let followValidationRequest = 0;
  let followValidationWait = null;
  const escape = (s) => { const e = document.createElement("span"); e.textContent = s || ""; return e.innerHTML; };
  function defaultVisible(song) { return song.releaseKind === "official" || song.showByDefault === true; }
  function isAccompaniment(song) { return song.versionKind === "instrumental"; }
  function showVersions() { return $("#includeVersions").getAttribute("aria-pressed") === "true"; }
  function visible(songs) {
    const versions = showVersions();
    return songs.filter((song) => !song.supersededBy && (versions || defaultVisible(song)));
  }
  function audioDownloadName(song) {
    if (!Number.isFinite(song.normalizedPeakDbfs)) return song.title + ".mp3";
    const ext = song.normalizedAudioExt;
    return song.title + "." + (ext === "wav" || ext === "opus" ? ext : "flac");
  }
  function updateAudioPresentation(song) {
    if (!song) return;
    if (song.normalizedAudioExt === "opus" && Number.isFinite(song.normalizedAudioBitrate))
      $("#nowQuality").textContent = "Opus · " + song.normalizedAudioBitrate + " kbps";
    else if (Number.isFinite(song.normalizedPeakDbfs))
      $("#nowQuality").textContent = (song.normalizedAudioExt === "wav" ? "WAV" : "FLAC") + " · 峰值 −0.1 dBFS";
    $("#downloadCurrent").download = audioDownloadName(song);
  }
  function enrich() {
    const ponyTownRank = 4;
    const rank = (album) => {
      if (album.id.startsWith("season-")) return 0;
      if (album.id === "credits") return 1;
      if (album.id.startsWith("equestria-girls")) return 2;
      return album.id.startsWith("soundtracks-pony-town-") ? ponyTownRank : 3;
    };
    data.albums.sort((a, b) => {
      const groupOrder = rank(a) - rank(b);
      if (groupOrder) return groupOrder;
      const releaseOrder = rank(a) === ponyTownRank
        ? (a.releaseDate || "9999").localeCompare(b.releaseDate || "9999") : 0;
      return releaseOrder || a.id.localeCompare(b.id);
    });
    const albums = new Map(data.albums.map((a) => [a.id, a]));
    const scores = data.scores.map((score) => ({score, title: (score.title || "").toLowerCase().replace(/[^a-z0-9]/g, "")}));
    data.songs.forEach((song) => {
      const album = albums.get(song.albumId); song.albumTitle = album?.title || ""; song.cover = album?.cover || "";
      const title = (song.baseTitle || song.title).toLowerCase().replace(/[^a-z0-9]/g, "");
      const match = title.length > 5 && scores.find((entry) => entry.title.includes(title));
      if (match) song.scoreId = match.score.id;
    });
  }
  function closeSongMenus() {
    document.querySelectorAll(".song-actions[open]").forEach((actions) => { actions.open = false; });
  }

  function positionSongMenu(summary, menu) {
    const gap = 6;
    const pane = $("#panelMusic").getBoundingClientRect();
    const anchor = summary.getBoundingClientRect();
    const top = Math.max(0, pane.top) + gap;
    const bottom = Math.min(pane.bottom, $("#player").getBoundingClientRect().top) - gap;
    const left = Math.max(0, pane.left) + gap;
    const right = Math.min(pane.right, document.documentElement.clientWidth) - gap;
    const aboveEdge = Math.min(anchor.top - gap, bottom);
    const belowEdge = Math.max(anchor.bottom + gap, top);
    const above = Math.max(0, aboveEdge - top);
    const below = Math.max(0, bottom - belowEdge);
    menu.style.maxWidth = Math.max(0, right - left) + "px";
    menu.style.maxHeight = "";
    const opensAbove = menu.offsetHeight > below && above > below;
    menu.style.maxHeight = (opensAbove ? above : below) + "px";
    menu.style.top = (opensAbove ? aboveEdge - menu.offsetHeight : belowEdge) + "px";
    menu.style.left = Math.max(left, Math.min(anchor.right, right) - menu.offsetWidth) + "px";
  }

  function rowList(container, songs, context = songs) {
    container.replaceChildren();
    if (!songs.length) { const empty = document.createElement("p"); empty.className = "empty-results"; empty.textContent = "没有找到歌曲，试试其他歌名或开启其他版本。"; container.append(empty); return; }
    const ul = document.createElement("ul"); ul.className = "song-results";
    const grouped = container.id === "trackList" && songs.some(isAccompaniment);
    let section = "", afterAccompaniments = false;
    songs.forEach((song) => {
      if (grouped) {
        const accompaniment = isAccompaniment(song);
        const nextSection = accompaniment ? "伴奏" : afterAccompaniments ? "其他版本" : "原曲";
        afterAccompaniments ||= accompaniment;
        if (nextSection !== section) {
          const entry = document.createElement("li"); entry.className = "album-track-heading";
          const heading = document.createElement("h3"); heading.textContent = nextSection;
          entry.append(heading); ul.append(entry);
          section = nextSection;
        }
      }
      const li = document.createElement("li"); li.className = "song-row"; li.dataset.songId = song.id;
      const play = document.createElement("button"); play.type = "button"; play.className = "song-main"; play.setAttribute("aria-label", "播放 " + song.title);
      const credit = credits.compact(song);
      const subtitle = [credit, song.lyricSnippet || [song.alias, song.albumTitle].filter(Boolean).join(" · ")].filter(Boolean).join(" · ");
      play.innerHTML = `<img src="${escape(song.cover || "/logo.png")}" alt="" loading="lazy" /><span class="song-text"><span class="song-title">${escape(song.title)}${song.versionKind !== "original" ? `<span class="version-badge">${labels[song.versionKind] || "其他版本"}</span>` : ""}</span><span class="song-details">${escape(subtitle)}</span></span>`;
      play.onclick = () => { window.MusicPlayer.play(song, context); markPlaying(song.id); };
      const duration = document.createElement("span"); duration.className = "song-duration";
      duration.textContent = song.duration ? `${Math.floor(song.duration / 60)}:${String(Math.floor(song.duration % 60)).padStart(2, "0")}` : "";
      const actions = document.createElement("details"); actions.className = "song-actions";
      const summary = document.createElement("summary"); summary.textContent = "•••"; summary.setAttribute("aria-label", song.title + " 更多操作");
      const menu = document.createElement("div"); menu.className = "song-action-menu";
      summary.onclick = (e) => {
        e.preventDefault();
        const open = !actions.open;
        closeSongMenus();
        actions.open = open;
        if (open) positionSongMenu(summary, menu);
      };
      actions.onkeydown = (e) => {
        if (e.key !== "Escape" || !actions.open) return;
        e.preventDefault();
        actions.open = false;
        summary.focus({preventScroll: true});
      };
      [["下一首播放", () => window.MusicPlayer.add(song, true)], ["加入播放队列", () => window.MusicPlayer.add(song)], ["查看歌词", () => { if (window.MusicPlayer.current()?.id !== song.id) window.MusicPlayer.play(song, context); openNow("lyrics"); }], ["分享歌曲", () => share(song)]].forEach(([label, fn]) => {
        const button = document.createElement("button"); button.type = "button"; button.textContent = label; button.onclick = () => { actions.open = false; fn(); }; menu.append(button);
      });
      const download = document.createElement("a"); download.textContent = "下载音频"; download.href = song.src; download.download = audioDownloadName(song); menu.append(download);
      actions.append(summary, menu); li.append(play, duration, actions); ul.append(li);
    });
    container.append(ul); markPlaying(window.MusicPlayer.current()?.id);
  }
  function markPlaying(id) { document.querySelectorAll("[data-song-id]").forEach((el) => el.classList.toggle("playing", el.dataset.songId === id)); }
  async function search(q) {
    $("#includeVersions").hidden = false;
    const token = ++searchRequest;
    $("#panelMusic").classList.add("search-mode"); $("#panelMusic").classList.remove("album-open");
    $("#albumGrid").classList.add("hidden"); $("#trackPanel").classList.add("hidden"); $("#searchResults").classList.remove("hidden");
    $("#libraryHeading").textContent = `搜索“${q}”`;
    const terms = q.toLowerCase().split(/\s+/);
    const matches = visible(data.songs.filter((song) => {
      const hay = [song.title, song.alias, song.albumTitle, song.episode, ...credits.searchTerms(song)].join(" ").toLowerCase(); return terms.every((term) => hay.includes(term));
    }));
    rowList($("#searchResults"), matches);
    try {
      const res = await fetch("/api/search?q=" + encodeURIComponent(q) + "&versions=" + showVersions());
      if (!res.ok) return; const results = await res.json(); if (token !== searchRequest || $("#q").value.trim().toLowerCase() !== q.toLowerCase()) return;
      const local = new Map(data.songs.map((s) => [s.id, s]));
      const combined = new Map(matches.map((song) => [song.id, song]));
      for (const result of results.songs) {
        const song = local.get(result.id);
        if (song) combined.set(song.id, result.lyricSnippet ? {...song, lyricSnippet: result.lyricSnippet} : song);
      }
      const songs = visible([...combined.values()]);
      rowList($("#searchResults"), songs);
      $("#libraryHeading").textContent = `搜索“${q}” · ${songs.length} 首`;
    } catch (_) {}
  }
  function albumSongs(id) {
    const tracks = data.songs.filter((song) => song.albumId === id && !song.supersededBy);
    if (showVersions()) return tracks;
    const filtered = tracks.filter((song) => defaultVisible(song)
      || (isAccompaniment(song) && song.showByDefault !== false));
    return filtered.length ? filtered : tracks;
  }
  function openNow(name = "lyrics") {
    if ($("#nowPlaying").hidden) lastFocus = document.activeElement;
    $("#nowPlaying").hidden = false; syncNowToggles(); selectPane(name); $("#closeNow").focus();
  }
  function closeNow() { $("#playerTools").open = false; $("#nowPlaying").hidden = true; syncNowToggles(); window.MusicPlayer.syncFollow(); if (lastFocus?.isConnected) lastFocus.focus(); }
  function syncNowToggles() {
    const expanded = !$("#nowPlaying").hidden;
    ["#playerTitle", "#playerArt", "#playerSub"].forEach((selector) => {
      $(selector).setAttribute("aria-expanded", String(expanded));
      $(selector).title = expanded ? "收起歌曲详情" : "展开歌曲详情与歌词";
    });
  }
  function toggleNow() { if ($("#nowPlaying").hidden) openNow("lyrics"); else closeNow(); }
  function readerNotice(message) {
    const pane = $("#followPane");
    if (!pane.prepend) return false;
    let notice = $("#followReaderStatus");
    if (!notice) {
      notice = document.createElement("p"); notice.id = "followReaderStatus";
      notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
      pane.prepend(notice);
    }
    notice.textContent = message; notice.hidden = false;
    return true;
  }
  const previewRecordings = new Map();
  const previewFor = (song) => {
    const preview = previewRecordings.get(song?.id);
    return preview?.src === song?.src ? preview?.followId : null;
  };
  const readerId = (song) => song?.followId || previewFor(song);
  function refreshFollowTab(song) {
    const tab = $("#followTab");
    tab.hidden = !readerId(song);
    tab.textContent = !song?.followId && previewFor(song) ? "跟谱试用" : "跟谱";
  }
  async function loadFollowPreviews() {
    try {
      const response = await fetch("/follow/layouts/preview/index.json", {cache: "no-cache"});
      if (!response.ok) return;
      const entries = await response.json();
      if (!Array.isArray(entries)) return;
      previewRecordings.clear();
      for (const entry of entries) {
        if (typeof entry?.songId === "string" && typeof entry.src === "string" &&
            typeof entry.followId === "string" && /^[a-z0-9-]+$/.test(entry.followId)) {
          previewRecordings.set(entry.songId, entry);
        }
      }
      const song = window.MusicPlayer.current();
      if (song && !song.followId && previewFor(song)) prefetchFollow(song);
    } catch (_) {
      // The library and verified readers can load while previews are unavailable.
    }
  }
  function currentReader(state = followFeedback) {
    const song = window.MusicPlayer.current();
    return state && state === followFeedback && $("#followFrame") === state.frame &&
      state.frame.getAttribute("src") === state.target && song?.id === state.id &&
      song.src === state.src && readerId(song) === state.followId &&
      song.followId === state.approvedId && song.followViewPath === state.followViewPath;
  }
  function readerHasBody(frame) {
    try {
      return !!frame.getAttribute("src") && frame.contentWindow.location.href === location.origin + frame.getAttribute("src") &&
        frame.contentDocument?.body?.childElementCount > 0;
    } catch (_) {return false;}
  }
  function stopReaderFeedback() {
    if (followFeedback) clearTimeout(followFeedback.timer);
    followFeedback = null;
    const notice = $("#followReaderStatus");
    if (notice) notice.hidden = true;
  }
  function beginReaderFeedback(song, frame, target) {
    stopReaderFeedback();
    const state = {frame, target, id: song.id, src: song.src, followId: readerId(song),
      approvedId: song.followId, followViewPath: song.followViewPath};
    followFeedback = state;
    if (readerNotice("正在加载谱面…")) state.timer = setTimeout(() => {
      if (!currentReader(state)) return;
      readerNotice(readerHasBody(frame) ? "谱面已打开" : "谱面加载较慢，请稍候…");
    }, 8000);
    return state;
  }
  function inspectFollowFrame(frame, phase) {
    if (!frame.dataset) return;
    frame.dataset.readerCheck = phase;
    try {
      frame.dataset.readerLocation = frame.contentWindow.location.href;
      frame.dataset.readerDocumentState = frame.contentDocument?.readyState || "unavailable";
      frame.dataset.readerChildren = String(frame.contentDocument?.body?.childElementCount ?? -1);
      frame.dataset.readerAccess = "same-origin";
    } catch (_) {frame.dataset.readerAccess = "blocked";}
  }
  function expandCompactScore(frame) {
    if (frame.dataset?.staffReflow !== "true" || $("#followPane").hidden || $("#nowPlaying").hidden ||
        !window.matchMedia?.("(max-width: 700px), (max-height: 500px) and (orientation: landscape)").matches) return;
    window.requestAnimationFrame(() => {
      const expand = $("#expandFollow");
      if (expand && !expand.hidden && !$("#followPane").hidden && frame.dataset.staffReflow === "true") expand.click();
    });
  }
  window.addEventListener?.("message", (event) => {
    const frame = $("#followFrame");
    if (event.origin === location.origin && event.source === frame?.contentWindow && event.data?.type === "music-ready" &&
        currentReader() && readerHasBody(frame)) {
      frame.dataset.readerReady = "true";
      frame.dataset.staffReflow = String(event.data.staffReflow === true);
      clearTimeout(followFeedback.timer); readerNotice("谱面加载完成");
      inspectFollowFrame(frame, "music-ready");
      expandCompactScore(frame);
    }
  });
  function prepareFollow(song) {
    const id = readerId(song);
    if (!id || !/^[a-z0-9-]+$/.test(id)) return;
    const frame = $("#followFrame");
    const target = "/follow/unified/index.html?v=20261111-4&song=" + encodeURIComponent(id) +
      (song.followId ? "" : "&preview=1");
    if (!frame.getAttribute("src")) {
      const feedback = beginReaderFeedback(song, frame, target);
      frame.onload = () => {
        inspectFollowFrame(frame, "load");
        if (currentReader(feedback) && readerHasBody(frame) && frame.dataset?.readerReady !== "true") {
          clearTimeout(feedback.timer); readerNotice("谱面已打开");
        }
        window.MusicPlayer.syncFollow();
      };
      if (frame.dataset) {
        frame.dataset.readerReady = "false"; frame.dataset.readerRecovery = "disabled";
        delete frame.dataset.staffReflow;
      }
      frame.src = target;
    }
    inspectFollowFrame(frame, "prepare");
  }
  function prefetchFollow(song) {
    clearTimeout(followPreloadTimer);
    if (followFeedback && !currentReader()) stopReaderFeedback();
    refreshFollowTab(song);
    if (!readerId(song) || navigator.connection?.saveData) return;
    // Start the same shared reader once the recording is selected, without
    // switching panes. Rapid skips never preload the previous recording.
    followPreloadTimer = setTimeout(() => {
      if (window.MusicPlayer.current()?.id === song.id) prepareFollow(song);
    }, 300);
  }
  function applyFollowAvailability(songs, verifiedSongs) {
    const verified = new Map(verifiedSongs.map(({id, src, followId, followViewPath}) => [id, {src, followId, followViewPath}]));
    const current = window.MusicPlayer.current();
    const previous = [current?.followId, current?.followViewPath];
    // Search results and queues may hold copies. Update those exact objects too,
    // without replacing the library, selected recording, queue or audio source.
    const targets = new Set([...songs, ...(window.MusicPlayer.getQueue?.() || []), ...(current ? [current] : [])]);
    for (const song of targets) {
      delete song.followId; delete song.followViewPath;
      const accepted = verified.get(song.id);
      if (typeof accepted?.followId !== "string" || !/^[a-z0-9-]+$/.test(accepted.followId)) continue;
      if (typeof song.src === "string" && typeof accepted.src === "string" && song.src !== accepted.src) continue;
      song.followId = accepted.followId;
      if (typeof accepted.followViewPath === "string") song.followViewPath = accepted.followViewPath;
    }
    window.MusicFollowBadges?.setSongs(songs);
    refreshFollowTab(current);
    if (previous[0] !== current?.followId || previous[1] !== current?.followViewPath) {
      clearTimeout(followPreloadTimer);
      $("#followFrame").removeAttribute("src");
      stopReaderFeedback();
      if (!readerId(current) && !$("#followPane").hidden) selectPane("lyrics");
    }
    if (readerId(current)) prefetchFollow(current);
  }
  async function validateFollows(songs, request) {
    void loadFollowPreviews();
    const token = ++followValidationRequest;
    if (followValidationWait) {
      clearTimeout(followValidationWait.timer);
      followValidationWait.resolve(false);
      followValidationWait = null;
    }
    const deadline = Date.now() + 20 * 60 * 1000;
    while (token === followValidationRequest && Date.now() < deadline) {
      try {
        const result = await request("/api/songs");
        if (!Array.isArray(result?.songs)) throw new Error("Invalid songs validation response");
        if (token === followValidationRequest && Date.now() < deadline) applyFollowAvailability(songs, result.songs);
        return;
      } catch (error) {
        if (token !== followValidationRequest) return;
        applyFollowAvailability(songs, []);
        if (error?.status !== 503 || error?.warming !== true) return;
        const remaining = deadline - Date.now();
        if (remaining <= 0) return;
        const delay = Math.min(remaining, Math.max(1000, Math.min(30000, Number(error.retryAfterMs) || 3000)));
        const active = await new Promise((resolve) => {
          const wait = {resolve, timer: setTimeout(() => {
            if (followValidationWait === wait) followValidationWait = null;
            resolve(token === followValidationRequest);
          }, delay)};
          followValidationWait = wait;
        });
        if (!active) return;
      }
    }
  }
  function selectPane(name) {
    const song = window.MusicPlayer.current();
    if (!readerId(song)) stopReaderFeedback();
    if (name === "follow" && !readerId(song)) name = "lyrics";
    $("#nowPlaying").classList.toggle("follow-focused", name === "follow");
    document.querySelectorAll("[data-now-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.nowTab === name)));
    ["lyrics", "queue", "follow"].forEach((key) => $("#" + key + "Pane").hidden = key !== name);
    if (name === "follow") {
      prepareFollow(window.MusicPlayer.current());
    }
    if (name === "lyrics") {window.MusicLyrics.update($("#audio").currentTime); window.MusicLyrics.refresh();}
    window.MusicPlayer.syncFollow();
    if (name === "follow") {
      const frame = $("#followFrame");
      inspectFollowFrame(frame, "select-pane");
      expandCompactScore(frame);
    }
  }
  async function share(song) {
    if (!song) return;
    const url = new URL(location.origin + "/"); url.searchParams.set("song", song.id);
    const status = $("#shareStatus");
    try {
      await navigator.clipboard.writeText(url.href);
      clearTimeout(shareTimer); status.classList.remove("share-fallback"); status.textContent = "链接已复制"; status.hidden = false;
      shareTimer = setTimeout(() => {status.hidden = true;}, 2000);
    } catch (_) {
      clearTimeout(shareTimer); status.classList.add("share-fallback");
      const message = document.createElement("span"); message.textContent = "请长按或右键复制链接";
      const link = document.createElement("a"); link.href = url.href; link.textContent = url.href;
      const close = document.createElement("button"); close.type = "button"; close.textContent = "关闭"; close.setAttribute("aria-label", "关闭分享提示"); close.onclick = () => {status.hidden = true;};
      status.replaceChildren(message, link, close); status.hidden = false;
    }
  }
  function init(state, refresh) {
    data = state; enrich();
    $("#includeVersions").onclick = () => {
      $("#includeVersions").setAttribute("aria-pressed", String(!showVersions()));
      if (data.currentAlbumId) refresh(data.currentAlbumId);
      else if ($("#q").value.trim()) search($("#q").value.trim());
      else refresh();
    };
    $("#playAlbum").onclick = () => { const list = albumSongs(data.currentAlbumId); if (list.length) window.MusicPlayer.play(list[0], list); };
    ["#playerTitle", "#playerArt", "#playerSub"].forEach((selector) => { $(selector).onclick = toggleNow; });
    syncNowToggles();
    $("#openQueue").onclick = () => openNow("queue"); $("#closeNow").onclick = closeNow;
    document.querySelectorAll("[data-now-tab]").forEach((b) => b.onclick = () => selectPane(b.dataset.nowTab));
    $("#shareSong").onclick = () => share(window.MusicPlayer.current());
    $("#songScoreLink").onclick = () => { const song = window.MusicPlayer.current(); if (!song?.scoreId) return; closeNow(); document.querySelector('[data-tab="scores"]').click(); document.querySelector(`[data-score-id="${CSS.escape(song.scoreId)}"]`)?.click(); };
    function dismissMenus(e) {
      document.querySelectorAll("#playerTools[open], .song-actions[open]").forEach((menu) => {if (!menu.contains(e.target)) menu.open = false;});
    }
    document.addEventListener("pointerdown", dismissMenus, true);
    $("#panelMusic").addEventListener("scroll", closeSongMenus, {passive: true});
    window.addEventListener("resize", closeSongMenus);
    window.addEventListener("blur", () => {if (document.activeElement === $("#followFrame")) dismissMenus({target: $("#followFrame")});});
    $("#followFrame").addEventListener("load", () => {try {$("#followFrame").contentDocument?.addEventListener("pointerdown", dismissMenus, true);} catch (_) {}});
    document.addEventListener("keydown", (e) => { if ($("#nowPlaying").hidden) return; if (e.key === "Escape") {if ($("#playerTools").open) $("#playerTools").open = false; else closeNow(); e.preventDefault();} if (e.key === "Tab") {const items = [...$("#nowPlaying").querySelectorAll("button,input,summary,iframe,[tabindex]")].filter((el) => el.getClientRects().length); const first = items[0], last = items.at(-1); if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); } else if (!e.shiftKey && document.activeElement === last) {first.focus(); e.preventDefault();} } });
    const shared = new URLSearchParams(location.search).get("song");
    if (shared) { const song = data.songs.find((s) => s.id === shared); if (song) {window.MusicPlayer.add(song); openNow();} }
  }
  window.MusicLibrary = {init, search, albumSongs, rowList, markPlaying, openNow, closeNow, selectPane, prefetchFollow, validateFollows, applyFollowAvailability, updateAudioPresentation, visible};
})();

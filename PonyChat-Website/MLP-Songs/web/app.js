/**
 * MLP Music 前端：专辑浏览、播放列表、乐谱 PDF.js 画布预览。
 * 与站点同源，API 前缀 /api。
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const state = {
    albums: [],
    songs: [],
    scores: [],
    albumFilter: "",
    tab: "music",
    queue: [],
    queueIndex: -1,
    currentAlbumId: null,
    /* 乐谱分页状态 */
    scorePdf: null,
    scorePage: 1,
    scoreTotal: 0,
    scoreTitle: "",
    scoreUrl: "",
  };

  /* ── DOM 引用 ── */
  const audio = $("#audio");
  const albumGrid = $("#albumGrid");
  const trackPanel = $("#trackPanel");
  const trackList = $("#trackList");
  const trackPanelTitle = $("#trackPanelTitle");
  const albumFilterEl = $("#albumFilter");
  const panelMusic = $("#panelMusic");
  const panelScores = $("#panelScores");
  const scoreList = $("#scoreList");
  const scoreCanvasWrap = $("#scoreCanvasWrap");
  const sidebarSectionMusic = $("#sidebarSectionMusic");
  const sidebarSectionScores = $("#sidebarSectionScores");
  const pdfHint = $("#pdfHint");
  const scoreNav = $("#scoreNav");
  const scorePageLabel = $("#scorePageLabel");
  const btnScorePrev = $("#btnScorePrev");
  const btnScoreNext = $("#btnScoreNext");
  const btnDownloadPage = $("#btnDownloadPage");
  const scoreLightbox = $("#scoreLightbox");
  const scoreLightboxBackdrop = $("#scoreLightboxBackdrop");
  const scoreLightboxStage = $("#scoreLightboxStage");
  const scoreLightboxCanvas = $("#scoreLightboxCanvas");
  const scoreLightboxPageLabel = $("#scoreLightboxPageLabel");
  const btnScoreLightboxClose = $("#btnScoreLightboxClose");
  const playerTitle = $("#playerTitle");
  const playerSub = $("#playerSub");
  const playerArt = $("#playerArt");
  const btnPlay = $("#btnPlay");
  const iconPlay = btnPlay && btnPlay.querySelector(".icon-play");
  const iconPause = btnPlay && btnPlay.querySelector(".icon-pause");

  function setPlayButtonPlaying(playing) {
    if (!btnPlay) return;
    if (iconPlay) iconPlay.classList.toggle("hidden", !!playing);
    if (iconPause) iconPause.classList.toggle("hidden", !playing);
    btnPlay.setAttribute("aria-label", playing ? "暂停" : "播放");
  }
  const btnPrev = $("#btnPrev");
  const btnNext = $("#btnNext");
  const seek = $("#seek");
  const vol = $("#vol");
  const timeLabel = $("#timeLabel");
  const timeCurrent = $("#timeCurrent");
  const timeTotal = $("#timeTotal");
  const downloadCurrent = $("#downloadCurrent");
  const qInput = $("#q");
  const btnMenu = $("#btnMenu");
  const btnSearchIcon = $("#btnSearchIcon");
  const sidebar = $("#sidebar");
  const sidebarOverlay = $("#sidebarOverlay");
  const topBar = $(".top");

  /* ── PDF.js 初始化 ── */
  const pdfjsLib = window["pdfjs-dist/build/pdf"];
  if (pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  }

  /* ── 工具函数 ── */
  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function debounce(fn, ms) {
    let t;
    return function () {
      clearTimeout(t);
      t = setTimeout(fn, ms);
    };
  }

  function fmtTime(s) {
    if (!isFinite(s) || s < 0) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  function isMobile() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  /* ── History API 状态管理 ── */
  // 初始化历史状态
  history.replaceState({ appView: "home" }, "");

  function pushNav(view, extra) {
    history.pushState(Object.assign({ appView: view }, extra || {}), "");
  }

  window.addEventListener("popstate", (e) => {
    const st = e.state || {};
    const view = st.appView;
    if (sidebar && sidebar.classList.contains("open")) {
      _closeSidebar();
      return;
    }
    /* 遮罩关闭侧边栏时会 history.back() 回到「专辑」历史位；此时曲目面板仍打开，
       不能按「退出专辑」处理，否则会跳到全部专辑网格。 */
    if (view === "album" && st.albumId) {
      if (!trackPanel.classList.contains("hidden") && state.currentAlbumId === st.albumId) {
        return;
      }
      openAlbum(st.albumId, { skipHistory: true });
      return;
    }
    if (trackPanel && !trackPanel.classList.contains("hidden")) {
      _closeAlbum();
      return;
    }
    // 没有可关闭的视图时，允许浏览器正常后退
    // （不干预，用户会离开页面）
  });

  /* ── 音乐侧边栏 ── */
  function _openSidebar() {
    sidebar.classList.add("open");
    sidebarOverlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }
  function _closeSidebar() {
    sidebar.classList.remove("open");
    sidebarOverlay.classList.remove("open");
    document.body.style.overflow = "";
  }
  function openSidebar() {
    _openSidebar();
    if (isMobile()) pushNav("sidebar");
  }
  function closeSidebar() {
    // 若是由 popstate 之外触发（如点击遮罩），回退历史
    if (sidebar.classList.contains("open")) {
      _closeSidebar();
      if (isMobile()) history.back();
    }
  }

  /* 汉堡菜单：统一打开/关闭侧边栏（内容随 Tab 在专辑筛选 / 乐谱列表间切换） */
  btnMenu.addEventListener("click", () => {
    sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
  });
  sidebarOverlay.addEventListener("click", closeSidebar);

  /** 按当前 Tab 显示侧边栏内「专辑筛选」或「乐谱列表」区块 */
  function updateSidebarSections() {
    if (!sidebarSectionMusic || !sidebarSectionScores) return;
    if (state.tab === "music") {
      sidebarSectionMusic.classList.remove("hidden");
      sidebarSectionScores.classList.add("hidden");
    } else {
      sidebarSectionMusic.classList.add("hidden");
      sidebarSectionScores.classList.remove("hidden");
    }
  }

  /* ── 搜索图标（手机） ── */
  if (btnSearchIcon) {
    btnSearchIcon.addEventListener("click", () => {
      topBar.classList.add("search-active");
      qInput.focus();
    });
  }
  qInput.addEventListener("blur", () => {
    if (!qInput.value.trim()) {
      topBar.classList.remove("search-active");
    }
  });

  /* ── API 接口 ── */
  async function api(path) {
    const r = await fetch(path, { credentials: "same-origin" });
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }

  function albumTitle(id) {
    const a = state.albums.find((x) => x.id === id);
    return a ? a.title : id;
  }

  /* ── 播放器 ── */
  function setPlayerArt(coverUrl) {
    playerArt.style.backgroundImage = coverUrl ? "url('" + coverUrl + "')" : "";
  }

  function markPlayingTrack(songId) {
    document.querySelectorAll(".track-list li").forEach((li) => {
      li.classList.toggle("playing", li.dataset.songId === songId);
    });
  }

  function markPlayingAlbum(albumId) {
    document.querySelectorAll(".album-card").forEach((card) => {
      card.classList.toggle("playing", card.dataset.id === albumId);
    });
  }

  function playSong(song) {
    if (!song || !song.src) return;
    audio.src = song.src;
    audio.volume = Number(vol.value) / 100;
    playerTitle.textContent = song.title || "—";
    playerSub.textContent = albumTitle(song.albumId);
    downloadCurrent.href = song.src;
    downloadCurrent.setAttribute("download", (song.title || "track") + ".mp3");
    const al = state.albums.find((a) => a.id === song.albumId);
    setPlayerArt(al && al.cover ? al.cover : null);
    audio.play().catch(() => {});
    setPlayButtonPlaying(true);
    markPlayingTrack(song.id);
    markPlayingAlbum(song.albumId);
  }

  function buildQueueFromAlbum(albumId) {
    state.queue = state.songs
      .filter((s) => s.albumId === albumId)
      .slice()
      .sort((a, b) => {
        const ta = a.track != null ? a.track : 999;
        const tb = b.track != null ? b.track : 999;
        return ta - tb || a.title.localeCompare(b.title);
      });
  }

  function playAt(i) {
    if (i < 0 || i >= state.queue.length) return;
    state.queueIndex = i;
    playSong(state.queue[i]);
  }

  /* ── 专辑网格 ── */
  function renderAlbumGrid() {
    const q = (qInput.value || "").trim().toLowerCase();
    albumGrid.innerHTML = "";
    const filterId = state.albumFilter;
    state.albums.forEach((al) => {
      if (filterId && al.id !== filterId) return;
      if (q) {
        const matchAlbum = (al.title || "").toLowerCase().includes(q);
        const hasSong = state.songs.some(
          (s) => s.albumId === al.id && (s.title || "").toLowerCase().includes(q)
        );
        if (!matchAlbum && !hasSong) return;
      }
      const card = document.createElement("div");
      card.className = "album-card" + (al.id.endsWith("-extras") ? " extras-card" : "");
      card.dataset.id = al.id;
      const cover = al.cover
        ? 'style="background-image:url(\'' + al.cover + '\')"'
        : "";
      card.innerHTML =
        '<div class="album-cover" ' + cover + "></div>" +
        '<div class="album-card-body">' +
        '<p class="album-card-title">' + escapeHtml(al.title) + "</p>" +
        '<p class="album-card-meta">' + (al.trackCount || 0) + " 首</p></div>";
      card.addEventListener("click", () => openAlbum(al.id));
      albumGrid.appendChild(card);
    });
  }

  /* ── 曲目列表 ── */
  function _closeAlbum() {
    trackPanel.classList.add("hidden");
    albumGrid.classList.remove("hidden");
    state.currentAlbumId = null;
  }
  function closeAlbum() {
    if (!trackPanel.classList.contains("hidden")) {
      _closeAlbum();
      history.back();
    }
  }

  function openAlbum(albumId, opts) {
    opts = opts || {};
    state.currentAlbumId = albumId;
    const al = state.albums.find((a) => a.id === albumId);
    trackPanelTitle.textContent = al ? al.title : albumId;
    trackPanel.classList.remove("hidden");
    albumGrid.classList.add("hidden");
    if (!opts.skipHistory) pushNav("album", { albumId });

    const q = (qInput.value || "").trim().toLowerCase();
    let list = state.songs.filter((s) => s.albumId === albumId);
    if (q) list = list.filter((s) => (s.title || "").toLowerCase().includes(q));
    list.sort((a, b) => {
      const ta = a.track != null ? a.track : 999;
      const tb = b.track != null ? b.track : 999;
      return ta - tb;
    });

    trackList.innerHTML = "";
    list.forEach((song, idx) => {
      const li = document.createElement("li");
      li.dataset.songId = song.id;
      /* 列表内严格递增序号（元数据 track 可能重复，如正式版与 Demo 同号） */
      const num = String(idx + 1);
      li.innerHTML =
        '<span class="track-num">' + escapeHtml(num) + "</span>" +
        '<span class="track-name">' + escapeHtml(song.title) + "</span>" +
        '<span class="track-actions">' +
        '<a href="' + encodeURI(song.src) + '" download>下载</a></span>';

      const doPlay = () => {
        buildQueueFromAlbum(albumId);
        const order = state.songs
          .filter((s) => s.albumId === albumId)
          .slice()
          .sort((a, b) => {
            const ta = a.track != null ? a.track : 999;
            const tb = b.track != null ? b.track : 999;
            return ta - tb;
          });
        const ix = order.findIndex((s) => s.id === song.id);
        state.queue = order;
        playAt(ix >= 0 ? ix : 0);
        _closeSidebar();
      };

      li.addEventListener("click", (e) => {
        /* 下载链接触发下载，不播放；其余区域（曲名、序号、行空白）均播放 */
        if (e.target.closest("a[download]")) return;
        doPlay();
      });
      li.querySelector("a").addEventListener("click", (e) => e.stopPropagation());
      trackList.appendChild(li);
    });

    if (state.queue.length > 0 && state.queueIndex >= 0) {
      const cur = state.queue[state.queueIndex];
      if (cur) markPlayingTrack(cur.id);
    }
  }

  /* ── 侧边栏筛选 ── */
  function renderSidebar() {
    albumFilterEl.innerHTML = "";
    const all = document.createElement("li");
    all.innerHTML = '<button type="button" data-id="">全部专辑</button>';
    all.querySelector("button").addEventListener("click", () => {
      state.albumFilter = "";
      $$(".album-filter button").forEach((b) => b.classList.remove("active"));
      all.querySelector("button").classList.add("active");
      renderAlbumGrid();
      _closeSidebar();
    });
    all.querySelector("button").classList.add("active");
    albumFilterEl.appendChild(all);

    state.albums.forEach((al) => {
      const isExtras = al.id.endsWith("-extras");
      const li = document.createElement("li");
      if (isExtras) li.classList.add("extras-item");
      li.innerHTML =
        '<button type="button" data-id="' + escapeHtml(al.id) + '">' +
        escapeHtml(al.title) +
        '<span class="badge">' + (al.trackCount || 0) + "</span></button>";
      li.querySelector("button").addEventListener("click", () => {
        state.albumFilter = al.id;
        $$(".album-filter button").forEach((b) => b.classList.remove("active"));
        li.querySelector("button").classList.add("active");
        renderAlbumGrid();
        _closeSidebar();
      });
      albumFilterEl.appendChild(li);
    });
  }

  /* ── 乐谱 PDF.js 渲染 ── */

  function getLightboxMaxLongEdge() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    return Math.min(4096, Math.round(Math.max(w, h) * dpr));
  }

  async function renderPdfPageToCanvas(canvas, pageNum, maxLongEdge) {
    const page = await state.scorePdf.getPage(pageNum);
    const baseVp = page.getViewport({ scale: 1 });
    const longEdge = Math.max(baseVp.width, baseVp.height);
    const scale = maxLongEdge / longEdge;
    const vp = page.getViewport({ scale });
    canvas.width = Math.round(vp.width);
    canvas.height = Math.round(vp.height);
    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport: vp,
    }).promise;
  }

  function updateScoreNavOnly() {
    if (scorePageLabel)
      scorePageLabel.textContent = state.scorePage + " / " + state.scoreTotal;
    if (btnScorePrev) btnScorePrev.disabled = state.scorePage <= 1;
    if (btnScoreNext) btnScoreNext.disabled = state.scorePage >= state.scoreTotal;
    if (scoreLightboxPageLabel)
      scoreLightboxPageLabel.textContent = state.scorePage + " / " + state.scoreTotal;
  }

  function isScoreLightboxOpen() {
    return scoreLightbox && !scoreLightbox.classList.contains("hidden");
  }

  /** 打开全屏前保存焦点，关闭时先移出再 aria-hidden，避免与无障碍规则冲突 */
  let scoreLightboxReturnFocus = null;

  /* 主区域单页（长边 4096px） */
  async function renderScorePage() {
    if (!state.scorePdf || !scoreCanvasWrap) return;
    scoreCanvasWrap.innerHTML = '<p class="pdf-hint">渲染中…</p>';

    try {
      const canvas = document.createElement("canvas");
      await renderPdfPageToCanvas(canvas, state.scorePage, 4096);

      scoreCanvasWrap.innerHTML = "";
      scoreCanvasWrap.appendChild(canvas);
      canvas.title = "点击查看全屏预览";
      canvas.addEventListener("click", () => {
        if (!state.scorePdf) return;
        openScoreLightbox();
      });

      updateScoreNavOnly();
      if (scoreNav) scoreNav.classList.remove("hidden");

      btnDownloadPage.onclick = () => {
        canvas.toBlob((blob) => {
          const blobUrl = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = blobUrl;
          a.download =
            (state.scoreTitle || "score") +
            (state.scoreTotal > 1 ? "_p" + state.scorePage : "") +
            ".png";
          a.click();
          URL.revokeObjectURL(blobUrl);
        }, "image/png");
      };
    } catch (err) {
      scoreCanvasWrap.innerHTML = '<p class="pdf-hint">渲染失败，请重试。</p>';
      console.error("PDF render error:", err);
    }
  }

  /* 全屏层：按屏幕清晰度渲染，与主区域分页同步 */
  async function renderLightboxPage() {
    if (!state.scorePdf || !scoreLightboxCanvas) return;
    try {
      scoreLightboxCanvas.style.opacity = "0.85";
      await renderPdfPageToCanvas(
        scoreLightboxCanvas,
        state.scorePage,
        getLightboxMaxLongEdge()
      );
    } catch (err) {
      console.error("Lightbox render error:", err);
    } finally {
      scoreLightboxCanvas.style.opacity = "1";
    }
    updateScoreNavOnly();
  }

  function openScoreLightbox() {
    if (!state.scorePdf || !scoreLightbox) return;
    scoreLightboxReturnFocus = document.activeElement;
    scoreLightbox.classList.remove("hidden");
    scoreLightbox.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    renderLightboxPage();
    if (btnScoreLightboxClose) {
      requestAnimationFrame(() => {
        try {
          btnScoreLightboxClose.focus();
        } catch (_) {}
      });
    }
  }

  function closeScoreLightbox() {
    if (!scoreLightbox) return;
    const returnEl = scoreLightboxReturnFocus;
    scoreLightboxReturnFocus = null;
    const active = document.activeElement;
    if (active && scoreLightbox.contains(active)) {
      if (
        returnEl &&
        typeof returnEl.focus === "function" &&
        document.body.contains(returnEl) &&
        !scoreLightbox.contains(returnEl)
      ) {
        try {
          returnEl.focus({ preventScroll: true });
        } catch (_) {}
      } else if (btnMenu && typeof btnMenu.focus === "function") {
        try {
          btnMenu.focus({ preventScroll: true });
        } catch (_) {}
      } else {
        try {
          active.blur();
        } catch (_) {}
      }
    }
    scoreLightbox.classList.add("hidden");
    scoreLightbox.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    renderScorePage().catch((e) => console.error(e));
  }

  /* 全屏内左右滑动翻页 */
  (function attachLightboxSwipe() {
    if (!scoreLightboxStage) return;
    let startX = 0;
    let startY = 0;
    let active = false;

    scoreLightboxStage.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      active = true;
      startX = e.clientX;
      startY = e.clientY;
      try {
        scoreLightboxStage.setPointerCapture(e.pointerId);
      } catch (_) {}
    });

    scoreLightboxStage.addEventListener("pointerup", async (e) => {
      if (!active) return;
      active = false;
      try {
        if (scoreLightboxStage.hasPointerCapture(e.pointerId))
          scoreLightboxStage.releasePointerCapture(e.pointerId);
      } catch (_) {}

      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.abs(dx) < 48) return;
      if (Math.abs(dx) < Math.abs(dy) * 1.15) return;

      if (dx < 0 && state.scorePage < state.scoreTotal) {
        state.scorePage++;
        await renderLightboxPage();
        return;
      }
      if (dx > 0 && state.scorePage > 1) {
        state.scorePage--;
        await renderLightboxPage();
      }
    });

    scoreLightboxStage.addEventListener("pointercancel", () => {
      active = false;
    });
  })();

  if (btnScoreLightboxClose) {
    btnScoreLightboxClose.addEventListener("click", closeScoreLightbox);
  }
  if (scoreLightboxBackdrop) {
    scoreLightboxBackdrop.addEventListener("click", closeScoreLightbox);
  }

  document.addEventListener("keydown", (e) => {
    if (!isScoreLightboxOpen()) return;
    if (e.code === "Escape") {
      e.preventDefault();
      closeScoreLightbox();
      return;
    }
    if (e.code === "ArrowLeft" && state.scorePage > 1) {
      e.preventDefault();
      state.scorePage--;
      renderLightboxPage();
    }
    if (e.code === "ArrowRight" && state.scorePage < state.scoreTotal) {
      e.preventDefault();
      state.scorePage++;
      renderLightboxPage();
    }
  });

  window.addEventListener(
    "resize",
    debounce(() => {
      if (isScoreLightboxOpen()) renderLightboxPage();
    }, 250)
  );

  /* 加载乐谱并渲染第一页 */
  async function loadScore(url, title) {
    if (!scoreCanvasWrap) return;
    scoreCanvasWrap.innerHTML = '<p class="pdf-hint">加载中…</p>';
    if (scoreNav) scoreNav.classList.add("hidden");

    if (!pdfjsLib) {
      scoreCanvasWrap.innerHTML = '<p class="pdf-hint">PDF 渲染库未加载，请刷新页面。</p>';
      return;
    }

    try {
      const pdf = await pdfjsLib.getDocument(url).promise;
      state.scorePdf = pdf;
      state.scorePage = 1;
      state.scoreTotal = pdf.numPages;
      state.scoreTitle = title || "score";
      state.scoreUrl = url;
      await renderScorePage();
    } catch (err) {
      scoreCanvasWrap.innerHTML = '<p class="pdf-hint">加载失败，请重试。</p>';
      console.error("PDF load error:", err);
    }
  }

  /* 翻页按钮（全屏打开时同步全屏画布） */
  if (btnScorePrev) {
    btnScorePrev.addEventListener("click", async () => {
      if (state.scorePage > 1) {
        state.scorePage--;
        await renderScorePage();
        scoreCanvasWrap.scrollTop = 0;
        if (isScoreLightboxOpen()) await renderLightboxPage();
      }
    });
  }
  if (btnScoreNext) {
    btnScoreNext.addEventListener("click", async () => {
      if (state.scorePage < state.scoreTotal) {
        state.scorePage++;
        await renderScorePage();
        scoreCanvasWrap.scrollTop = 0;
        if (isScoreLightboxOpen()) await renderLightboxPage();
      }
    });
  }

  /* ── 乐谱列表渲染 ── */
  function renderScores() {
    const q = (qInput.value || "").trim().toLowerCase();
    scoreList.innerHTML = "";
    state.scores.forEach((sc) => {
      if (
        q &&
        !(sc.title || "").toLowerCase().includes(q) &&
        !(sc.id || "").toLowerCase().includes(q)
      )
        return;
      const li = document.createElement("li");
      li.dataset.src = sc.src;

      /* 标题（可折行，flex: 1） */
      const titleSpan = document.createElement("span");
      titleSpan.className = "score-item-title";
      titleSpan.textContent = sc.title || sc.id;
      li.appendChild(titleSpan);

      /* 下载整个 PDF 按钮 */
      const dlBtn = document.createElement("a");
      dlBtn.className = "btn-score-pdf-dl";
      dlBtn.href = sc.src;
      dlBtn.download = (sc.title || sc.id) + ".pdf";
      dlBtn.title = "下载 PDF";
      dlBtn.textContent = "↓";
      dlBtn.addEventListener("click", (e) => e.stopPropagation());
      li.appendChild(dlBtn);

      li.addEventListener("click", () => {
        $$(".score-list li").forEach((x) => x.classList.remove("active"));
        li.classList.add("active");
        // 手机端关闭抽屉再显示画布
        if (isMobile()) _closeSidebar();
        loadScore(sc.src, sc.title || sc.id);
      });
      scoreList.appendChild(li);
    });
  }

  /* ── 标签切换 ── */
  function setTab(name) {
    _closeSidebar();
    state.tab = name;
    updateSidebarSections();
    $$(".tab").forEach((t) => {
      const on = t.dataset.tab === name;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    panelMusic.classList.toggle("active", name === "music");
    panelScores.classList.toggle("active", name === "scores");
  }

  /* ── 数据加载 ── */
  async function load() {
    const [a, s, sc] = await Promise.all([
      api("/api/albums"),
      api("/api/songs"),
      api("/api/scores"),
    ]);
    state.albums = a.albums || [];
    state.songs = s.songs || [];
    state.scores = sc.scores || [];
    renderSidebar();
    renderAlbumGrid();
    renderScores();
    updateSidebarSections();
  }

  /* ── 播放器事件 ── */
  btnPlay.addEventListener("click", () => {
    if (!audio.src) return;
    if (audio.paused) {
      audio.play();
      setPlayButtonPlaying(true);
    } else {
      audio.pause();
      setPlayButtonPlaying(false);
    }
  });

  btnPrev.addEventListener("click", () => {
    if (state.queueIndex > 0) playAt(state.queueIndex - 1);
  });

  btnNext.addEventListener("click", () => {
    if (state.queueIndex < state.queue.length - 1) playAt(state.queueIndex + 1);
  });

  audio.addEventListener("play", () => setPlayButtonPlaying(true));
  audio.addEventListener("pause", () => setPlayButtonPlaying(false));
  audio.addEventListener("ended", () => {
    if (state.queueIndex < state.queue.length - 1) playAt(state.queueIndex + 1);
  });

  audio.addEventListener("timeupdate", () => {
    const d = audio.duration;
    const t = audio.currentTime;
    if (isFinite(d) && d > 0) {
      const pct = (t / d) * 100;
      seek.value = String(Math.floor(pct * 10));
      seek.style.setProperty("--fill", pct.toFixed(1) + "%");
    }
    const cur = fmtTime(t);
    const tot = fmtTime(d || 0);
    timeLabel.textContent = cur + " / " + tot;
    if (timeCurrent) timeCurrent.textContent = cur;
    if (timeTotal) timeTotal.textContent = tot;
  });

  seek.addEventListener("input", () => {
    const d = audio.duration;
    if (!isFinite(d) || d <= 0) return;
    const pct = Number(seek.value) / 10;
    audio.currentTime = (pct / 100) * d;
    seek.style.setProperty("--fill", pct.toFixed(1) + "%");
    const t = audio.currentTime;
    const cur = fmtTime(t);
    const tot = fmtTime(d);
    timeLabel.textContent = cur + " / " + tot;
    if (timeCurrent) timeCurrent.textContent = cur;
    if (timeTotal) timeTotal.textContent = tot;
  });

  vol.addEventListener("input", () => {
    audio.volume = Number(vol.value) / 100;
    vol.style.setProperty("--fill", vol.value + "%");
  });
  vol.style.setProperty("--fill", vol.value + "%");

  /* ── 搜索 ── */
  qInput.addEventListener(
    "input",
    debounce(() => {
      renderAlbumGrid();
      if (state.tab === "scores") renderScores();
      if (state.currentAlbumId && !trackPanel.classList.contains("hidden"))
        openAlbum(state.currentAlbumId);
    }, 200)
  );

  /* ── Tab 切换 ── */
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
  });

  /* ── 返回专辑按钮 ── */
  $("#backAlbum").addEventListener("click", closeAlbum);

  /* ── 键盘快捷键 ── */
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space") return;
    if (isScoreLightboxOpen()) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON") return;
    e.preventDefault();
    if (!audio.src) return;
    if (audio.paused) { audio.play(); } else { audio.pause(); }
  });

  /* ── 启动 ── */
  load().catch((e) => {
    console.error(e);
    playerSub.textContent = "无法加载数据，请确认已运行 generate_index 且后端可用。";
  });
})();

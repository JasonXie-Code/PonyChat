/**
 * MLP Music 前端：专辑浏览、播放列表、乐谱 PDF.js 画布预览。
 * 与站点同源，API 前缀 /api。
 */
(function () {
  "use strict";
  document.documentElement.dataset.appLoadStartMs = performance.now().toFixed(2);

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const state = {
    albums: [],
    songs: [],
    scores: [],
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
  const albumCategories = [...$$("#collectionChips button")].map((button) => ({
    button,
    section: document.getElementById(button.getAttribute("aria-controls")),
  }));
  let selectedAlbumCategory = albumGrid;
  let albumGridScrollTop = 0;
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

  /* ── PDF.js 按需加载 ── */
  let pdfjsLib = window["pdfjs-dist/build/pdf"], pdfjsPromise = null;
  function loadPdfLibrary() {
    const configure = (library) => {
      library.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs-3.11.174/pdf.worker.min.js";
      return library;
    };
    if (pdfjsLib) return Promise.resolve(configure(pdfjsLib));
    if (!pdfjsPromise) {
      pdfjsPromise = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "/vendor/pdfjs-3.11.174/pdf.min.js";
        script.async = true;
        script.onload = () => {
          pdfjsLib = window["pdfjs-dist/build/pdf"];
          if (pdfjsLib) resolve(configure(pdfjsLib));
          else {script.remove(); reject(new Error("PDF library unavailable"));}
        };
        script.onerror = () => {script.remove(); reject(new Error("PDF library failed to load"));};
        document.head.append(script);
      }).catch((error) => {pdfjsPromise = null; throw error;});
    }
    return pdfjsPromise;
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
    if (isMobile()) pushNav("sidebar", { albumDepth: (history.state?.albumDepth || 0) + 1 });
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
    if (path === "/api/library" && window.MusicLibraryBootstrap) return window.MusicLibraryBootstrap.load();
    const r = await fetch(path, { credentials: "same-origin" });
    if (!r.ok) {
      const error = new Error(path + " " + r.status);
      const retrySeconds = Number(r.headers.get("Retry-After") || 3);
      error.status = r.status;
      error.warming = r.headers.get("X-Music-Warming") === "readers";
      error.retryAfterMs = Math.max(1000, Math.min(30000, (Number.isFinite(retrySeconds) ? retrySeconds : 3) * 1000));
      throw error;
    }
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

  function playSong(song) { window.MusicPlayer.play(song); }

  /* ── 专辑网格 ── */
  function albumGroup(album) {
    if (album.id.startsWith("equestria-girls")) return "equestriaGirls";
    if (album.id.startsWith("soundtracks-pony-town-")) return "ponyTown";
    if (album.id === "4everfreebrony-the-highest-tower") return "highestTower";
    if (album.id === "shadyvox-dont-mine-at-night") return "shadyVox";
    if (album.id === "david-larsen-double-rainboom") return "doubleRainboom";
    return "main";
  }

  function renderAlbumCategory() {
    if (!selectedAlbumCategory.querySelector(".album-card")) selectedAlbumCategory = albumGrid;
    const filtered = selectedAlbumCategory !== albumGrid;
    albumGrid.classList.toggle("category-filtered", filtered);
    for (const {button, section} of albumCategories) {
      const selected = section === selectedAlbumCategory;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
      if (selected) $("#libraryHeading").textContent = button.textContent;
      if (section === albumGrid) continue;
      button.hidden = !section.querySelector(".album-card");
      section.hidden = button.hidden || (filtered && !selected);
    }
    $("#collectionChips").hidden = false;
  }

  for (const {button, section} of albumCategories) {
    button.addEventListener("click", () => {
      selectedAlbumCategory = section;
      renderAlbumCategory();
      panelMusic.scrollTop = 0;
    });
  }

  function renderAlbumGrid() {
    const q = (qInput.value || "").trim().toLowerCase();
    if (q) { window.MusicLibrary.search(q); return; }
    $("#includeVersions").hidden = true;
    $("#panelMusic").classList.remove("search-mode", "album-open");
    $("#searchResults").classList.add("hidden");
    albumGrid.classList.remove("hidden");
    const cards = {
      main: $("#mainAlbumCards"),
      equestriaGirls: $("#equestriaGirlsAlbumCards"),
      ponyTown: $("#ponyTownAlbumCards"),
      highestTower: $("#highestTowerAlbumCards"),
      shadyVox: $("#shadyVoxAlbumCards"),
      doubleRainboom: $("#doubleRainboomAlbumCards"),
    };
    Object.values(cards).forEach((list) => list.replaceChildren());
    state.albums.forEach((al) => {
      const trackCount = window.MusicLibrary.albumSongs(al.id).length;
      if (!trackCount) return;
      const card = document.createElement("button");
      card.type = "button";
      card.setAttribute("aria-label", "打开专辑 " + al.title);
      card.className = "album-card" + (al.id.endsWith("-extras") ? " extras-card" : "");
      card.dataset.id = al.id;
      const cover = al.cover
        ? 'style="background-image:url(\'' + al.cover + '\')"'
        : "";
      card.innerHTML =
        '<div class="album-cover" ' + cover + "></div>" +
        '<div class="album-card-body">' +
        '<p class="album-card-title">' + escapeHtml(al.title) + "</p>" +
        '<p class="album-card-meta">' + trackCount + " 首</p></div>";
      card.addEventListener("click", () => openAlbum(al.id));
      cards[albumGroup(al)].appendChild(card);
    });
    renderAlbumCategory();
  }

  /* ── 曲目列表 ── */
  function _closeAlbum() {
    trackPanel.classList.add("hidden");
    $("#panelMusic").classList.remove("album-open");
    albumGrid.classList.remove("hidden");
    state.currentAlbumId = null;
    $("#discovery").classList.remove("hidden");
    renderAlbumGrid();
    selectSidebarAlbum("");
    panelMusic.scrollTop = albumGridScrollTop;
  }
  function closeAlbum() {
    if (!trackPanel.classList.contains("hidden")) {
      const albumDepth = history.state?.albumDepth || 1;
      _closeAlbum();
      history.go(-albumDepth);
    }
  }

  function openAlbum(albumId, opts) {
    opts = opts || {};
    const opening = state.currentAlbumId !== albumId;
    if (opening && !albumGrid.classList.contains("hidden")) albumGridScrollTop = panelMusic.scrollTop;
    state.currentAlbumId = albumId;
    $("#includeVersions").hidden = false;
    const al = state.albums.find((a) => a.id === albumId);
    trackPanelTitle.textContent = al ? al.title : albumId;
    const release = $("#albumRelease");
    const releaseDate = al?.releaseDate || "";
    const releaseTime = release.querySelector("time");
    releaseTime.dateTime = releaseTime.textContent = releaseDate;
    release.hidden = !releaseDate;
    const description = $("#albumDescription");
    description.textContent = al?.description || "";
    description.hidden = !description.textContent;
    trackPanel.classList.remove("hidden");
    albumGrid.classList.add("hidden");
    $("#searchResults").classList.add("hidden");
    $("#discovery").classList.remove("hidden");
    $("#panelMusic").classList.add("album-open");
    if (!opts.skipHistory) {
      const view = history.state?.appView;
      const albumDepth = history.state?.albumDepth || 0;
      if (view === "album" || view === "sidebar") {
        history.replaceState({ appView: "album", albumId, albumDepth: albumDepth || 1 }, "");
      } else {
        pushNav("album", { albumId, albumDepth: 1 });
      }
    }
    window.MusicLibrary.rowList(trackList, window.MusicLibrary.albumSongs(albumId));
    if (opening) panelMusic.scrollTop = 0;
    selectSidebarAlbum(albumId);
    _closeSidebar();
  }

  /* ── 侧边栏筛选 ── */
  function selectSidebarAlbum(albumId) {
    $$(".album-filter button[data-id]").forEach((button) => {
      button.classList.toggle("active", button.dataset.id === albumId);
    });
  }
  function renderSidebar() {
    const filters = {
      main: albumFilterEl,
      equestriaGirls: $("#equestriaGirlsAlbumFilter"),
      ponyTown: $("#ponyTownAlbumFilter"),
      highestTower: $("#highestTowerAlbumFilter"),
      shadyVox: $("#shadyVoxAlbumFilter"),
      doubleRainboom: $("#doubleRainboomAlbumFilter"),
    };
    Object.values(filters).forEach((list) => list.replaceChildren());
    const allAlbums = $("#allAlbumFilter");
    allAlbums.replaceChildren();
    const all = document.createElement("li");
    all.innerHTML = '<button type="button" data-id="">全部专辑</button>';
    all.querySelector("button").addEventListener("click", () => {
      selectedAlbumCategory = albumGrid;
      albumGridScrollTop = 0;
      qInput.value = "";
      if (!trackPanel.classList.contains("hidden")) {
        closeAlbum();
        _closeSidebar();
        return;
      }
      _closeAlbum();
      closeSidebar();
    });
    all.querySelector("button").classList.add("active");
    allAlbums.appendChild(all);

    state.albums.forEach((al) => {
      const isExtras = al.id.endsWith("-extras");
      const li = document.createElement("li");
      if (isExtras) li.classList.add("extras-item");
      li.innerHTML =
        '<button type="button" data-id="' + escapeHtml(al.id) + '">' +
        escapeHtml(al.title) +
        '<span class="badge">' + (al.trackCount || 0) + "</span></button>";
      li.querySelector("button").addEventListener("click", () => {
        qInput.value = "";
        openAlbum(al.id);
      });
      filters[albumGroup(al)].appendChild(li);
    });
    $("#mainSidebar").hidden = !filters.main.childElementCount;
    $("#equestriaGirlsSidebar").hidden = !filters.equestriaGirls.childElementCount;
    $("#ponyTownSidebar").hidden = !filters.ponyTown.childElementCount;
    $("#highestTowerSidebar").hidden = !filters.highestTower.childElementCount;
    $("#shadyVoxSidebar").hidden = !filters.shadyVox.childElementCount;
    $("#doubleRainboomSidebar").hidden = !filters.doubleRainboom.childElementCount;
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
      canvas.dataset.page = String(state.scorePage);
      canvas.title = "点击查看全屏预览";
      canvas.addEventListener("click", () => {
        if (!state.scorePdf) return;
        openScoreLightbox(canvas);
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

  function openScoreLightbox(source = document.activeElement) {
    if (!state.scorePdf || !scoreLightbox) return;
    scoreLightboxReturnFocus = source;
    scoreLightbox.classList.remove("hidden");
    scoreLightbox.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    renderLightboxPage();
    if (btnScoreLightboxClose) {
      requestAnimationFrame(() => {
        if (!isScoreLightboxOpen()) return;
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
    const restoreCanvasFocus = () => {
      if (returnEl?.matches(".score-canvas-wrap canvas")) {
        const nextCanvas = scoreCanvasWrap.querySelector("canvas");
        if (nextCanvas) {nextCanvas.tabIndex = 0; nextCanvas.focus({preventScroll:true});}
      }
    };
    const currentCanvas = scoreCanvasWrap.querySelector("canvas");
    if (currentCanvas?.dataset.page === String(state.scorePage)) restoreCanvasFocus();
    else renderScorePage().then(restoreCanvasFocus).catch((e) => console.error(e));
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
    if (e.code === "Tab") {e.preventDefault(); btnScoreLightboxClose?.focus(); return;}
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

    try {
      const library = await loadPdfLibrary();
      const pdf = await library.getDocument(url).promise;
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

  window.MusicScores = {open: async (url,title) => {
    if (typeof url !== "string" || !/^\/(?:follow-media\/)?scores\//.test(url)) return;
    window.MusicLibrary?.closeNow(); qInput.value = ""; window.MusicControls?.refresh();
    setTab("scores"); document.querySelector('[data-tab="scores"]')?.focus(); await loadScore(url,title);
  }};

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
      li.dataset.scoreId = sc.id;

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
    if (name === "scores") renderScores();
  }

  /* ── 数据加载 ── */
  async function loadSongLyrics(song) {
    const instrumental = song && song.lyricsStatus !== "available" &&
      (song.instrumental === true || song.versionKind === "instrumental" || song.lyricsStatus === "instrumental");
    const load = window.MusicLyrics.load(instrumental ? null : song);
    const notice = $("#lyricsNotice");
    if (!instrumental) await load;
    if (instrumental || notice.textContent === "纯音乐版本，没有人声歌词") {
      notice.textContent = $("#lyricsEmpty").textContent = "纯音乐，请欣赏";
    }
  }

  async function load() {
    const catalog = await api("/api/library");
    const timing = document.documentElement.dataset;
    timing.libraryRenderStartMs = performance.now().toFixed(2);
    state.albums = catalog.albums || [];
    state.songs = catalog.songs || [];
    // Base metadata cannot grant a follow entry, even if an older server sends it.
    state.songs.forEach((song) => {delete song.followId; delete song.followViewPath;});
    window.MusicFollowBadges?.setSongs(state.songs);
    state.scores = catalog.scores || [];
    window.MusicPlayer.setCallbacks({
      onSong: (song) => {
        loadSongLyrics(song);
        window.MusicLibrary.markPlaying(song?.id);
        window.MusicLibrary.selectPane("lyrics");
        window.MusicLibrary.prefetchFollow(song);
        window.MusicLibrary.updateAudioPresentation(song);
      },
      onTime: window.MusicLyrics.update
    });
    window.MusicLibrary.init(state, (id) => id ? openAlbum(id, {skipHistory: true}) : renderAlbumGrid());
    timing.libraryInitDoneMs = performance.now().toFixed(2);
    renderSidebar();
    timing.librarySidebarDoneMs = performance.now().toFixed(2);
    renderAlbumGrid();
    timing.libraryAlbumsDoneMs = performance.now().toFixed(2);
    if (state.tab === "scores") renderScores();
    timing.libraryScoresDoneMs = performance.now().toFixed(2);
    updateSidebarSections();
    document.documentElement.dataset.libraryReadyMs = performance.now().toFixed(2);
    document.documentElement.dataset.libraryReady = "true";
    void window.MusicLibrary.validateFollows(state.songs, api);
  }

  /* ── 播放器事件 ── */
  audio.addEventListener("play", () => setPlayButtonPlaying(true));
  audio.addEventListener("pause", () => setPlayButtonPlaying(false));
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
    vol.style.setProperty("--fill", vol.value + "%");
  });
  vol.style.setProperty("--fill", vol.value + "%");

  /* ── 搜索 ── */
  qInput.addEventListener(
    "input",
    debounce(() => {
      if (state.tab === "scores") renderScores();
      else { state.currentAlbumId = null; trackPanel.classList.add("hidden"); $("#discovery").classList.remove("hidden"); renderAlbumGrid(); }
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
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "SUMMARY") return;
    e.preventDefault();
    if (!audio.src) return;
    window.MusicPlayer.toggle();
  });

  /* ── 启动 ── */
  load().then(() => {
    const params = new URLSearchParams(location.search), score = params.get("score");
    if (score) window.MusicScores.open(score,params.get("title") || "原谱");
  }).catch((e) => {
    console.error(e);
    playerSub.textContent = "歌曲暂时加载失败，请刷新重试。";
  });
})();

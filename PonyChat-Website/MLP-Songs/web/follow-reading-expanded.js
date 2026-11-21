/* Extra reading space without reloading the score or changing playback. */
(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const panel = $("#nowPlaying"), pane = $("#followPane"), frame = $("#followFrame");
  const enter = $("#expandFollow"), toolbar = $("#expandedFollowTools");
  if (!panel || !pane || !frame || !enter || !toolbar) return;
  const exit = $("#exitExpandedFollow"), play = $("#expandedFollowPlay");
  const title = $("#expandedFollowTitle"), audio = $("#audio");
  let expanded = false, previousFocus = null;
  function available() {
    const song = window.MusicPlayer?.current();
    const src = frame.getAttribute("src");
    if (panel.hidden || pane.hidden || !song || !src) return false;
    if (song.followId) return true;
    if (frame.dataset.readerReady !== "true") return false;
    const route = new URL(src, location.href);
    return route.origin === location.origin && route.pathname === "/follow/unified/index.html" &&
      route.searchParams.get("preview") === "1" && /^[a-z0-9-]+$/.test(route.searchParams.get("song") || "");
  }
  function update() {
    const ready = available();
    if (expanded && !ready) leave(false);
    enter.hidden = !ready || expanded;
    const song = window.MusicPlayer?.current();
    title.textContent = song?.title || "跟谱";
    play.textContent = audio.paused ? "播放" : "暂停";
    play.setAttribute("aria-label", audio.paused ? "播放音乐" : "暂停音乐");
  }
  function leave(restoreFocus = true) {
    if (!expanded) return;
    expanded = false;
    panel.classList.remove("follow-reading-expanded");
    toolbar.hidden = true;
    enter.setAttribute("aria-expanded", "false");
    update();
    if (restoreFocus && previousFocus?.isConnected) previousFocus.focus();
  }
  function escape(event) {
    if (!expanded || event.key !== "Escape") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    leave();
  }
  enter.addEventListener("click", () => {
    if (!available()) return;
    previousFocus = document.activeElement;
    expanded = true;
    panel.classList.add("follow-reading-expanded");
    toolbar.hidden = false;
    enter.setAttribute("aria-expanded", "true");
    update();
    exit.focus();
  });
  exit.addEventListener("click", () => leave());
  play.addEventListener("click", () => window.MusicPlayer.toggle());
  document.addEventListener("keydown", escape, true);
  frame.addEventListener("load", () => {
    // This owned iframe uses the site's origin; no external message bridge.
    try { frame.contentDocument?.addEventListener("keydown", escape, true); } catch (_) {}
    update();
  });
  for (const event of ["play", "pause", "ended", "loadedmetadata", "emptied"]) {
    audio.addEventListener(event, update);
  }
  const observer = new MutationObserver(update);
  observer.observe(panel, {attributes: true, attributeFilter: ["hidden", "class"]});
  observer.observe(pane, {attributes: true, attributeFilter: ["hidden"]});
  observer.observe(frame, {attributes: true, attributeFilter: ["src", "data-reader-ready"]});
  update();
})();

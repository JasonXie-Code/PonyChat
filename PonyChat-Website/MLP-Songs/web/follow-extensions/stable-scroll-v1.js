/* One viewport owner for the frozen reader and its source-system fit addons. */
(function (root) {
  "use strict";
  function targetFor(row, viewport, scrollTop, scrollHeight, height) {
    const margin = 8;
    if (row.top >= viewport.top + margin && row.bottom <= viewport.top + height - margin) return scrollTop;
    const gap = row.height <= height - 2 * margin ? (height - row.height) / 2 : margin;
    return Math.max(0, Math.min(Math.max(0, scrollHeight - height), scrollTop + row.top - viewport.top - gap));
  }
  function install(win) {
    const doc = win.document, wrap = doc.getElementById("scoreWrap");
    const resume = doc.getElementById("resumeFollow"), status = doc.getElementById("stageStatus");
    if (!wrap || !resume || !status || wrap.dataset.stableScroll === "enabled") return null;
    // Scope the adapter to this reader element. The signed music/controller
    // bytes stay exact; other scroll containers retain native behavior.
    let prototype = Object.getPrototypeOf(wrap), descriptor;
    while (prototype && !descriptor) {
      descriptor = Object.getOwnPropertyDescriptor(prototype, "scrollTop");
      prototype = Object.getPrototypeOf(prototype);
    }
    if (!descriptor?.get || !descriptor?.set || Object.hasOwn(wrap, "scrollTop")) return null;
    const read = () => descriptor.get.call(wrap), write = value => descriptor.set.call(wrap, value);
    let frame = 0, alive = true, parentVisible = true, previous = null, revision;
    const following = () => alive && parentVisible && !doc.hidden && wrap.clientHeight > 0 &&
      resume.hidden === true && status.textContent.startsWith("自动跟随");
    function anchor() {
      if (wrap.dataset.mode === "jianpu") return wrap.querySelector(".jp-row-active");
      const line = wrap.querySelector(".auto-page.has-current > .unified-score-cursor");
      return line && win.getComputedStyle(line).display !== "none" ? line : null;
    }
    function flush() {
      frame = 0;
      if (!following()) { previous = null; return; }
      const node = anchor();
      // Rests/gaps may temporarily hide the line between two notes of the same
      // system. Retain its viewport anchor instead of reviving per-note scroll.
      if (!node) return;
      const row = node.getBoundingClientRect(), bounds = wrap.getBoundingClientRect();
      const viewport = {top: bounds.top + wrap.clientTop};
      if (!row.height || ![row.top, row.bottom, row.height].every(Number.isFinite)) return;
      const top = read(), height = wrap.clientHeight, width = wrap.clientWidth;
      const contentTop = Math.round((top + row.top - viewport.top) * 2) / 2;
      const identity = [wrap.dataset.mode, node.dataset.page, node.dataset.system, node.dataset.row,
        contentTop, row.height, height, width].join(":");
      if (previous?.node === node && previous.identity === identity) return;
      previous = {node, identity};
      const target = targetFor(row, viewport, top, wrap.scrollHeight, height);
      if (Math.abs(target - top) >= 1) write(target);
    }
    function schedule() {
      if (alive && !frame) frame = win.requestAnimationFrame(flush);
    }
    Object.defineProperty(wrap, "scrollTop", {
      configurable: true, get: read,
      set(value) {
        if (!following() || (!anchor() && !previous)) { previous = null; write(value); return; }
        // Core RAF ticks and fitting observers may both request a scroll for
        // every note. Resolve their requests after all cursor painters finish,
        // and move only when the source row or viewport actually changes.
        schedule();
      }
    });
    const observer = new win.MutationObserver(schedule);
    observer.observe(wrap, {subtree: true, childList: true, attributes: true,
      attributeFilter: ["class", "data-mode", "data-playback-time"]});
    observer.observe(resume, {attributes: true, attributeFilter: ["hidden"]});
    const resize = new win.ResizeObserver(schedule); resize.observe(wrap);
    function reset() { previous = null; schedule(); }
    function message(event) {
      if (event.source !== win.parent || event.origin !== win.location.origin || event.data?.type !== "music-time") return;
      parentVisible = event.data.visible !== false;
      if (event.data.seekRevision != null) {
        if (revision != null && revision !== event.data.seekRevision) previous = null;
        revision = event.data.seekRevision;
      }
      schedule();
    }
    resume.addEventListener("click", reset);
    win.addEventListener("message", message);
    doc.addEventListener("visibilitychange", reset);
    function stop() {
      alive = false; win.cancelAnimationFrame(frame); observer.disconnect(); resize.disconnect();
      delete wrap.scrollTop; delete wrap.dataset.stableScroll;
      resume.removeEventListener("click", reset); win.removeEventListener("message", message);
      doc.removeEventListener("visibilitychange", reset); win.removeEventListener("pagehide", stop);
    }
    win.addEventListener("pagehide", stop, {once: true});
    wrap.dataset.stableScroll = "enabled"; schedule();
    return {flush, stop};
  }
  if (typeof module === "object" && module.exports) module.exports = {targetFor, install};
  else if (root.document.readyState === "complete") install(root);
  else root.addEventListener("load", () => install(root), {once: true});
})(typeof window === "object" ? window : {});

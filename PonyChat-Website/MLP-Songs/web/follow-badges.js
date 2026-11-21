/* Availability comes only from the songs API supplied by the library loader. */
(function (root) {
  "use strict";
  const LABEL = "有跟谱", NS = "http://www.w3.org/2000/svg";
  const eligible = (song) => typeof song?.followId === "string" && /^[a-z0-9-]+$/.test(song.followId);
  function create(doc, player) {
    let songs = new Map(), observer = null, scheduled = false;
    const ownedLabels = new WeakMap();
    function icon() {
      const svg = doc.createElementNS(NS, "svg");
      svg.setAttribute("class", "follow-available-icon");
      svg.setAttribute("viewBox", "0 0 16 20");
      svg.setAttribute("width", "16"); svg.setAttribute("height", "20");
      svg.setAttribute("role", "img"); svg.setAttribute("aria-label", LABEL);
      svg.setAttribute("focusable", "false");
      const stem = doc.createElementNS(NS, "path");
      stem.setAttribute("d", "M11 2h2v13h-2z"); stem.setAttribute("fill", "currentColor");
      const head = doc.createElementNS(NS, "ellipse");
      head.setAttribute("cx", "8"); head.setAttribute("cy", "15");
      head.setAttribute("rx", "5"); head.setAttribute("ry", "3.2");
      head.setAttribute("transform", "rotate(-22 8 15)"); head.setAttribute("fill", "currentColor");
      svg.append(stem, head);
      return svg;
    }
    function accessible(button, text, enabled) {
      if (!button) return;
      const previous = ownedLabels.get(button);
      if (enabled) {
        const next = text + "，" + LABEL;
        if (button.getAttribute("aria-label") !== next) button.setAttribute("aria-label", next);
        ownedLabels.set(button, {original: previous?.original ?? text, value: next});
      } else if (previous) {
        if (button.getAttribute("aria-label") === previous.value) button.setAttribute("aria-label", previous.original);
        ownedLabels.delete(button);
      }
    }
    function decorate(title, enabled) {
      if (!title) return;
      const existing = title.querySelector(".follow-available-icon");
      const label = title.querySelector(".follow-title-label");
      if (!enabled) {
        existing?.remove();
        if (label) label.replaceWith(...label.childNodes);
        title.classList.remove("follow-title-marked");
        return;
      }
      if (!existing) {
        const text = doc.createElement("span"); text.className = "follow-title-label";
        text.append(...title.childNodes);
        title.append(text, icon());
      }
      title.classList.add("follow-title-marked");
    }
    function available(song) { return !!song && eligible(songs.get(song.id)); }
    function refresh() {
      for (const row of doc.querySelectorAll(".song-row[data-song-id]")) {
        const song = songs.get(row.dataset.songId), enabled = available(song);
        decorate(row.querySelector(".song-title"), enabled);
        accessible(row.querySelector(".song-main"), "播放 " + (song?.title || ""), enabled);
      }
      const queue = player()?.getQueue?.() || [];
      [...doc.querySelectorAll("#queueList .queue-song")].forEach((button, i) => {
        const song = queue[i], enabled = available(song);
        decorate(button.children[1], enabled);
        accessible(button, "播放 " + (song?.title || ""), enabled);
      });
      const current = player()?.current?.(), enabled = available(current);
      decorate(doc.getElementById("playerTitle"), enabled);
      decorate(doc.getElementById("nowTitle"), enabled);
      const currentButton = doc.getElementById("playerTitle");
      const currentLabel = (current?.title || "未播放") + (enabled ? "，" + LABEL : "");
      if (currentButton && currentButton.getAttribute("aria-label") !== currentLabel) currentButton.setAttribute("aria-label", currentLabel);
    }
    function setSongs(apiSongs) {
      songs = new Map((apiSongs || []).map((song) => [song.id, song]));
      if (!observer && root.MutationObserver) {
        observer = new root.MutationObserver(() => {
          if (scheduled) return;
          scheduled = true;
          root.queueMicrotask(() => {scheduled = false; refresh();});
        });
        for (const id of ["trackList", "searchResults", "queueList", "playerTitle", "nowTitle"]) {
          const target = doc.getElementById(id);
          if (target) observer.observe(target, {childList: true, subtree: true, characterData: true});
        }
      }
      refresh();
    }
    return {setSongs, refresh};
  }
  if (typeof module === "object" && module.exports) module.exports = {eligible, create};
  else root.MusicFollowBadges = create(root.document, () => root.MusicPlayer);
})(typeof window === "object" ? window : globalThis);

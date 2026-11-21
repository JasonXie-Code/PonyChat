/* Keep visible lyrics current when animation delivery or media events are sparse. */
(function () {
  "use strict";
  const audio = document.querySelector("#audio");
  const player = document.querySelector("#nowPlaying");
  const pane = document.querySelector("#lyricsPane");
  if (!audio || !player || !pane) return;
  let timer = null;
  function visible() { return !document.hidden && !player.hidden && !pane.hidden; }
  function paint() {
    if (visible() && window.MusicLyrics) window.MusicLyrics.update(audio.currentTime);
  }
  function stop() { if (timer !== null) clearInterval(timer); timer = null; }
  function synchronize() {
    paint();
    if (!visible() || audio.paused || audio.ended) {stop(); return;}
    if (timer === null) timer = setInterval(synchronize, 50);
  }
  ["play", "pause", "ended", "seeked", "timeupdate"].forEach(name => audio.addEventListener(name, synchronize));
  document.addEventListener("visibilitychange", synchronize);
  const observer = new MutationObserver(synchronize);
  [player, pane].forEach(node => observer.observe(node, {attributes: true, attributeFilter: ["hidden"]}));
  synchronize();
})();

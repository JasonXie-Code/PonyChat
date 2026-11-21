/* Coordinate recording handoff while the browser loads audio directly. */
(function () {
  "use strict";
  const player = window.MusicPlayer;
  const audio = document.querySelector("#audio");
  const service = navigator.serviceWorker;
  if (!player || !audio) return;

  const warmer = new Audio();
  warmer.preload = "auto";
  let queue = [], index = -1, expected = "", warmUrl = "";
  let releaseSwitch = null, mutedBeforeSwitch = false, nativeGuard = false;

  function prepareNext() {
    const mode = document.querySelector("#playMode")?.textContent;
    const song = queue[index + 1] || (mode === "列表循环" ? queue[0] : null);
    const url = song && new URL(song.src, location.href);
    const target = index >= 0 && !navigator.connection?.saveData && mode !== "随机播放"
      && mode !== "单曲循环" && url?.origin === location.origin && url.href !== expected ? url.href : "";

    // Preserve the warm request while the main decoder opens that recording.
    const playing = !audio.paused && audio.currentSrc === expected && audio.readyState >= 3;
    if (!playing && warmUrl && warmUrl === audio.src) return;
    if (warmUrl && warmUrl !== target) {
      warmer.removeAttribute("src");
      warmer.load();
      warmUrl = "";
    }
    if (playing && target && !warmUrl) {
      warmUrl = target;
      warmer.src = target;
    }
  }

  function bindMuteButton() {
    const button = document.querySelector("#toggleMute");
    const slider = document.querySelector("#vol");
    if (!button || !slider) return;
    let lastVolume = Number(slider.value) || 100;
    const muted = () => nativeGuard ? mutedBeforeSwitch : audio.muted;
    function updateButton() {
      const silent = muted() || Number(slider.value) === 0;
      button.setAttribute("aria-pressed", String(silent));
      button.dataset.tooltip = silent ? "取消静音" : "静音";
    }
    function setMute(value) {
      if (nativeGuard) mutedBeforeSwitch = value;
      else audio.muted = value;
      updateButton();
    }
    slider.addEventListener("input", () => {
      const volume = Number(slider.value);
      if (volume > 0) {
        lastVolume = volume;
        setMute(false);
      } else {
        updateButton();
      }
    });
    button.addEventListener("click", () => {
      if (Number(slider.value) === 0) {
        slider.value = String(lastVolume);
        slider.dispatchEvent(new Event("input", {bubbles: true}));
      } else {
        setMute(!muted());
      }
    });
    audio.addEventListener("volumechange", updateButton);
    updateButton();
  }

  function resetRecording(song) {
    releaseSwitch?.(false);
    window.MusicAudioOutput?.hold();
    expected = song ? new URL(song.src, location.href).href : "";
    if (!song) {
      if (nativeGuard) audio.muted = mutedBeforeSwitch;
      nativeGuard = false;
      prepareNext();
      return;
    }

    if (!nativeGuard) mutedBeforeSwitch = audio.muted;
    nativeGuard = nativeGuard || !window.MusicAudioOutput?.smooth();
    if (nativeGuard) {
      audio.muted = true;
    }
    function release(restore = true) {
      if (releaseSwitch !== release) return;
      for (const event of ["loadeddata", "canplay", "playing"]) audio.removeEventListener(event, ready);
      audio.removeEventListener("error", failed);
      releaseSwitch = null;
      if (nativeGuard && restore) {
        nativeGuard = false;
        audio.muted = mutedBeforeSwitch;
      }
    }
    function ready() {
      if (audio.currentSrc === expected && audio.readyState >= 2) release();
    }
    function failed() { if (audio.error) release(); }
    releaseSwitch = release;
    for (const event of ["loadeddata", "canplay", "playing"]) audio.addEventListener(event, ready);
    audio.addEventListener("error", failed);
    // Flush the previous decoder before the core calls play on the selected src.
    audio.load();
  }

  let onQueue = () => {};
  const setCallbacks = player.setCallbacks;
  player.setCallbacks = function ({onSong, onQueue: queueCallback, ...callbacks}) {
    if (queueCallback) onQueue = queueCallback;
    callbacks.onQueue = function (songs, currentIndex) {
      queue = songs;
      index = currentIndex;
      prepareNext();
      onQueue(songs, currentIndex);
    };
    if (onSong) {
      callbacks.onSong = function (song) {
        resetRecording(song);
        onSong(song);
      };
    }
    setCallbacks(callbacks);
  };

  bindMuteButton();
  audio.addEventListener("playing", () => {
    if (expected && audio.currentSrc === expected && audio.readyState >= 2 && !audio.paused) {
      window.MusicAudioOutput?.open();
      prepareNext();
    }
  });
  document.querySelector("#playMode")?.addEventListener("click", prepareNext);
  navigator.connection?.addEventListener("change", prepareNext);

  // Update older tabs to the worker that releases control. New tabs need no registration.
  const oldWorker = new URL("/audio-preload-worker.js", location.href).href;
  if (service?.controller?.scriptURL === oldWorker) {
    service.controller.postMessage({type: "music-preload-clear"});
  }
  service?.getRegistration(location.href).then(registration => {
    if (registration?.scope === new URL("/", location.href).href
        && [registration.active, registration.waiting, registration.installing]
          .some(worker => worker?.scriptURL === oldWorker)) {
      return registration.update();
    }
  }).catch(() => {});
})();

/* Keep the transition envelope and optional loudness correction in one output graph. */
(function () {
  "use strict";
  const player = window.MusicPlayer;
  const audio = document.querySelector("#audio");
  const button = document.querySelector("#normalizeVolume");
  const slider = document.querySelector("#vol");
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!player || !audio || !button || !slider) return;

  const defaultTitle = "按歌曲均衡响度（目标 −11 LUFS）";
  let enabled = false;
  let context, limiter, transition, output, starting;
  let held = true, reopenAt = 0;
  const worklets = AudioContext && window.AudioWorkletNode;
  // iOS suspends Web Audio in the background. Keep native playback there by default.
  const mobileApple = /iP(?:hone|ad|od)/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  function hold() {
    if (held) return;
    held = true;
    if (!transition) return;
    const now = context.currentTime;
    const gate = transition.parameters.get("open");
    gate.cancelScheduledValues(now);
    gate.setValueAtTime(0, now);
    reopenAt = now + 0.006;
  }

  function open() {
    held = false;
    if (transition) {
      transition.parameters.get("open").setValueAtTime(1, Math.max(context.currentTime, reopenAt));
    }
  }

  window.MusicAudioOutput = {hold, open, smooth: () => Boolean(transition)};

  function setParameter(parameter, value, smooth) {
    const now = context.currentTime;
    parameter.cancelScheduledValues(now);
    if (smooth) parameter.setTargetAtTime(value, now, 0.012);
    else parameter.setValueAtTime(value, now);
  }

  function apply(song, smooth = false) {
    button.title = song && !song.loudnessPlayback ? "这首歌暂无响度数据" : defaultTitle;
    if (!limiter) return;
    const settings = enabled ? song?.loudnessPlayback : null;
    setParameter(limiter.parameters.get("gain"), settings?.gain ?? 1, smooth);
    // Keep the transition safe while the per-song gain ramps back to unity.
    setParameter(limiter.parameters.get("ceiling"), settings?.ceiling ?? 1, false);
  }

  function applyVolume() {
    if (!output) return;
    const volume = Number(slider.value) / 100;
    if (audio.volume !== 1) audio.volume = 1;
    setParameter(output.gain, audio.muted ? 0 : volume, true);
  }

  async function start() {
    const candidate = new AudioContext({sampleRate: 48000, latencyHint: "interactive"});
    try {
      const [fadeModule, loudnessModule] = await Promise.allSettled([
        candidate.audioWorklet.addModule("/audio-transition.js?v=1"),
        candidate.audioWorklet.addModule("/loudness-limiter.js?v=1"),
        candidate.resume(),
      ]);
      const stereo = {channelCount: 2, channelCountMode: "explicit", outputChannelCount: [2]};
      const fade = fadeModule.status === "fulfilled" ? new AudioWorkletNode(candidate,
        "music-audio-transition", {...stereo, parameterData: {open: held ? 0 : 1}}) : null;
      const processor = loudnessModule.status === "fulfilled" ? new AudioWorkletNode(candidate,
        "music-loudness-limiter", {...stereo, parameterData: {ceiling: 1}}) : null;
      if ((!fade && !processor) || candidate.state !== "running") throw Error("Audio output unavailable");
      const level = candidate.createGain();
      level.gain.value = audio.muted ? 0 : Number(slider.value) / 100;
      const source = candidate.createMediaElementSource(audio);
      source.connect(processor || fade || level);
      processor?.connect(fade || level);
      fade?.connect(level);
      level.connect(candidate.destination);
      processor?.addEventListener("processorerror", () => {
        source.disconnect(processor);
        source.connect(transition || level);
        processor.disconnect();
        limiter = null;
        enabled = false;
        button.setAttribute("aria-pressed", "false");
        button.title = "当前浏览器无法使用均衡音量";
      }, {once: true});
      fade?.addEventListener("processorerror", () => {
        const input = limiter || source;
        input.disconnect(fade);
        input.connect(level);
        fade.disconnect();
        transition = null;
      }, {once: true});
      context = candidate;
      limiter = processor;
      transition = fade;
      output = level;
      apply(player.current());
      applyVolume();
    } catch (error) {
      await candidate.close().catch(() => {});
      throw error;
    }
  }

  button.title = defaultTitle;
  button.disabled = !worklets;
  if (button.disabled) button.title = "当前浏览器无法使用均衡音量";
  function ensureOutput() {
    return starting ||= start().finally(() => { starting = null; });
  }
  button.onclick = async () => {
    enabled = !enabled;
    button.setAttribute("aria-pressed", String(enabled));
    if (enabled && !limiter) {
      try {
        if (!context) await ensureOutput();
        if (!limiter) throw Error("Loudness output unavailable");
      }
      catch (_) {
        enabled = false;
        button.setAttribute("aria-pressed", "false");
        button.title = "暂时无法启用均衡音量，点击重试";
        return;
      }
    }
    apply(player.current(), true);
  };

  if (button.disabled) return;
  let tried = false;
  // Run the gate in the same task as the certified player's native pause and play.
  const nativePlay = audio.play.bind(audio);
  const nativePause = audio.pause.bind(audio);
  audio.play = function () {
    if (!tried && !context && !mobileApple) {
      tried = true;
      ensureOutput().catch(() => {});
    }
    if (context && context.state !== "running") context.resume().catch(() => {});
    return nativePlay();
  };
  audio.pause = function () {
    hold();
    return nativePause();
  };
  const setCallbacks = player.setCallbacks;
  player.setCallbacks = function (callbacks) {
    setCallbacks({
      ...callbacks,
      onSong(song) {
        limiter?.port.postMessage("reset");
        apply(song);
        applyVolume();
        callbacks.onSong?.(song);
      },
    });
  };
  slider.addEventListener("input", applyVolume);
  audio.addEventListener("volumechange", applyVolume);
  audio.addEventListener("seeking", () => limiter?.port.postMessage("reset"));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !audio.paused && context?.state !== "running") context?.resume().catch(() => {});
  });
})();

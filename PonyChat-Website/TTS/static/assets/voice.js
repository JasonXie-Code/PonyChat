const state = {
  voices: [],
  speakers: [],
  speakerMeta: [],
  selectedVoice: "",
  segmentedMode: false,
  mobileMicrophone: false,
  currentAudio: {
    originalUrl: "",
    mobileUrl: "",
    filename: "",
    mobileFilename: "",
  },
  railSyncFrame: 0,
};

const $ = (id) => document.getElementById(id);
const API_BASE = (document.body?.dataset?.apiBase || "").replace(/\/+$/, "");
const customSelects = new Set();
const DIALECT_LABELS = {
  sichuan_dialect: "四川话",
  beijing_dialect: "北京话",
};
const SPEAKER_LABELS = {
  eric: "eric（四川话）",
  dylan: "dylan（北京话）",
};
const DESIGN_REFERENCE_TEXT = "晨光落在旧城门上，我们用温柔而清晰的声音说：今天也要勇敢前行。Across the quiet sky, I keep my promise with a steady smile. 星の下で、君の名前をそっと呼びます。";

function htmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error-text", isError);
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 3200);
}

function apiUrl(url) {
  const value = String(url || "");
  if (!value || /^(?:https?:|blob:|data:)/i.test(value)) return value;
  if (!API_BASE || !value.startsWith("/")) return value;
  return `${API_BASE}${value}`;
}

function setBusy(button, busy, label = "处理中...") {
  if (!button) return;
  button.disabled = busy;
  button.setAttribute("aria-busy", busy ? "true" : "false");
  if (busy) {
    if (!button.dataset.idleHtml) button.dataset.idleHtml = button.innerHTML;
    button.classList.add("busy-button");
    button.innerHTML = `<span class="button-label">${htmlEscape(label)}</span><span class="button-spinner" aria-hidden="true"></span>`;
  } else {
    if (button.dataset.idleHtml) button.innerHTML = button.dataset.idleHtml;
    button.classList.remove("busy-button");
    button.removeAttribute("aria-busy");
    delete button.dataset.idleHtml;
  }
}

function filenamePart(value, fallback) {
  const text = String(value || "").trim() || fallback;
  return text
    .replace(/[\\/:*?"<>|\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/^[ .-]+|[ .-]+$/g, "")
    .slice(0, 80) || fallback;
}

function textPreview(text, limit = 8) {
  const source = String(text || "").trim();
  if (!source) return "audio";
  if (!/[\u4e00-\u9fff]/.test(source)) {
    const words = source.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?/g);
    if (words?.length) return words.slice(0, limit).join(" ");
  }
  return Array.from(source.replace(/\s+/g, "")).slice(0, limit).join("") || "audio";
}

function timestampMs(date = new Date()) {
  const pad = (value, size = 2) => String(value).padStart(size, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join("") + pad(date.getMilliseconds(), 3);
}

function downloadFilename(role, text) {
  return `${filenamePart(role, "voice")} - ${filenamePart(textPreview(text), "audio")} - ${timestampMs()}.wav`;
}

async function apiJson(url, options = {}) {
  const res = await fetch(apiUrl(url), options);
  if (!res.ok) {
    let text = await res.text();
    try { text = JSON.parse(text).detail || text; } catch (_) {}
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function apiBlob(url, options = {}) {
  const res = await fetch(apiUrl(url), options);
  if (!res.ok) {
    let text = await res.text();
    try { text = JSON.parse(text).detail || text; } catch (_) {}
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.blob();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForJob(jobId, button, labels = {}) {
  const queued = labels.queued || "排队中";
  const running = labels.running || "生成中";
  for (;;) {
    const job = await apiJson(`/jobs/${encodeURIComponent(jobId)}`);
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error || "任务失败");
    if (job.status === "running") {
      setBusy(button, true, `${running}...`);
    } else {
      const position = job.queue_position ? ` #${job.queue_position}` : "";
      setBusy(button, true, `${queued}${position}...`);
    }
    await sleep(1200);
  }
}

function parameterValue(prefix, key) {
  const panel = document.querySelector(`[data-parameter-panel="${prefix}"]`);
  const suffix = panel?.classList.contains("developer-mode") ? "Raw" : "";
  return Number($(`${prefix}${key}${suffix}`).value);
}

function syncDeveloperControls(prefix) {
  const keys = prefix === "design" ? ["Temperature", "TopP"] : ["Temperature", "TopK", "TopP"];
  keys.forEach((key) => {
    const friendly = $(`${prefix}${key}`);
    const raw = $(`${prefix}${key}Raw`);
    if (friendly && raw) raw.value = friendly.value;
  });
}

function setParameterMode(prefix, developerMode) {
  const panel = document.querySelector(`[data-parameter-panel="${prefix}"]`);
  const button = document.querySelector(`[data-parameter-toggle="${prefix}"]`);
  if (!panel || !button) return;
  if (developerMode) syncDeveloperControls(prefix);
  panel.classList.toggle("developer-mode", developerMode);
  button.setAttribute("aria-pressed", developerMode ? "true" : "false");
  button.textContent = developerMode ? "普通模式" : "开发者";
}

function mobileFilename(filename) {
  const name = filename || "qwen-tts.wav";
  if (name.toLowerCase().endsWith(".wav") || name.toLowerCase().endsWith(".mp3")) {
    return `${name.slice(0, -4)} - 手机拾音.mp3`;
  }
  return `${name} - 手机拾音.mp3`;
}

function activeAudio() {
  return state.mobileMicrophone ? $("audioPlayerMobile") : $("audioPlayer");
}

function inactiveAudio() {
  return state.mobileMicrophone ? $("audioPlayer") : $("audioPlayerMobile");
}

function audioPlayers() {
  return [$("audioPlayer"), $("audioPlayerMobile")].filter(Boolean);
}

function currentDownload() {
  const useMobile = state.mobileMicrophone && state.currentAudio.mobileUrl;
  return {
    url: useMobile ? state.currentAudio.mobileUrl : state.currentAudio.originalUrl,
    filename: useMobile
      ? (state.currentAudio.mobileFilename || mobileFilename(state.currentAudio.filename))
      : state.currentAudio.filename,
  };
}

function updateDownloadLink() {
  const link = $("downloadLink");
  const current = currentDownload();
  if (!current.url) {
    link.href = "#";
    link.download = "qwen-tts.wav";
    link.classList.add("disabled");
    return;
  }
  link.href = current.url;
  link.download = current.filename || "qwen-tts.wav";
  link.classList.remove("disabled");
}

function applyActiveAudio() {
  const active = activeAudio();
  const inactive = inactiveAudio();
  if (active) active.muted = false;
  if (inactive) inactive.muted = true;
  updateDownloadLink();
  updatePlayerState();
}

function waitForSeekable(audio) {
  if (!audio?.src || audio.readyState >= 1) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      audio.removeEventListener("loadedmetadata", done);
      audio.removeEventListener("canplay", done);
      audio.removeEventListener("error", done);
      resolve();
    };
    audio.addEventListener("loadedmetadata", done, { once: true });
    audio.addEventListener("canplay", done, { once: true });
    audio.addEventListener("error", done, { once: true });
  });
}

function waitForSeeked(audio) {
  if (!audio?.src) return Promise.resolve();
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      audio.removeEventListener("seeked", done);
      audio.removeEventListener("canplay", done);
      audio.removeEventListener("error", done);
      resolve();
    };
    const timer = setTimeout(done, 220);
    audio.addEventListener("seeked", done, { once: true });
    audio.addEventListener("canplay", done, { once: true });
    audio.addEventListener("error", done, { once: true });
  });
}

async function seekAudio(audio, time) {
  if (!audio?.src || !Number.isFinite(time)) return;
  await waitForSeekable(audio);
  const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : time;
  const target = Math.max(0, Math.min(time, Math.max(0, duration - 0.02)));
  try {
    if (Math.abs(audio.currentTime - target) > 0.05) {
      audio.currentTime = target;
      await waitForSeeked(audio);
    }
  } catch (_) {}
}

function bestCurrentTime(preferred) {
  const candidates = [preferred, ...audioPlayers()]
    .map((audio) => audio?.src && Number.isFinite(audio.currentTime) ? audio.currentTime : 0)
    .filter((value) => Number.isFinite(value));
  return Math.max(0, ...candidates);
}

function showAudioSources(sources, title, startedAt) {
  const filename = sources.filename || "qwen-tts.wav";
  state.currentAudio = {
    originalUrl: sources.originalUrl || sources.url || "",
    mobileUrl: sources.mobileUrl || sources.originalUrl || sources.url || "",
    filename,
    mobileFilename: sources.mobileFilename || mobileFilename(filename),
  };
  const original = $("audioPlayer");
  const mobile = $("audioPlayerMobile");
  audioPlayers().forEach((audio) => {
    audio.pause();
    audio.currentTime = 0;
  });
  original.src = state.currentAudio.originalUrl;
  mobile.src = state.currentAudio.mobileUrl;
  original.load();
  mobile.load();
  mobile.muted = true;
  applyActiveAudio();
  $("outputTitle").textContent = title;
  if (startedAt) {
    const seconds = ((performance.now() - startedAt) / 1000).toFixed(2);
    toast(`完成，用时 ${seconds}s`);
  }
}

function audioSourcesFromJob(job, fallbackUrl, fallbackFilename) {
  const originalUrl = job.original_audio_url || job.audio_url || job.result_url || fallbackUrl || "";
  const mobileUrl = job.mobile_audio_url || originalUrl;
  const filename = job.filename || fallbackFilename || "qwen-tts.wav";
  return {
    originalUrl: apiUrl(originalUrl),
    mobileUrl: apiUrl(mobileUrl),
    filename,
    mobileFilename: job.mobile_filename || mobileFilename(filename),
  };
}

function formatTime(value) {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function updatePlayerState() {
  const audio = activeAudio();
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  const current = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  const progress = duration > 0 ? Math.min(1000, Math.max(0, (current / duration) * 1000)) : 0;
  $("currentTime").textContent = formatTime(current);
  $("durationTime").textContent = formatTime(duration);
  $("seekBar").value = String(progress);
  $("seekBar").style.setProperty("--progress", `${progress / 10}%`);
  $("playButton").classList.toggle("playing", !audio.paused && !audio.ended);
}

function syncVoiceRailHeight() {
  const rail = document.querySelector(".voice-rail");
  const tool = document.querySelector(".tool-panel");
  if (!rail || !tool) return;
  const height = Math.ceil(tool.getBoundingClientRect().height);
  if (height > 0) rail.style.setProperty("--voice-rail-max-height", `${height}px`);
}

function scheduleVoiceRailSync() {
  cancelAnimationFrame(state.railSyncFrame);
  state.railSyncFrame = requestAnimationFrame(syncVoiceRailHeight);
}

function normalizeSpeakerMeta(payload) {
  const meta = Array.isArray(payload.speaker_meta) ? payload.speaker_meta : [];
  if (meta.length) {
    return meta.map((item) => ({
      id: String(item.id || item.voice_id || "").replace(/^speaker:/, ""),
      voiceId: item.voice_id || `speaker:${String(item.id || "").replace(/^speaker:/, "")}`,
      dialect: item.dialect || "",
    })).filter((item) => item.id);
  }
  return (payload.speakers || []).map((name) => ({
    id: String(name).replace(/^speaker:/, ""),
    voiceId: `speaker:${String(name).replace(/^speaker:/, "")}`,
    dialect: "",
  }));
}

function speakerLabel(name) {
  return SPEAKER_LABELS[name] || name;
}

function selectedTtsLanguage() {
  return "Auto";
}

function renderVoices() {
  const list = $("voiceList");
  const select = $("ttsVoice");
  const table = $("voiceTable");
  list.innerHTML = "";
  select.innerHTML = "";
  table.innerHTML = "";
  const systemVoices = state.speakerMeta;

  if (!state.voices.length && !systemVoices.length) {
    list.innerHTML = '<p class="run-meta">暂无声音</p>';
    table.innerHTML = '<p class="run-meta">暂无声音</p>';
  }

  for (const voice of state.voices) {
    const id = typeof voice === "string" ? voice : voice.id;
    const summary = typeof voice === "string" ? "" : (voice.summary || voice.ref_text || "");
    const summaryLabel = typeof voice === "string" ? "参考文本" : (voice.summary_label || "参考文本");
    const option = document.createElement("option");
    option.value = id;
    option.textContent = id;
    select.appendChild(option);

    const item = document.createElement("button");
    item.type = "button";
    item.className = `voice-item${id === state.selectedVoice ? " active" : ""}`;
    item.innerHTML = `<strong>${id}</strong><span>${summary ? summary.slice(0, 34) : "QwenTTS voice"}</span>`;
    item.addEventListener("click", () => {
      state.selectedVoice = id;
      select.value = id;
      renderVoices();
    });
    list.appendChild(item);

    const row = document.createElement("div");
    row.className = "voice-row";
    const encodedId = encodeURIComponent(id);
    row.innerHTML = `
      <div>
        <button class="voice-title-button" type="button" data-edit="${encodedId}" title="点击编辑名称">${htmlEscape(id)}</button>
        <input class="voice-name-input" data-name-for="${encodedId}" value="${htmlEscape(id)}">
        <small>${htmlEscape(summaryLabel)}：${htmlEscape(summary || "未记录")}</small>
      </div>
      <button class="secondary-btn" type="button" data-use="${encodedId}">使用</button>
      <a class="download-link" href="${apiUrl(`/voices/${encodedId}/audio`)}" download="${htmlEscape(id)}.wav">参考音频</a>
      <button class="danger-btn" type="button" data-delete="${encodedId}">删除</button>
    `;
    table.appendChild(row);
  }

  if (systemVoices.length) {
    const group = document.createElement("optgroup");
    group.label = "系统预置（不可编辑）";
    for (const speaker of systemVoices) {
      const option = document.createElement("option");
      option.value = speaker.voiceId;
      option.textContent = `预置 · ${speakerLabel(speaker.id)}`;
      group.appendChild(option);

      const summary = speaker.dialect ? `${DIALECT_LABELS[speaker.dialect] || speaker.dialect} · 系统内置` : "系统内置音色";
      const item = document.createElement("button");
      item.type = "button";
      item.className = `voice-item system-voice${speaker.voiceId === state.selectedVoice ? " active" : ""}`;
      item.innerHTML = `<strong>${htmlEscape(speakerLabel(speaker.id))}</strong><span>${htmlEscape(summary)}</span>`;
      item.addEventListener("click", () => {
        state.selectedVoice = speaker.voiceId;
        select.value = speaker.voiceId;
        renderVoices();
      });
      list.appendChild(item);

      const row = document.createElement("div");
      row.className = "voice-row locked";
      const encodedId = encodeURIComponent(speaker.voiceId);
      row.innerHTML = `
        <div>
          <strong class="voice-title-static">${htmlEscape(speakerLabel(speaker.id))}</strong>
          <small>系统预置：${htmlEscape(summary)}</small>
        </div>
        <span class="locked-badge">不可编辑</span>
        <button class="secondary-btn" type="button" data-use="${encodedId}">使用</button>
      `;
      table.appendChild(row);
    }
    select.appendChild(group);
  }

  const selectable = [
    ...state.voices.map((v) => (typeof v === "string" ? v : v.id)),
    ...systemVoices.map((s) => s.voiceId),
  ];
  if (!state.selectedVoice || !selectable.includes(state.selectedVoice)) {
    state.selectedVoice = selectable[0] || "";
  }
  if (state.selectedVoice) select.value = state.selectedVoice;
  refreshCustomSelect(select);
  scheduleVoiceRailSync();
}

function closeCustomSelects(except = null) {
  customSelects.forEach((select) => {
    const api = select._customSelect;
    if (!api || api.root === except) return;
    api.root.classList.remove("open");
    api.button.setAttribute("aria-expanded", "false");
  });
}

function refreshCustomSelect(select) {
  const api = select?._customSelect;
  if (!api) return;
  const selected = select.options[select.selectedIndex];
  api.value.textContent = selected ? selected.textContent : "";
  api.menu.innerHTML = "";
  Array.from(select.options).forEach((option) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `custom-select-option${option.value === select.value ? " selected" : ""}`;
    item.textContent = option.textContent;
    item.dataset.value = option.value;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
    item.addEventListener("click", () => {
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      refreshCustomSelect(select);
      closeCustomSelects();
    });
    api.menu.appendChild(item);
  });
}

function enhanceSelect(select) {
  if (!select || select._customSelect) return;
  select.classList.add("native-select-hidden");
  const root = document.createElement("div");
  root.className = "custom-select";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "custom-select-trigger";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  const value = document.createElement("span");
  value.className = "custom-select-value";
  const arrow = document.createElement("span");
  arrow.className = "custom-select-arrow";
  arrow.setAttribute("aria-hidden", "true");
  const menu = document.createElement("div");
  menu.className = "custom-select-menu";
  menu.setAttribute("role", "listbox");
  button.append(value, arrow);
  root.append(button, menu);
  select.insertAdjacentElement("afterend", root);
  select._customSelect = { root, button, value, menu };
  customSelects.add(select);
  button.addEventListener("click", () => {
    const willOpen = !root.classList.contains("open");
    closeCustomSelects(root);
    root.classList.toggle("open", willOpen);
    button.setAttribute("aria-expanded", willOpen ? "true" : "false");
  });
  select.addEventListener("change", () => refreshCustomSelect(select));
  refreshCustomSelect(select);
}

function stepNumberInput(input, direction) {
  if (!input) return;
  try {
    direction > 0 ? input.stepUp() : input.stepDown();
  } catch (_) {
    const step = Number(input.step) || 1;
    const min = input.min === "" ? -Infinity : Number(input.min);
    const max = input.max === "" ? Infinity : Number(input.max);
    const base = input.value === "" ? (Number.isFinite(min) ? min : 0) : Number(input.value);
    const precision = Math.max(0, (String(input.step).split(".")[1] || "").length);
    const next = Math.min(max, Math.max(min, base + direction * step));
    input.value = Number.isFinite(next) ? next.toFixed(precision).replace(/\.?0+$/, "") : "";
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function enhanceNumberInput(input) {
  if (!input || input._numberStepper) return;
  const root = document.createElement("div");
  root.className = "number-stepper";
  input.insertAdjacentElement("beforebegin", root);
  root.appendChild(input);
  const controls = document.createElement("div");
  controls.className = "number-stepper-controls";
  const up = document.createElement("button");
  up.type = "button";
  up.className = "number-stepper-btn up";
  up.setAttribute("aria-label", "增加");
  const down = document.createElement("button");
  down.type = "button";
  down.className = "number-stepper-btn down";
  down.setAttribute("aria-label", "减少");
  controls.append(up, down);
  root.appendChild(controls);
  up.addEventListener("click", () => { input.focus(); stepNumberInput(input, 1); });
  down.addEventListener("click", () => { input.focus(); stepNumberInput(input, -1); });
  input._numberStepper = { root, up, down };
}

async function refreshVoices() {
  const data = await apiJson("/voices/meta");
  state.voices = data.voices || [];
  if (!state.speakers.length) {
    try {
      const sp = await apiJson("/speakers");
      state.speakers = sp.speakers || [];
      state.speakerMeta = normalizeSpeakerMeta(sp);
    } catch (_) {
      state.speakers = [];
      state.speakerMeta = [];
    }
  }
  renderVoices();
}

async function refreshHealth() {
  const data = await apiJson("/health");
  $("backendStatus").textContent = data.backend || "QwenTTS";
  $("speedStatus").textContent = `${data.device || "cuda"} · ${data.clone_dtype || "float32"}`;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-pane").forEach((pane) => pane.classList.toggle("active", pane.dataset.pane === name));
  scheduleVoiceRailSync();
}

function readSegments() {
  const rows = Array.from(document.querySelectorAll("#ttsSegments .seg-row"));
  const segments = [];
  for (const row of rows) {
    const text = row.querySelector(".seg-text")?.value?.trim();
    if (!text) continue;
    segments.push({ text, instruct: row.querySelector(".seg-instruct")?.value?.trim() || "" });
  }
  return segments;
}

function resizeSegmentText(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  const minHeight = parseFloat(getComputedStyle(textarea).minHeight) || 42;
  textarea.style.height = `${Math.max(textarea.scrollHeight, minHeight)}px`;
  scheduleVoiceRailSync();
}

function addSegment(text = "", instruct = "") {
  const container = $("ttsSegments");
  const row = document.createElement("div");
  row.className = "seg-row";
  row.innerHTML = `
    <textarea class="seg-text" rows="1" placeholder="这一段的文本"></textarea>
    <input class="seg-instruct" type="text" placeholder="这一段的情绪，如：生气地、压低声音">
    <button class="ghost-btn seg-del" type="button" aria-label="删除该段">×</button>
  `;
  const textInput = row.querySelector(".seg-text");
  textInput.value = text;
  textInput.addEventListener("input", () => resizeSegmentText(textInput));
  row.querySelector(".seg-instruct").value = instruct;
  row.querySelector(".seg-del").addEventListener("click", () => {
    row.remove();
    if (!$("ttsSegments").querySelector(".seg-row")) addSegment();
    scheduleVoiceRailSync();
  });
  container.appendChild(row);
  resizeSegmentText(textInput);
  scheduleVoiceRailSync();
}

function setSegmentedMode(on) {
  state.segmentedMode = on;
  $("ttsSingleBlock").hidden = on;
  $("ttsSegmentsBlock").hidden = !on;
  const button = $("segToggle");
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.textContent = on ? "单段模式" : "分段情绪";
  if (on && !$("ttsSegments").querySelector(".seg-row")) {
    addSegment($("ttsText").value || "", $("ttsInstruct").value || "");
  }
  scheduleVoiceRailSync();
}

async function syncShadowPlayback() {
  const active = activeAudio();
  const inactive = inactiveAudio();
  if (!active?.src || !inactive?.src) return;
  inactive.muted = true;
  await seekAudio(inactive, active.currentTime);
  if (!active.paused && !active.ended) {
    try {
      await inactive.play();
    } catch (_) {}
  } else {
    inactive.pause();
  }
}

async function setMobileMicrophone(on) {
  const previous = activeAudio();
  const keepTime = bestCurrentTime(previous);
  const wasPlaying = Boolean(previous?.src && !previous.paused && !previous.ended);
  audioPlayers().forEach((audio) => audio.pause());
  state.mobileMicrophone = on;
  const button = $("mobileMicToggle");
  if (button) {
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.classList.toggle("active", on);
    button.title = on ? "正在播放手机拾音版本，下载也会选择该版本" : "正在播放原始版本，下载也会选择原始版本";
  }
  await Promise.all(audioPlayers().map((audio) => seekAudio(audio, keepTime)));
  applyActiveAudio();
  if (wasPlaying && activeAudio()?.src) {
    try {
      await seekAudio(activeAudio(), keepTime);
      await activeAudio().play();
      await syncShadowPlayback();
    } catch (_) {}
  }
}

async function handleTts(event) {
  event.preventDefault();
  const button = event.submitter;
  setBusy(button, true, "生成中...");
  const started = performance.now();
  try {
    const voiceId = $("ttsVoice").value;
    if (!voiceId) throw new Error("请选择声音");
    const common = {
      voice_id: voiceId,
      language: selectedTtsLanguage(),
      temperature: parameterValue("tts", "Temperature"),
      top_k: parameterValue("tts", "TopK"),
      top_p: parameterValue("tts", "TopP"),
      mobile_microphone: state.mobileMicrophone,
    };
    let queued;
    let previewText;
    if (state.segmentedMode) {
      const segments = readSegments();
      if (!segments.length) throw new Error("请至少填写一个段落文本");
      previewText = segments.map((s) => s.text).join(" ");
      queued = await apiJson("/jobs/tts/segmented", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...common, segments }),
      });
    } else {
      previewText = $("ttsText").value;
      queued = await apiJson("/jobs/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...common, text: previewText, instruct: $("ttsInstruct").value }),
      });
    }
    const job = await waitForJob(queued.job_id, button, { queued: "排队中", running: "生成中" });
    showAudioSources(
      audioSourcesFromJob(job, `/jobs/${encodeURIComponent(job.job_id)}/audio`, downloadFilename(voiceId.replace("speaker:", ""), previewText)),
      "合成结果",
      started,
    );
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function handleClone(event) {
  event.preventDefault();
  const button = event.submitter;
  setBusy(button, true, "创建中...");
  const started = performance.now();
  try {
    const file = $("cloneAudio").files[0];
    if (!file) throw new Error("请选择参考音频");
    const form = new FormData();
    form.append("name", $("cloneName").value);
    form.append("language", "Auto");
    form.append("ref_text", $("cloneRefText").value);
    form.append("preview_text", $("clonePreviewText").value);
    form.append("ref_audio", file);
    const queued = await apiJson("/jobs/voices/clone", { method: "POST", body: form });
    const data = await waitForJob(queued.job_id, button, { queued: "排队中", running: "创建中" });
    await refreshVoices();
    state.selectedVoice = data.voice_id;
    renderVoices();
    if (data.audio_url || data.result_url) {
      showAudioSources(
        audioSourcesFromJob(data, data.audio_url || data.result_url, data.filename || downloadFilename(data.voice_id, $("clonePreviewText").value)),
        "克隆试音",
        started,
      );
    } else {
      toast(`已创建 ${data.voice_id}`);
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function handleClonePreview() {
  setBusy($("clonePreview"), true, "试音中...");
  const started = performance.now();
  try {
    const file = $("cloneAudio").files[0];
    if (!file) throw new Error("请选择参考音频");
    const form = new FormData();
    form.append("text", $("clonePreviewText").value);
    form.append("language", "Auto");
    form.append("ref_text", $("cloneRefText").value);
    form.append("ref_audio", file);
    const queued = await apiJson("/jobs/clone", { method: "POST", body: form });
    const job = await waitForJob(queued.job_id, $("clonePreview"), { queued: "排队中", running: "试音中" });
    showAudioSources(
      audioSourcesFromJob(job, `/jobs/${encodeURIComponent(job.job_id)}/audio`, job.filename || downloadFilename($("cloneName").value || "clone-preview", $("clonePreviewText").value)),
      "克隆试音",
      started,
    );
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy($("clonePreview"), false);
  }
}

async function designPayload() {
  return {
    name: $("designName").value,
    instruct: $("designInstruct").value,
    language: "Auto",
    temperature: parameterValue("design", "Temperature"),
    top_p: parameterValue("design", "TopP"),
  };
}

async function handleDesign(event) {
  event.preventDefault();
  const button = event.submitter;
  setBusy(button, true, "设计中...");
  const started = performance.now();
  try {
    const payload = await designPayload();
    const queued = await apiJson("/jobs/voices/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await waitForJob(queued.job_id, button, { queued: "排队中", running: "设计中" });
    await refreshVoices();
    state.selectedVoice = data.voice_id;
    renderVoices();
    showAudioSources(
      audioSourcesFromJob(data, data.audio_url || `/jobs/${encodeURIComponent(data.job_id)}/audio`, data.filename || downloadFilename(data.voice_id, DESIGN_REFERENCE_TEXT)),
      "设计结果",
      started,
    );
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(button, false);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const toolPanel = document.querySelector(".tool-panel");
  if (window.ResizeObserver && toolPanel) {
    new ResizeObserver(scheduleVoiceRailSync).observe(toolPanel);
  }
  window.addEventListener("resize", scheduleVoiceRailSync);
  document.querySelectorAll("select").forEach(enhanceSelect);
  document.querySelectorAll('input[type="number"]').forEach(enhanceNumberInput);
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".custom-select")) closeCustomSelects();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCustomSelects();
  });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  $("synthPane").addEventListener("submit", handleTts);
  $("segToggle").addEventListener("click", () => setSegmentedMode(!state.segmentedMode));
  $("segAdd").addEventListener("click", () => addSegment());
  $("clonePane").addEventListener("submit", handleClone);
  $("clonePreview").addEventListener("click", handleClonePreview);
  $("designPane").addEventListener("submit", handleDesign);
  document.querySelectorAll("[data-parameter-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const prefix = button.dataset.parameterToggle;
      const panel = document.querySelector(`[data-parameter-panel="${prefix}"]`);
      setParameterMode(prefix, !panel?.classList.contains("developer-mode"));
    });
  });
  $("refreshVoices").addEventListener("click", refreshVoices);
  $("libraryRefresh").addEventListener("click", refreshVoices);
  $("ttsVoice").addEventListener("change", (event) => {
    state.selectedVoice = event.target.value;
    renderVoices();
  });
  $("voiceTable").addEventListener("click", (event) => {
    const useId = event.target?.dataset?.use;
    if (useId) {
      const id = decodeURIComponent(useId);
      state.selectedVoice = id;
      $("ttsVoice").value = id;
      switchTab("synth");
      renderVoices();
      return;
    }
    const editId = event.target?.dataset?.edit;
    if (editId) {
      startRename(decodeURIComponent(editId));
      return;
    }
    const deleteId = event.target?.dataset?.delete;
    if (deleteId) {
      deleteVoice(decodeURIComponent(deleteId));
    }
  });
  $("voiceTable").addEventListener("keydown", (event) => {
    const encoded = event.target?.dataset?.nameFor;
    if (!encoded) return;
    if (event.key === "Enter") {
      event.preventDefault();
      event.target.blur();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.target.value = decodeURIComponent(encoded);
      event.target.blur();
    }
  });
  $("voiceTable").addEventListener("focusout", (event) => {
    const encoded = event.target?.dataset?.nameFor;
    if (!encoded) return;
    commitRename(decodeURIComponent(encoded));
  });
  $("playButton").addEventListener("click", async () => {
    const audio = activeAudio();
    if (!audio.src) {
      toast("请先生成一段语音");
      return;
    }
    if (audio.paused || audio.ended) {
      await audio.play();
      await syncShadowPlayback();
    } else {
      audioPlayers().forEach((item) => item.pause());
    }
    updatePlayerState();
  });
  $("mobileMicToggle").addEventListener("click", () => setMobileMicrophone(!state.mobileMicrophone));
  $("seekBar").addEventListener("input", (event) => {
    const audio = activeAudio();
    if (!audio.src || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const nextTime = (Number(event.target.value) / 1000) * audio.duration;
    audioPlayers().forEach((item) => {
      if (item.src) item.currentTime = nextTime;
    });
    updatePlayerState();
  });
  ["loadedmetadata", "timeupdate", "play", "pause", "ended", "durationchange"].forEach((name) => {
    audioPlayers().forEach((audio) => {
      audio.addEventListener(name, (event) => {
        if (event.target === activeAudio()) updatePlayerState();
        if (name === "ended" && event.target === activeAudio()) inactiveAudio()?.pause();
      });
    });
  });

  try {
    await setMobileMicrophone(false);
    await Promise.all([refreshHealth(), refreshVoices()]);
  } catch (err) {
    toast(err.message, true);
  }
});

function startRename(id) {
  const encoded = encodeURIComponent(id);
  const input = document.querySelector(`[data-name-for="${CSS.escape(encoded)}"]`);
  const row = input?.closest(".voice-row");
  if (!input || !row) return;
  row.classList.add("editing");
  input.value = id;
  input.focus();
  input.select();
}

async function commitRename(id) {
  const encoded = encodeURIComponent(id);
  const input = document.querySelector(`[data-name-for="${CSS.escape(encoded)}"]`);
  const row = input?.closest(".voice-row");
  if (!input || !row || !row.classList.contains("editing")) return;
  row.classList.remove("editing");
  const name = input.value.trim();
  if (!name || name === id) {
    input.value = id;
    return;
  }
  try {
    const data = await apiJson(`/voices/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    state.selectedVoice = data.voice_id;
    await refreshVoices();
    toast(`已重命名为 ${data.voice_id}`);
  } catch (err) {
    toast(err.message, true);
    await refreshVoices();
  }
}

async function deleteVoice(id) {
  if (!confirm(`删除音色「${id}」？`)) return;
  try {
    await apiJson(`/voices/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.selectedVoice === id) state.selectedVoice = "";
    await refreshVoices();
    toast(`已删除 ${id}`);
  } catch (err) {
    toast(err.message, true);
  }
}

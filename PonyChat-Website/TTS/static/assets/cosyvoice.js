const $ = (id) => document.getElementById(id);
const API_BASE = (document.body?.dataset?.apiBase || "/cosyvoice").replace(/\/+$/, "");

let voices = [];
let currentAudioUrl = "";
let currentJob = null;
let useMobileMic = false;
let segmented = false;
let selectedVoiceId = "";

function toast(message) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function apiForm(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    body: formData,
  });
  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function setMeta(text) {
  $("ttsMeta").textContent = text || "";
}

function setRunMeta(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function fmtTime(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function normalizeAudioUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_BASE}${url.startsWith("/cosyvoice/") ? url.slice("/cosyvoice".length) : url}`;
}

function renderVoices() {
  const select = $("ttsVoice");
  const list = $("voiceList");
  if (!selectedVoiceId || !voices.some((voice) => voice.id === selectedVoiceId)) {
    selectedVoiceId = voices[0]?.id || "";
  }
  select.innerHTML = "";
  list.innerHTML = "";
  voices.forEach((voice) => {
    const option = document.createElement("option");
    option.value = voice.id;
    option.textContent = `${voice.name || voice.id} (${voice.id})`;
    option.selected = voice.id === selectedVoiceId;
    select.append(option);

    const card = document.createElement("button");
    card.type = "button";
    card.className = "voice-item system-voice";
    card.innerHTML = `<strong>${voice.name || voice.id}</strong><span>${voice.description || voice.id}</span>`;
    card.addEventListener("click", () => {
      selectedVoiceId = voice.id;
      select.value = voice.id;
      renderVoices();
    });
    if (selectedVoiceId === voice.id) card.classList.add("active");
    list.append(card);
  });
  renderVoiceTable();
}

async function loadHealth() {
  try {
    const data = await api("/health");
    $("backendStatus").textContent = data.api_key_configured ? "已连接" : "缺少 API Key";
    $("speedStatus").textContent = data.model || "CosyVoice";
  } catch (error) {
    $("backendStatus").textContent = "连接失败";
    toast(error.message);
  }
}

async function loadVoices() {
  try {
    const data = await api("/speakers");
    voices = data.voices || data.speakers || [];
    renderVoices();
  } catch (error) {
    toast(error.message);
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.pane === name);
  });
}

function addSegment(text = "", instruct = "") {
  const row = document.createElement("div");
  row.className = "seg-row";
  row.innerHTML = `
    <label><span>文本</span><textarea rows="3">${text}</textarea></label>
    <label><span>风格</span><input type="text" value="${instruct}"></label>
    <button class="ghost-btn" type="button" aria-label="删除段落">删除</button>
  `;
  row.querySelector("button").addEventListener("click", () => row.remove());
  $("ttsSegments").append(row);
}

function setSegmented(next) {
  segmented = next;
  $("segToggle").setAttribute("aria-pressed", String(next));
  $("ttsSingleBlock").hidden = next;
  $("ttsSegmentsBlock").hidden = !next;
  if (next && !$("ttsSegments").querySelector(".seg-row")) {
    addSegment($("ttsText").value, $("ttsInstruct").value);
  }
}

function collectSegments() {
  return Array.from(document.querySelectorAll("#ttsSegments .seg-row")).map((row) => {
    const textarea = row.querySelector("textarea");
    const input = row.querySelector("input");
    return {
      text: textarea?.value || "",
      instruct: input?.value || "",
    };
  }).filter((segment) => segment.text.trim());
}

async function pollJob(jobId, metaId = "ttsMeta") {
  for (let i = 0; i < 240; i += 1) {
    const job = await api(`/jobs/${jobId}`);
    currentJob = job;
    if (job.status === "done") return job;
    if (job.status === "error") throw new Error(job.error || "生成失败");
    setRunMeta(metaId, job.status === "running" ? "生成中" : "排队中");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("生成超时");
}

function attachAudio(job) {
  currentAudioUrl = normalizeAudioUrl(job.audio_url || job.download_url);
  const audio = $("audioPlayer");
  audio.src = `${currentAudioUrl}?t=${Date.now()}`;
  audio.load();
  $("downloadLink").href = audio.src;
  $("downloadLink").download = job.filename || "cosyvoice.wav";
  $("downloadLink").classList.remove("disabled");
  $("outputTitle").textContent = useMobileMic ? "手机拾音模拟试听" : "官方原声试听";
  setMeta(job.usage?.characters ? `${job.usage.characters} 字符` : "完成");
}

async function runSynthesis(text, instruct = "", voiceId = selectedVoiceId, mobile = useMobileMic) {
  const queued = await api("/jobs/tts", {
    method: "POST",
    body: JSON.stringify({
      voice_id: voiceId || $("ttsVoice").value,
      format: "wav",
      sample_rate: 24000,
      mobile_microphone: mobile,
      text,
      instruct,
    }),
  });
  return pollJob(queued.job_id);
}

async function submitSynth(event) {
  event.preventDefault();
  setMeta("提交中");
  $("downloadLink").classList.add("disabled");
  try {
    const common = {
      voice_id: selectedVoiceId || $("ttsVoice").value,
      format: "wav",
      sample_rate: 24000,
      mobile_microphone: useMobileMic,
    };
    const queued = segmented
      ? await api("/jobs/tts/segmented", {
          method: "POST",
          body: JSON.stringify({ ...common, segments: collectSegments() }),
        })
      : await api("/jobs/tts", {
          method: "POST",
          body: JSON.stringify({
            ...common,
            text: $("ttsText").value,
            instruct: $("ttsInstruct").value,
          }),
        });
    const job = await pollJob(queued.job_id);
    attachAudio(job);
    $("audioPlayer").play().catch(() => {});
  } catch (error) {
    setMeta("");
    toast(error.message);
  }
}

async function submitClone(event) {
  event.preventDefault();
  setRunMeta("cloneMeta", "提交中");
  try {
    const file = $("cloneAudio").files[0];
    if (!file) throw new Error("请选择参考音频");
    const form = new FormData();
    form.append("name", $("cloneName").value || "ponyvoice");
    form.append("language", $("cloneLanguage").value || "zh");
    form.append("audio", file);
    const queued = await apiForm("/jobs/voices/clone", form);
    const job = await pollJob(queued.job_id, "cloneMeta");
    selectedVoiceId = job.voice_id;
    await loadVoices();
    setRunMeta("cloneMeta", `已创建 ${job.voice_id}`);
    const preview = $("clonePreviewText").value.trim();
    if (preview) {
      const audioJob = await runSynthesis(preview, "", job.voice_id, useMobileMic);
      attachAudio(audioJob);
      $("audioPlayer").play().catch(() => {});
    }
  } catch (error) {
    setRunMeta("cloneMeta", "");
    toast(error.message);
  }
}

async function submitDesign(event) {
  event.preventDefault();
  setRunMeta("designMeta", "提交中");
  try {
    const queued = await api("/jobs/voices/design", {
      method: "POST",
      body: JSON.stringify({
        name: $("designName").value || "narrator",
        voice_prompt: $("designPrompt").value,
        preview_text: $("designPreviewText").value,
      }),
    });
    const job = await pollJob(queued.job_id, "designMeta");
    selectedVoiceId = job.voice_id;
    await loadVoices();
    setRunMeta("designMeta", `已创建 ${job.voice_id}`);
    const preview = $("designPreviewText").value.trim();
    if (preview) {
      const audioJob = await runSynthesis(preview, "", job.voice_id, useMobileMic);
      attachAudio(audioJob);
      $("audioPlayer").play().catch(() => {});
    }
  } catch (error) {
    setRunMeta("designMeta", "");
    toast(error.message);
  }
}

function renderVoiceTable() {
  const table = $("voiceTable");
  if (!table) return;
  table.innerHTML = "";
  voices.forEach((voice) => {
    const row = document.createElement("div");
    row.className = "voice-row";
    row.innerHTML = `
      <div>
        <strong>${voice.name || voice.id}</strong>
        <span>${voice.id}</span>
      </div>
      <span>${voice.custom ? "自定义" : "系统"}</span>
      <button class="ghost-btn" type="button">${voice.custom ? "删除" : "保留"}</button>
    `;
    row.querySelector("button").disabled = !voice.custom;
    row.querySelector("button").addEventListener("click", async () => {
      try {
        await api(`/voices/${encodeURIComponent(voice.id)}`, { method: "DELETE" });
        if (selectedVoiceId === voice.id) selectedVoiceId = "";
        await loadVoices();
        toast("已删除音色");
      } catch (error) {
        toast(error.message);
      }
    });
    table.append(row);
  });
}

function bindPlayer() {
  const audio = $("audioPlayer");
  const play = $("playButton");
  const seek = $("seekBar");
  play.addEventListener("click", () => {
    if (!audio.src) return;
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  });
  audio.addEventListener("play", () => play.classList.add("playing"));
  audio.addEventListener("pause", () => play.classList.remove("playing"));
  audio.addEventListener("timeupdate", () => {
    $("currentTime").textContent = fmtTime(audio.currentTime);
    $("durationTime").textContent = fmtTime(audio.duration);
    seek.value = audio.duration ? Math.floor((audio.currentTime / audio.duration) * 1000) : 0;
  });
  seek.addEventListener("input", () => {
    if (audio.duration) audio.currentTime = (Number(seek.value) / 1000) * audio.duration;
  });
}

function init() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
  $("synthPane").addEventListener("submit", submitSynth);
  $("clonePane").addEventListener("submit", submitClone);
  $("designPane").addEventListener("submit", submitDesign);
  $("refreshVoices").addEventListener("click", loadVoices);
  $("libraryRefresh").addEventListener("click", loadVoices);
  $("segToggle").addEventListener("click", () => setSegmented(!segmented));
  $("segAdd").addEventListener("click", () => addSegment());
  $("ttsVoice").addEventListener("change", (event) => {
    selectedVoiceId = event.target.value;
    renderVoices();
  });
  $("mobileMicToggle").addEventListener("click", () => {
    useMobileMic = !useMobileMic;
    $("mobileMicToggle").setAttribute("aria-pressed", String(useMobileMic));
    toast(useMobileMic ? "网页试听将使用手机拾音模拟" : "网页试听将使用官方原声");
  });
  bindPlayer();
  loadHealth();
  loadVoices();
}

document.addEventListener("DOMContentLoaded", init);

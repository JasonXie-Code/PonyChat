const $ = (id) => document.getElementById(id);
const customSelects = new Set();
const state = {
  messages: [],          // {role, content, images?: [dataURL], reasoning?}
  pendingImages: [],     // dataURLs for next user message
  streaming: false,
  controller: null,
  model: "qwen3.6-27b",
  lastSpeed: 0,
  lastTotalTokens: 0,
  followBottom: true,
  programmaticScroll: false,
  userScrollIntentUntil: 0,
  lightbox: { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0, originX: 0, originY: 0 },
};

const SUGGESTIONS = [
  "用三句话解释什么是大语言模型。",
  "写一首关于小马驹和星空的短诗。",
  "写一段快速排序代码，并解释思路。",
  "（可上传一张图片）描述这张图片里的内容。",
];
const INPUT_PLACEHOLDER_DEFAULT = "给 Qwen3.6-27B 发消息…（回车发送，Shift+回车换行）";
const INPUT_PLACEHOLDER_STREAMING = "模型正在生成中...";
const IMAGE_MAX_DIMENSION = 1600;
const IMAGE_MAX_BYTES = 2.5 * 1024 * 1024;
const IMAGE_JPEG_QUALITY = 0.86;

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error-text", isError);
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 3200);
}

function formatTokenSpeed(value) {
  const n = Number.isFinite(value) ? Math.max(0, value) : 0;
  if (n >= 10) return String(Math.round(n));
  if (n >= 1) return n.toFixed(1).replace(/\.0$/, "");
  return String(Math.round(n));
}

function updateTokenStats(speed = state.lastSpeed, totalTokens = state.lastTotalTokens) {
  state.lastSpeed = Number.isFinite(speed) ? Math.max(0, speed) : state.lastSpeed;
  state.lastTotalTokens = Number.isFinite(totalTokens) ? Math.max(0, Math.round(totalTokens)) : state.lastTotalTokens;
  const chip = $("capsChip");
  if (chip) chip.textContent = `${formatTokenSpeed(state.lastSpeed)}Token/s ${state.lastTotalTokens}Tokens`;
}

function estimateTextTokens(text) {
  const s = String(text || "");
  if (!s) return 0;
  const cjk = (s.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  const nonCjk = Math.max(0, s.length - cjk);
  return Math.ceil(cjk * 1.15 + nonCjk / 3.8);
}

function estimateContentTokens(content) {
  if (Array.isArray(content)) {
    return content.reduce((sum, part) => {
      if (part?.type === "text") return sum + estimateTextTokens(part.text);
      if (part?.type === "image_url") return sum + 256;
      return sum;
    }, 0);
  }
  return estimateTextTokens(content);
}

function estimateApiMessagesTokens(messages) {
  return messages.reduce((sum, message) => sum + 4 + estimateContentTokens(message.content), 2);
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function compactWhitespace(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
}

function normalizeApiError(detail, status) {
  const raw = String(detail || "").trim();
  if (!raw) return `HTTP ${status}`;
  if (/^\s*</.test(raw)) {
    const doc = new DOMParser().parseFromString(raw, "text/html");
    const title = compactWhitespace(doc.querySelector("h1")?.textContent || doc.querySelector("title")?.textContent);
    if (/bad gateway/i.test(title) || status === 502) {
      return "502 Bad Gateway：LLM 后端暂时不可用或正在重启，请稍后重试。";
    }
    return title ? `HTTP ${status}：${title}` : `HTTP ${status}`;
  }
  if (/Bad Gateway/i.test(raw) || status === 502) {
    return "502 Bad Gateway：LLM 后端暂时不可用或正在重启，请稍后重试。";
  }
  return raw.length > 600 ? `${raw.slice(0, 600)}...` : raw;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("读取图片失败"));
    reader.readAsDataURL(file);
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片解码失败"));
    img.src = src;
  });
}

async function prepareImageDataUrl(file) {
  const original = await readFileAsDataUrl(file);
  if (!/^image\/(?:png|jpe?g|webp)$/i.test(file.type)) return original;

  const img = await loadImage(original);
  const maxSide = Math.max(img.naturalWidth || img.width, img.naturalHeight || img.height);
  if (file.size <= IMAGE_MAX_BYTES && maxSide <= IMAGE_MAX_DIMENSION) return original;

  const scale = Math.min(1, IMAGE_MAX_DIMENSION / Math.max(1, maxSide));
  const width = Math.max(1, Math.round((img.naturalWidth || img.width) * scale));
  const height = Math.max(1, Math.round((img.naturalHeight || img.height) * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0, width, height);
  return canvas.toDataURL("image/jpeg", IMAGE_JPEG_QUALITY);
}

const MARKDOWN_ALLOWED_TAGS = new Set([
  "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6",
  "hr", "img", "input", "li", "ol", "p", "pre", "s", "span", "strong", "table",
  "tbody", "td", "th", "thead", "tr", "ul",
]);
const MARKDOWN_DROP_TAGS = new Set(["script", "style", "iframe", "object", "embed", "link", "meta"]);

function isSafeMarkdownUrl(value, allowImageData = false) {
  const url = String(value || "").trim();
  if (!url) return false;
  if (url.startsWith("#") || url.startsWith("/") || url.startsWith("./") || url.startsWith("../")) return true;
  if (allowImageData && /^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(url)) return true;
  try {
    const parsed = new URL(url, window.location.href);
    return ["http:", "https:", "mailto:", "tel:"].includes(parsed.protocol);
  } catch (_) {
    return false;
  }
}

function sanitizeMarkdownHtml(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const root = doc.body.firstElementChild;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  for (const el of nodes) {
    const tag = el.tagName.toLowerCase();
    if (MARKDOWN_DROP_TAGS.has(tag)) {
      el.remove();
      continue;
    }
    if (!MARKDOWN_ALLOWED_TAGS.has(tag)) {
      el.replaceWith(...Array.from(el.childNodes));
      continue;
    }

    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value;
      let keep = false;
      if (tag === "a" && ["href", "title"].includes(name)) keep = name !== "href" || isSafeMarkdownUrl(value);
      if (tag === "img" && ["src", "alt", "title"].includes(name)) keep = name !== "src" || isSafeMarkdownUrl(value, true);
      if (tag === "code" && name === "class") keep = /^language-[a-z0-9_+-]+$/i.test(value);
      if (tag === "pre" && name === "data-lang") keep = /^[\w#+.-]{1,24}$/.test(value);
      if (tag === "input" && ["type", "checked", "disabled"].includes(name)) keep = true;
      if (!keep) el.removeAttribute(attr.name);
    }

    if (tag === "a" && el.hasAttribute("href")) {
      el.setAttribute("target", "_blank");
      el.setAttribute("rel", "noopener noreferrer");
    }
    if (tag === "img") {
      el.setAttribute("loading", "lazy");
      el.setAttribute("decoding", "async");
    }
    if (tag === "input") {
      if (el.getAttribute("type") !== "checkbox") el.remove();
      else el.setAttribute("disabled", "");
    }
  }
  return root.innerHTML;
}

function enhanceMarkdownHtml(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const root = doc.body.firstElementChild;
  root.querySelectorAll("pre > code").forEach((code) => {
    const cls = code.getAttribute("class") || "";
    const lang = (cls.match(/language-([\w#+.-]+)/i)?.[1] || "代码").slice(0, 24);
    const pre = code.parentElement;
    pre.setAttribute("data-lang", lang);
    if (!pre.querySelector(".copy-code-btn")) {
      const btn = doc.createElement("button");
      btn.type = "button";
      btn.className = "copy-code-btn";
      btn.textContent = "复制";
      pre.insertBefore(btn, code);
    }
  });
  return root.innerHTML;
}

function protectMathSegments(text) {
  const source = String(text);
  const segments = [];
  let out = "";
  let i = 0;
  const tokenFor = (value) => {
    const token = `@@PONY_MATH_${segments.length}@@`;
    segments.push({ token, value });
    return token;
  };

  while (i < source.length) {
    if (source.startsWith("```", i)) {
      const end = source.indexOf("```", i + 3);
      const next = end >= 0 ? end + 3 : source.length;
      out += source.slice(i, next);
      i = next;
      continue;
    }
    if (source[i] === "`") {
      const end = source.indexOf("`", i + 1);
      const next = end >= 0 ? end + 1 : source.length;
      out += source.slice(i, next);
      i = next;
      continue;
    }

    const candidates = [
      ["\\begin{equation*}", "\\end{equation*}"],
      ["\\begin{equation}", "\\end{equation}"],
      ["\\begin{align*}", "\\end{align*}"],
      ["\\begin{align}", "\\end{align}"],
      ["\\begin{aligned}", "\\end{aligned}"],
      ["\\begin{gather*}", "\\end{gather*}"],
      ["\\begin{gather}", "\\end{gather}"],
      ["\\begin{matrix}", "\\end{matrix}"],
      ["\\begin{pmatrix}", "\\end{pmatrix}"],
      ["\\begin{bmatrix}", "\\end{bmatrix}"],
      ["$$", "$$"],
      ["\\[", "\\]"],
      ["\\(", "\\)"],
      ["$", "$"],
    ];
    let matched = false;
    for (const [left, right] of candidates) {
      if (!source.startsWith(left, i)) continue;
      if (left === "$") {
        const prev = source[i - 1] || "";
        const nextChar = source[i + 1] || "";
        if (/\s|\d/.test(nextChar) || /[\w)]/.test(prev)) continue;
      }
      const end = source.indexOf(right, i + left.length);
      if (end < 0) continue;
      if (left === "$" && /\s/.test(source[end - 1] || "")) continue;
      const value = source.slice(i, end + right.length);
      out += tokenFor(value);
      i = end + right.length;
      matched = true;
      break;
    }
    if (!matched) {
      out += source[i];
      i += 1;
    }
  }
  return { text: out, segments };
}

function restoreMathSegments(html, segments) {
  let out = html;
  for (const item of segments) {
    out = out.split(item.token).join(escapeHtml(item.value));
  }
  return out;
}

function repairInlineEmphasisHtml(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const root = doc.body.firstElementChild;
  const skipTags = new Set(["code", "pre", "script", "style", "textarea", "option"]);
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  for (const node of nodes) {
    let parent = node.parentElement;
    let skip = false;
    while (parent && parent !== root) {
      if (skipTags.has(parent.tagName.toLowerCase())) {
        skip = true;
        break;
      }
      parent = parent.parentElement;
    }
    if (skip) continue;

    const text = node.nodeValue || "";
    const re = /(\*\*|__|~~)([^\n]+?)\1/g;
    if (!re.test(text)) continue;
    re.lastIndex = 0;

    const frag = doc.createDocumentFragment();
    let last = 0;
    for (const match of text.matchAll(re)) {
      const index = match.index || 0;
      if (index > last) frag.appendChild(doc.createTextNode(text.slice(last, index)));
      const tag = match[1] === "~~" ? "del" : "strong";
      const el = doc.createElement(tag);
      el.textContent = match[2].trim();
      frag.appendChild(el);
      last = index + match[0].length;
    }
    if (last < text.length) frag.appendChild(doc.createTextNode(text.slice(last)));
    node.replaceWith(frag);
  }
  return root.innerHTML;
}

function normalizeMarkdownEmphasisSegment(segment) {
  const quotePairs = {
    "\"": "\"",
    "'": "'",
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
  };
  const inlineSpace = "[^\\S\\r\\n]";
  const trimInlineSpaceInside = (marker, bodyPattern) => new RegExp(
    `${marker}${inlineSpace}*(${bodyPattern}*?\\S)${inlineSpace}*${marker}`,
    "g"
  );
  let out = segment;
  out = out.replace(trimInlineSpaceInside("\\*\\*", "[^*\\n]"), "**$1**");
  out = out.replace(trimInlineSpaceInside("__", "[^_\\n]"), "__$1__");
  out = out.replace(trimInlineSpaceInside("~~", "[^~\\n]"), "~~$1~~");
  out = out.replace(/^([ \t]{0,3}#{1,6})([^\s#])/gm, "$1 $2");
  out = out.replace(/^([ \t]*[-+*])([^\s*-])/gm, "$1 $2");
  out = out.replace(/^([ \t]*\d{1,9}[.)])([^\s])/gm, "$1 $2");
  out = out.replace(/^([ \t]*>)([^\s>])/gm, "$1 $2");
  return out.replace(/\*\*([“‘「『"'])([^*\n]+?)([”’」』"'])\*\*/g, (match, open, body, close) => {
    if (quotePairs[open] !== close) return match;
    return `${open}**${body.trim()}**${close}`;
  });
}

function normalizeMarkdownText(text) {
  const source = String(text);
  let out = "";
  let i = 0;
  while (i < source.length) {
    if (source.startsWith("```", i)) {
      const end = source.indexOf("```", i + 3);
      const next = end >= 0 ? end + 3 : source.length;
      out += source.slice(i, next);
      i = next;
      continue;
    }
    if (source[i] === "`") {
      const end = source.indexOf("`", i + 1);
      const next = end >= 0 ? end + 1 : source.length;
      out += source.slice(i, next);
      i = next;
      continue;
    }
    let nextSpecial = source.length;
    const nextFence = source.indexOf("```", i);
    const nextCode = source.indexOf("`", i);
    if (nextFence >= 0) nextSpecial = Math.min(nextSpecial, nextFence);
    if (nextCode >= 0) nextSpecial = Math.min(nextSpecial, nextCode);
    out += normalizeMarkdownEmphasisSegment(source.slice(i, nextSpecial));
    i = nextSpecial;
  }
  return out;
}

// Markdown rendering with GFM support when marked is available, with a local safe fallback.
function renderMarkdown(text) {
  const math = protectMathSegments(normalizeMarkdownText(text));
  if (window.marked?.parse) {
    const raw = window.marked.parse(math.text, {
      async: false,
      breaks: true,
      gfm: true,
      mangle: false,
      headerIds: false,
    });
    return restoreMathSegments(enhanceMarkdownHtml(repairInlineEmphasisHtml(sanitizeMarkdownHtml(raw))), math.segments);
  }

  const parts = math.text.split(/```/);
  let html = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      let lang = "";
      const seg = parts[i].replace(/^[^\n]*\n/, (m) => {
        const head = m.trim();
        if (/^[a-zA-Z0-9+#.-]*\s*$/.test(head)) {
          lang = head;
          return "";
        }
        return m;
      });
      const cls = lang ? ` class="language-${escapeHtml(lang)}"` : "";
      html += `<pre data-lang="${escapeHtml(lang || "代码")}"><button type="button" class="copy-code-btn">复制</button><code${cls}>${escapeHtml(seg.replace(/\n$/, ""))}</code></pre>`;
    } else {
      let seg = escapeHtml(parts[i]);
      seg = seg.replace(/`([^`]+)`/g, "<code>$1</code>");
      seg = seg.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      seg = seg.split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
      html += seg;
    }
  }
  return restoreMathSegments(repairInlineEmphasisHtml(html), math.segments);
}

function renderMathInMarkdown(el) {
  if (!el || !window.renderMathInElement) return;
  window.renderMathInElement(el, {
    delimiters: [
      { left: "\\begin{equation*}", right: "\\end{equation*}", display: true },
      { left: "\\begin{equation}", right: "\\end{equation}", display: true },
      { left: "\\begin{align*}", right: "\\end{align*}", display: true },
      { left: "\\begin{align}", right: "\\end{align}", display: true },
      { left: "\\begin{aligned}", right: "\\end{aligned}", display: true },
      { left: "\\begin{gather*}", right: "\\end{gather*}", display: true },
      { left: "\\begin{gather}", right: "\\end{gather}", display: true },
      { left: "\\begin{matrix}", right: "\\end{matrix}", display: true },
      { left: "\\begin{pmatrix}", right: "\\end{pmatrix}", display: true },
      { left: "\\begin{bmatrix}", right: "\\end{bmatrix}", display: true },
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "\\(", right: "\\)", display: false },
      { left: "$", right: "$", display: false },
    ],
    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
    ignoredClasses: ["think-body"],
    throwOnError: false,
    errorColor: "#ef6f85",
  });
}

function setMarkdown(el, text, options = {}) {
  el.innerHTML = renderMarkdown(text);
  if (options.math !== false) renderMathInMarkdown(el);
}

function scrollToBottom(force = false) {
  const m = $("messages");
  if (force) state.followBottom = true;
  if (force || state.followBottom) {
    state.programmaticScroll = true;
    const pin = () => { m.scrollTop = m.scrollHeight; };
    pin();
    requestAnimationFrame(() => {
      pin();
      requestAnimationFrame(() => {
        pin();
        state.programmaticScroll = false;
        const nextGap = m.scrollHeight - m.scrollTop - m.clientHeight;
        state.followBottom = nextGap <= 24;
      });
    });
  }
}

function bindMessageScrollFollow() {
  const m = $("messages");
  const markUserScrollIntent = () => {
    state.followBottom = false;
    state.userScrollIntentUntil = performance.now() + 900;
  };
  m.addEventListener("wheel", markUserScrollIntent, { passive: true });
  m.addEventListener("touchstart", markUserScrollIntent, { passive: true });
  m.addEventListener("pointerdown", markUserScrollIntent);
  m.addEventListener("keydown", (e) => {
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(e.key)) markUserScrollIntent();
  });
  m.addEventListener("scroll", () => {
    if (state.programmaticScroll && performance.now() > state.userScrollIntentUntil) return;
    const gap = m.scrollHeight - m.scrollTop - m.clientHeight;
    state.followBottom = gap <= 24;
  }, { passive: true });
}

function scrollReasoningToBottom(ui, force = false) {
  if (!ui || !ui.thinkBody) return;
  if (!force && ui.reasoningUserScrolled) return;
  ui.reasoningAutoScrolling = true;
  const pin = () => { ui.thinkBody.scrollTop = ui.thinkBody.scrollHeight; };
  pin();
  requestAnimationFrame(() => {
    pin();
    requestAnimationFrame(() => {
      pin();
      ui.reasoningAutoScrolling = false;
      const gap = ui.thinkBody.scrollHeight - ui.thinkBody.scrollTop - ui.thinkBody.clientHeight;
      ui.reasoningUserScrolled = gap > 32;
    });
  });
}

function bindReasoningScrollLock(ui) {
  const body = ui.thinkBody;
  const syncFollow = () => {
    if (ui.reasoningAutoScrolling) return;
    const gap = body.scrollHeight - body.scrollTop - body.clientHeight;
    ui.reasoningUserScrolled = gap > 32;
  };
  const syncAfterInput = () => requestAnimationFrame(syncFollow);
  body.addEventListener("scroll", syncFollow, { passive: true });
  body.addEventListener("wheel", syncAfterInput, { passive: true });
  body.addEventListener("touchstart", syncAfterInput, { passive: true });
  body.addEventListener("pointerdown", syncAfterInput);
  body.addEventListener("keydown", syncAfterInput);
}

function renderWelcome() {
  const m = $("messages");
  m.innerHTML = "";
  state.followBottom = true;
  const wrap = document.createElement("div");
  wrap.className = "welcome";
  wrap.innerHTML = `
    <img class="w-logo" src="/logo/logoBK512.png" alt="">
    <h2>PonyChat 大模型</h2>
    <p>由 Qwen3.6-27B 本地模型驱动，支持多轮对话、图片视觉理解与推理过程展示。</p>
    <div class="suggestions"></div>`;
  const sg = wrap.querySelector(".suggestions");
  SUGGESTIONS.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "suggestion";
    b.textContent = t;
    b.addEventListener("click", () => { $("input").value = t.replace(/^（[^）]*）/, ""); $("input").focus(); autoGrow(); });
    sg.appendChild(b);
  });
  m.appendChild(wrap);
}

function avatarEl(role) {
  const a = document.createElement("div");
  a.className = "avatar";
  if (role === "assistant") {
    const img = document.createElement("img");
    img.src = "/logo/logoBK512.png";
    img.alt = "AI";
    a.appendChild(img);
  } else {
    a.textContent = "我";
  }
  return a;
}

function addMessageNode(role) {
  if ($("messages").querySelector(".welcome")) $("messages").innerHTML = "";
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  msg.appendChild(avatarEl(role));
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  msg.appendChild(bubble);
  $("messages").appendChild(msg);
  return bubble;
}

function renderUserMessage(text, images) {
  const bubble = addMessageNode("user");
  if (images && images.length) {
    bubble.classList.add("has-images");
    const row = document.createElement("div");
    row.className = "msg-images";
    images.forEach((src, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "msg-image-btn";
      btn.setAttribute("aria-label", `查看第 ${idx + 1} 张图片`);
      btn.dataset.src = src;
      const im = document.createElement("img");
      im.src = src;
      im.alt = `已发送图片 ${idx + 1}`;
      im.loading = "lazy";
      btn.appendChild(im);
      row.appendChild(btn);
    });
    bubble.appendChild(row);
  }
  if (text) {
    const md = document.createElement("div");
    md.className = "md";
    setMarkdown(md, text);
    bubble.appendChild(md);
  }
  scrollToBottom(true);
}

function createAssistantBubble() {
  const bubble = addMessageNode("assistant");
  const think = document.createElement("details");
  think.className = "think";
  think.open = true;
  think.hidden = true;
  think.innerHTML = `<summary>思考中…</summary><div class="think-body"></div>`;
  const md = document.createElement("div");
  md.className = "md cursor-blink";
  bubble.appendChild(think);
  bubble.appendChild(md);
  const ui = {
    bubble,
    think,
    thinkBody: think.querySelector(".think-body"),
    summary: think.querySelector("summary"),
    md,
    reasoningUserScrolled: false,
    reasoningAutoScrolling: false,
    reasoningFinalized: false,
  };
  bindReasoningScrollLock(ui);
  return ui;
}

function finalizeReasoning(ui) {
  if (!ui || ui.reasoningFinalized) return;
  ui.summary.textContent = "已思考";
  ui.think.open = false;
  ui.reasoningFinalized = true;
}

async function loadModel() {
  try {
    const res = await fetch("/v1/models");
    if (!res.ok) throw new Error();
    const data = await res.json();
    const item = (data.data && data.data[0]) || (data.models && data.models[0]);
    if (item) {
      state.model = item.id || item.name || state.model;
      $("modelChip").textContent = state.model;
      updateTokenStats();
      $("modelStatus").textContent = state.model;
    }
  } catch (_) { /* ignore */ }
}

async function pollHealth() {
  try {
    const res = await fetch("/health");
    const ok = res.ok;
    $("connStatus").classList.toggle("online", ok);
    $("connStatus").classList.toggle("offline", !ok);
    $("connStatus").textContent = ok ? "在线" : "离线";
  } catch (_) {
    $("connStatus").classList.add("offline");
    $("connStatus").textContent = "离线";
  }
}

function buildApiMessages() {
  const out = [];
  const sys = $("systemPrompt").value.trim();
  if (sys) out.push({ role: "system", content: sys });
  for (const m of state.messages) {
    if (m.role === "user" && m.images && m.images.length) {
      const content = [];
      if (m.content) content.push({ type: "text", text: m.content });
      m.images.forEach((url) => content.push({ type: "image_url", image_url: { url } }));
      out.push({ role: "user", content });
    } else {
      out.push({ role: m.role, content: m.content });
    }
  }
  return out;
}

function setStreaming(on) {
  state.streaming = on;
  $("sendBtn").hidden = on;
  $("stopBtn").hidden = !on;
  const input = $("input");
  input.disabled = on;
  input.placeholder = on ? INPUT_PLACEHOLDER_STREAMING : INPUT_PLACEHOLDER_DEFAULT;
}

async function sendMessage() {
  if (state.streaming) return;
  const text = $("input").value.trim();
  const images = state.pendingImages.slice();
  if (!text && !images.length) return;

  state.messages.push({ role: "user", content: text, images });
  renderUserMessage(text, images);
  $("input").value = "";
  state.pendingImages = [];
  renderAttachments();
  resetInputHeight();

  const ui = createAssistantBubble();
  scrollToBottom(true);
  setStreaming(true);
  state.controller = new AbortController();

  const thinkingOn = $("thinking").value === "on";
  const apiMessages = buildApiMessages();
  const estimatedPromptTokens = estimateApiMessagesTokens(apiMessages);
  let generatedTokens = 0;
  let tokenWindow = [];
  let lastLiveSpeed = state.lastSpeed;
  const refreshLiveStats = (speed = lastLiveSpeed, total = estimatedPromptTokens + generatedTokens) => {
    lastLiveSpeed = speed;
    updateTokenStats(speed, total);
  };
  const noteGeneratedToken = () => {
    const now = performance.now();
    generatedTokens += 1;
    tokenWindow.push(now);
    tokenWindow = tokenWindow.filter((t) => now - t <= 3000);
    const elapsed = tokenWindow.length > 1 ? Math.max(0.25, (now - tokenWindow[0]) / 1000) : 1;
    refreshLiveStats(tokenWindow.length / elapsed);
  };
  refreshLiveStats(0, estimatedPromptTokens);
  const body = {
    model: state.model,
    messages: apiMessages,
    temperature: Number($("temperature").value),
    top_p: Number($("topP").value),
    max_tokens: Number($("maxTokens").value),
    stream: true,
    stream_options: { include_usage: true },
    chat_template_kwargs: { enable_thinking: thinkingOn },
  };

  let contentBuf = "";
  let thinkBuf = "";
  let renderedContent = "";
  let contentRenderTimer = null;
  const t0 = performance.now();
  const contentRenderDelay = () => {
    if (contentBuf.length > 24000) return 850;
    if (contentBuf.length > 10000) return 520;
    if (contentBuf.length > 3500) return 260;
    return 100;
  };
  const renderContent = (final = false) => {
    if (contentRenderTimer) {
      clearTimeout(contentRenderTimer);
      contentRenderTimer = null;
    }
    if (!final && renderedContent === contentBuf) return;
    renderedContent = contentBuf;
    setMarkdown(ui.md, contentBuf, { math: final || contentBuf.length < 7000 });
    scrollToBottom();
  };
  const scheduleContentRender = () => {
    if (contentRenderTimer) return;
    contentRenderTimer = setTimeout(() => {
      contentRenderTimer = null;
      requestAnimationFrame(() => renderContent(false));
    }, contentRenderDelay());
  };
  try {
    const res = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: state.controller.signal,
    });
    if (!res.ok) {
      let detail = await res.text();
      try { detail = JSON.parse(detail).error?.message || detail; } catch (_) {}
      throw new Error(normalizeApiError(detail, res.status));
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        const s = line.trim();
        if (!s.startsWith("data:")) continue;
        const payload = s.slice(5).trim();
        if (payload === "[DONE]") continue;
        let json;
        try { json = JSON.parse(payload); } catch (_) { continue; }
        if (json.usage?.total_tokens) refreshLiveStats(lastLiveSpeed, json.usage.total_tokens);
        const delta = json.choices?.[0]?.delta || {};
        if (delta.reasoning_content) {
          noteGeneratedToken();
          thinkBuf += delta.reasoning_content;
          ui.think.hidden = false;
          ui.thinkBody.textContent = thinkBuf;
          scrollReasoningToBottom(ui);
        }
        if (delta.content) {
          noteGeneratedToken();
          if (thinkBuf) finalizeReasoning(ui);
          contentBuf += delta.content;
          scheduleContentRender();
        }
        scrollToBottom();
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      contentBuf += contentBuf ? "\n\n_(已停止)_" : "_(已停止)_";
    } else {
      setMarkdown(ui.md, contentBuf || "");
      toast("生成失败：" + err.message, true);
      ui.md.insertAdjacentHTML("beforeend", `<p class="error-text">⚠ ${escapeHtml(err.message)}</p>`);
    }
  } finally {
    if (contentRenderTimer) {
      clearTimeout(contentRenderTimer);
      contentRenderTimer = null;
    }
    ui.md.classList.remove("cursor-blink");
    if (thinkBuf && !ui.reasoningFinalized) finalizeReasoning(ui);
    if (contentBuf) {
      renderContent(true);
    } else {
      setMarkdown(ui.md, thinkBuf ? "" : "（无输出）");
    }
    if (contentBuf || thinkBuf) {
      state.messages.push({ role: "assistant", content: contentBuf, reasoning: thinkBuf });
    }
    setStreaming(false);
    state.controller = null;
    scrollToBottom();
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    if (contentBuf) toast(`完成，用时 ${secs}s`);
  }
}

function renderAttachments() {
  const row = $("attachRow");
  row.innerHTML = "";
  if (!state.pendingImages.length) { row.hidden = true; return; }
  row.hidden = false;
  state.pendingImages.forEach((src, idx) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    chip.innerHTML = `<img src="${src}" alt=""><button type="button" title="移除">×</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pendingImages.splice(idx, 1);
      renderAttachments();
    });
    row.appendChild(chip);
  });
}

function handleImageFiles(files) {
  Array.from(files).forEach(async (file) => {
    if (!file.type.startsWith("image/")) return;
    try {
      const src = await prepareImageDataUrl(file);
      state.pendingImages.push(src);
      renderAttachments();
      if (file.size > IMAGE_MAX_BYTES) toast("图片已压缩后上传");
    } catch (err) {
      toast(err.message || "图片处理失败", true);
    }
  });
}

function autoGrow() {
  const ta = $("input");
  const min = 34;
  const max = 126;
  ta.style.height = "auto";
  const next = Math.min(Math.max(ta.scrollHeight, min), max);
  ta.style.height = `${next}px`;
  ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
}

function resetInputHeight() {
  const ta = $("input");
  ta.style.height = "34px";
  ta.style.overflowY = "hidden";
}

async function copyCodeFromButton(btn) {
  const code = btn.closest("pre")?.querySelector("code");
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code.innerText);
    const old = btn.textContent;
    btn.textContent = "已复制";
    setTimeout(() => { btn.textContent = old; }, 1200);
  } catch (_) {
    toast("复制失败，请手动选择代码", true);
  }
}

function imageExtFromDataUrl(src) {
  const mime = String(src).match(/^data:image\/([^;,]+)/i)?.[1] || "png";
  if (mime === "jpeg") return "jpg";
  if (/^[a-z0-9]+$/i.test(mime)) return mime.toLowerCase();
  return "png";
}

function applyLightboxTransform(box = $("imageLightbox")) {
  if (!box) return;
  const img = box.querySelector(".lightbox-img");
  const { scale, x, y } = state.lightbox;
  img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  box.classList.toggle("is-zoomed", scale > 1.01);
}

function resetLightboxTransform(box = $("imageLightbox")) {
  state.lightbox = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0, originX: 0, originY: 0 };
  applyLightboxTransform(box);
}

function zoomLightbox(delta, clientX, clientY) {
  const box = $("imageLightbox");
  if (!box || box.hidden) return;
  const stage = box.querySelector(".lightbox-stage");
  const oldScale = state.lightbox.scale;
  const nextScale = Math.min(8, Math.max(0.35, oldScale * (delta < 0 ? 1.12 : 0.88)));
  if (Math.abs(nextScale - oldScale) < 0.001) return;
  const rect = stage.getBoundingClientRect();
  const cx = clientX - rect.left - rect.width / 2;
  const cy = clientY - rect.top - rect.height / 2;
  const ratio = nextScale / oldScale;
  state.lightbox.x = cx - (cx - state.lightbox.x) * ratio;
  state.lightbox.y = cy - (cy - state.lightbox.y) * ratio;
  state.lightbox.scale = nextScale;
  applyLightboxTransform(box);
}

function ensureLightbox() {
  let box = $("imageLightbox");
  if (box) return box;
  box = document.createElement("div");
  box.id = "imageLightbox";
  box.className = "image-lightbox";
  box.hidden = true;
  box.innerHTML = `
    <div class="lightbox-backdrop" data-close="true"></div>
    <div class="lightbox-panel" role="dialog" aria-modal="true" aria-label="图片预览">
      <div class="lightbox-stage" data-close="true">
        <img class="lightbox-img" alt="图片预览" draggable="false">
      </div>
      <a class="lightbox-download" download="ponychat-image.png">下载</a>
    </div>`;
  box.addEventListener("click", (e) => {
    if (e.target.closest(".lightbox-img, .lightbox-download")) return;
    closeImageLightbox();
  });
  const stage = box.querySelector(".lightbox-stage");
  const img = box.querySelector(".lightbox-img");
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomLightbox(e.deltaY, e.clientX, e.clientY);
  }, { passive: false });
  img.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    state.lightbox.dragging = true;
    state.lightbox.startX = e.clientX;
    state.lightbox.startY = e.clientY;
    state.lightbox.originX = state.lightbox.x;
    state.lightbox.originY = state.lightbox.y;
    img.setPointerCapture?.(e.pointerId);
    box.classList.add("is-dragging");
  });
  img.addEventListener("pointermove", (e) => {
    if (!state.lightbox.dragging) return;
    e.preventDefault();
    state.lightbox.x = state.lightbox.originX + e.clientX - state.lightbox.startX;
    state.lightbox.y = state.lightbox.originY + e.clientY - state.lightbox.startY;
    applyLightboxTransform(box);
  });
  const endDrag = (e) => {
    if (!state.lightbox.dragging) return;
    state.lightbox.dragging = false;
    img.releasePointerCapture?.(e.pointerId);
    box.classList.remove("is-dragging");
  };
  img.addEventListener("pointerup", endDrag);
  img.addEventListener("pointercancel", endDrag);
  img.addEventListener("dblclick", (e) => {
    e.preventDefault();
    if (state.lightbox.scale > 1.01) resetLightboxTransform(box);
    else zoomLightbox(-1, e.clientX, e.clientY);
  });
  document.body.appendChild(box);
  return box;
}

function openImageLightbox(src) {
  const box = ensureLightbox();
  const img = box.querySelector(".lightbox-img");
  const download = box.querySelector(".lightbox-download");
  img.src = src;
  download.href = src;
  download.download = `ponychat-image.${imageExtFromDataUrl(src)}`;
  box.hidden = false;
  document.body.classList.add("lightbox-open");
  resetLightboxTransform(box);
  img.onload = () => resetLightboxTransform(box);
  download.focus();
}

function closeImageLightbox() {
  const box = $("imageLightbox");
  if (!box) return;
  box.hidden = true;
  box.querySelector(".lightbox-img").removeAttribute("src");
  resetLightboxTransform(box);
  document.body.classList.remove("lightbox-open");
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
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
    item.textContent = option.textContent;
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
  button.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      closeCustomSelects(root);
      root.classList.add("open");
      button.setAttribute("aria-expanded", "true");
      apiFocusSelected(select);
    }
  });
  select.addEventListener("change", () => refreshCustomSelect(select));
  refreshCustomSelect(select);
}

function apiFocusSelected(select) {
  const api = select?._customSelect;
  if (!api) return;
  const selected = api.menu.querySelector(".custom-select-option.selected");
  (selected || api.menu.querySelector(".custom-select-option"))?.focus();
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

function newChat() {
  if (state.streaming && state.controller) state.controller.abort();
  state.messages = [];
  state.pendingImages = [];
  updateTokenStats(0, 0);
  renderAttachments();
  renderWelcome();
}

document.addEventListener("DOMContentLoaded", () => {
  renderWelcome();
  updateTokenStats(0, 0);
  bindMessageScrollFollow();
  document.querySelectorAll("select").forEach(enhanceSelect);
  document.querySelectorAll('input[type="number"]').forEach(enhanceNumberInput);
  loadModel();
  pollHealth();
  setInterval(pollHealth, 15000);
  resetInputHeight();

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
  $("messages").addEventListener("click", (e) => {
    const btn = e.target.closest?.(".copy-code-btn");
    if (btn) {
      copyCodeFromButton(btn);
      return;
    }
    const imageBtn = e.target.closest?.(".msg-image-btn");
    if (imageBtn?.dataset.src) openImageLightbox(imageBtn.dataset.src);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeImageLightbox(); });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".custom-select")) closeCustomSelects();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCustomSelects();
  });
  $("stopBtn").addEventListener("click", () => { if (state.controller) state.controller.abort(); });
  $("newChat").addEventListener("click", newChat);
  $("settingsToggle").addEventListener("click", () => {
    const p = $("settingsPanel");
    const show = p.hidden;
    p.hidden = !show;
    $("settingsToggle").setAttribute("aria-pressed", show ? "true" : "false");
  });
  $("imageInput").addEventListener("change", (e) => { handleImageFiles(e.target.files); e.target.value = ""; });
  const ta = $("input");
  ta.addEventListener("input", autoGrow);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); }
  });
  ta.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items || [];
    for (const it of items) { if (it.type.startsWith("image/")) { handleImageFiles([it.getAsFile()]); } }
  });
});

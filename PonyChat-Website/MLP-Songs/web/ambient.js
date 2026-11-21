/* Body-color swatches sampled from media-export/covers/season-08-2018a/Cover.jpg. */
(function () {
  "use strict";
  const panel = document.querySelector("#nowPlaying"), layer = document.querySelector("#playerAmbient"), audio = document.querySelector("#audio");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const coats = {
    "暮光闪闪": "#cd9ee2", "碧琪": "#f1a9c6", "柔柔": "#fef6a3", "云宝黛茜": "#9adaf5", "苹果嘉儿": "#fbb961", "珍奇": "#dee2e5",
    "星光熠熠": "#f1c7f9", "斯派克": "#c190c7", "加鲁斯": "#31afd7", "银溪": "#f9defd", "约娜": "#9d675b", "暗焰": "#e49c26"
  };
  const aliases = {"云宝": "云宝黛茜", "人类云宝": "云宝黛茜", "小蝶": "柔柔", "萍琪派": "碧琪", "瑞瑞": "珍奇", "苹果杰克": "苹果嘉儿"};
  const mainCast = ["暮光闪闪", "碧琪", "柔柔", "云宝黛茜", "苹果嘉儿", "珍奇"];
  const coverPalettes = new Map();
  const coverColorCount = 4;
  let lights = [], songId = null, cover = "", generation = 0, enabled = true;
  const random = (min, max) => min + Math.random() * (max - min);
  const point = () => ({x: random(-42, 42), y: random(-32, 32), scale: random(.9, 1.15)});
  const transform = (p) => `translate3d(${p.x}vw, ${p.y}vh, 0) scale(${p.scale})`;
  function palette(characters) {
    const names = (characters || []).flatMap((name) => {
      const clean = name.replace(/^未来的/, "").replace(/[（(\[].*$/, "").trim();
      if (/主角组|众马|全体|小马合唱团|虹爆/.test(clean)) return mainCast;
      return [aliases[clean] || clean];
    });
    return [...new Set(names.map((name) => coats[name]).filter(Boolean))].slice(0, 6);
  }
  function coverColors(image) {
    const size = 48;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0, size, size);
    const pixels = context.getImageData(0, 0, size, size).data;
    const histogram = new Map();
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] < 128) continue;
      const [r, g, b] = pixels.subarray(i, i + 3);
      const key = (r >> 5) * 64 + (g >> 5) * 8 + (b >> 5);
      if (!histogram.has(key)) histogram.set(key, {r: 0, g: 0, b: 0, count: 0});
      const bucket = histogram.get(key);
      bucket.r += r; bucket.g += g; bucket.b += b; bucket.count++;
    }
    const candidates = Array.from(histogram.values(), ({r, g, b, count}) => {
      const rgb = [r / count, g / count, b / count];
      const chroma = Math.max(...rgb) - Math.min(...rgb);
      return {rgb, weight: Math.sqrt(count) * (1 + chroma / 255)};
    });
    if (!candidates.length) return [];
    const colors = [];
    // Choose prevalent colors that are also separated from those already picked.
    const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    while (colors.length < coverColorCount && candidates.length) {
      const score = ({rgb, weight}) => colors.length
        ? weight * Math.min(...colors.map((other) => distance(rgb, other))) : weight;
      candidates.sort((a, b) => score(b) - score(a));
      colors.push(candidates.shift().rgb);
    }
    // Flat covers may have fewer than four colors. Use shades of their main color.
    const main = colors[0];
    const shadeTarget = Math.max(...main) > 160 ? 0 : 255;
    for (let step = 1; colors.length < coverColorCount; step++) {
      colors.push(main.map((channel) => channel + (shadeTarget - channel) * step / 6));
    }
    return colors.map((rgb) => {
      const lift = Math.max(0, 128 - Math.max(...rgb)) / 2;
      return rgb.map((channel) => Math.round(channel + lift));
    });
  }
  async function loadCoverColors(src) {
    if (coverPalettes.has(src)) return coverPalettes.get(src);
    try {
      const url = new URL(src, document.baseURI).href;
      let image = document.querySelector("#nowCover");
      if (image?.src !== url) {
        image = new Image();
        image.src = url;
      }
      await image.decode();
      if (image.src !== url) return [];
      const colors = coverColors(image);
      if (colors.length) {
        coverPalettes.set(src, colors);
        if (coverPalettes.size > 64) coverPalettes.delete(coverPalettes.keys().next().value);
      }
      return colors;
    } catch (_) {
      return [];
    }
  }
  function drift(light) {
    const path = [light.position, point(), point(), point()];
    light.position = path.at(-1);
    light.animation = light.element.animate(path.map((p) => ({transform: transform(p)})), {duration: random(65000, 95000), easing: "ease-in-out", fill: "forwards"});
    light.animation.onfinish = () => {
      if (!lights.includes(light)) return;
      light.element.style.transform = transform(light.position);
      light.animation.cancel(); drift(light); sync();
    };
  }
  function sync() {
    layer.hidden = !enabled;
    const playing = enabled && !audio.paused && !audio.ended && !panel.hidden && !document.hidden;
    layer.classList.toggle("is-playing", playing);
    lights.forEach((light) => {
      if (playing && !reduced.matches) light.animation.play();
      else light.animation.pause();
    });
  }
  function paint(colors, fromCover = false) {
    layer.style.setProperty("--glow-alpha", String(fromCover ? .09 : Math.min(.11, .22 / Math.max(1, colors.length))));
    colors.forEach((color, i) => {
      const element = document.createElement("span"); element.className = "player-glow";
      const rgb = fromCover ? color : [1, 3, 5].map((start) => parseInt(color.slice(start, start + 2), 16));
      element.style.setProperty("--glow-rgb", rgb.join(","));
      if (!fromCover) element.dataset.coat = color;
      const light = {element, position: {x: (i + .5) / colors.length * 70 - 35, y: i % 2 ? 18 : -18, scale: 1}, animation: null};
      element.style.transform = transform(light.position); layer.append(element); lights.push(light); drift(light);
    });
    sync();
  }
  function setSong(song) {
    const nextId = song?.id || null;
    const nextCover = song ? song.cover || "/logo.png" : "";
    if (nextId === songId && nextCover === cover) return;
    songId = nextId;
    cover = nextCover;
    const request = ++generation;
    lights.forEach((light) => light.animation.cancel()); lights = []; layer.replaceChildren();
    const colors = palette(song?.characters);
    if (colors.length || !cover) {
      paint(colors);
      return;
    }
    loadCoverColors(cover).then((rgb) => {
      if (request === generation) paint(rgb, true);
    });
  }
  ["play", "pause", "ended"].forEach((event) => audio.addEventListener(event, sync));
  document.querySelector("#ambientEffect").onclick = (e) => {enabled = !enabled; e.currentTarget.setAttribute("aria-pressed", String(enabled)); sync();};
  document.addEventListener("visibilitychange", sync); reduced.addEventListener("change", sync);
  new MutationObserver(sync).observe(panel, {attributes: true, attributeFilter: ["hidden"]});
  window.MusicAmbient = {setSong};
})();

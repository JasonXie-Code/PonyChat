(() => {
  const characters = [
    { id: 'twilight', name: '紫悦', english: 'Twilight Sparkle', coat: '#ab8bc4', post: 3148844 },
    { id: 'applejack', name: '苹果嘉儿', english: 'Applejack', coat: '#dca360', post: 3150616 },
    { id: 'rainbow', name: '云宝', english: 'Rainbow Dash', coat: '#75badd', post: 3149189 },
    { id: 'pinkie', name: '碧琪', english: 'Pinkie Pie', coat: '#e990ad', post: 3149448 },
    { id: 'fluttershy', name: '柔柔', english: 'Fluttershy', coat: '#deca70', post: 3605623 },
    { id: 'rarity', name: '珍奇', english: 'Rarity', coat: '#8e78be', post: 3150619 },
  ];
  const sizes = [128, 64, 48, 32, 24, 16];
  const comparison = document.querySelector('#comparison');
  const hero = document.querySelector('#hero-samples');
  const shortcuts = document.querySelector('#shortcuts');
  const description = document.querySelector('#mode-description');
  const methods = [...document.querySelectorAll('input[name="method"]')];
  const sizesControl = document.querySelector('#actual-size');
  const loaded = [];
  let method = 'area';

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(`Cannot load ${url}`));
      image.src = url;
    });
  }

  function visibleSource(image) {
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(image, 0, 0);
    const source = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let left = source.width;
    let right = -1;
    let top = source.height;
    let bottom = -1;
    for (let y = 0; y < source.height; y++) {
      for (let x = 0; x < source.width; x++) {
        if (source.data[(y * source.width + x) * 4 + 3] === 0) continue;
        left = Math.min(left, x);
        right = Math.max(right, x);
        top = Math.min(top, y);
        bottom = Math.max(bottom, y);
      }
    }
    if (right < left) throw new Error('Image is transparent');
    return ctx.getImageData(left, top, right - left + 1, bottom - top + 1);
  }

  // Weight partial source pixels by overlap and transparency to keep the edge clean.
  function sampleArea(source, x0, y0, x1, y1, dest, offset) {
    let red = 0;
    let green = 0;
    let blue = 0;
    let alpha = 0;
    for (let y = Math.floor(y0); y < Math.ceil(y1); y++) {
      const dy = Math.min(y + 1, y1) - Math.max(y, y0);
      for (let x = Math.floor(x0); x < Math.ceil(x1); x++) {
        const dx = Math.min(x + 1, x1) - Math.max(x, x0);
        const pixel = (y * source.width + x) * 4;
        const weight = dx * dy * source.data[pixel + 3];
        red += source.data[pixel] * weight;
        green += source.data[pixel + 1] * weight;
        blue += source.data[pixel + 2] * weight;
        alpha += weight;
      }
    }
    if (!alpha) return;
    dest[offset] = red / alpha;
    dest[offset + 1] = green / alpha;
    dest[offset + 2] = blue / alpha;
    dest[offset + 3] = alpha / ((x1 - x0) * (y1 - y0));
  }

  function paint(canvas, source, size, mode) {
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    const output = ctx.createImageData(size, size);
    const ratio = size / Math.max(source.width, source.height);
    const width = Math.max(1, Math.round(source.width * ratio));
    const height = Math.max(1, Math.round(source.height * ratio));
    const left = Math.floor((size - width) / 2);
    const top = Math.floor((size - height) / 2);
    for (let y = 0; y < height; y++) {
      const y0 = y * source.height / height;
      const y1 = (y + 1) * source.height / height;
      for (let x = 0; x < width; x++) {
        const x0 = x * source.width / width;
        const x1 = (x + 1) * source.width / width;
        const offset = ((y + top) * size + x + left) * 4;
        if (mode === 'nearest') {
          const sx = Math.floor((x0 + x1) / 2);
          const sy = Math.floor((y0 + y1) / 2);
          const start = (sy * source.width + sx) * 4;
          output.data.set(source.data.subarray(start, start + 4), offset);
        } else {
          sampleArea(source, x0, y0, x1, y1, output.data, offset);
        }
      }
    }
    ctx.putImageData(output, 0, 0);
  }

  function frame(content, label, sourceUrl) {
    const figure = element('figure', 'sample');
    const art = element('div', 'art');
    art.append(content);
    const caption = element('figcaption');
    if (sourceUrl) {
      const link = element('a', '', label);
      link.href = sourceUrl;
      caption.append(link);
    } else {
      caption.textContent = label;
    }
    figure.append(art, caption);
    return figure;
  }

  function addCharacter(character, result) {
    const { id, name, english, coat, post } = character;
    const link = element('a', '', name);
    link.href = `#${id}`;
    shortcuts.append(link);

    const card = element('section', 'character');
    card.id = id;
    card.style.setProperty('--coat', coat);
    const header = element('header', 'character-header');
    header.append(element('h2', '', name), element('p', '', english));
    card.append(header);

    if (result.status === 'fulfilled') {
      const { image, source } = result.value;
      image.alt = `${name}原图`;
      const row = element('div', 'samples');
      row.append(frame(image, '原图', `https://derpibooru.org/images/${post}`));
      const canvases = sizes.map(size => {
        const canvas = document.createElement('canvas');
        canvas.style.setProperty('--size', `${size}px`);
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${name}，${size} × ${size} 像素`);
        row.append(frame(canvas, `${size}×${size}`));
        return canvas;
      });
      card.append(row);
      loaded.push({ id, source, canvases });
    } else {
      card.append(element('p', '', '这张角色原图加载失败。请刷新页面重试。'));
    }
    comparison.append(card);
  }

  function render() {
    description.textContent = method === 'area'
      ? '区域平均把覆盖到的颜色合在一起，边缘会更平滑。'
      : '最近邻只取每个格子中心附近的一个像素，轮廓更硬，细线可能断开。';
    for (const { source, canvases } of loaded) {
      sizes.forEach((size, index) => paint(canvases[index], source, size, method));
    }
    const example = loaded.find(item => item.id === 'rainbow') ?? loaded[0];
    if (!example) return;
    hero.replaceChildren(...[128, 32, 16].map(size => {
      const canvas = document.createElement('canvas');
      paint(canvas, example.source, size, method);
      const figure = element('figure', 'example');
      figure.append(canvas, element('figcaption', '', `${size} px`));
      return figure;
    }));
  }

  for (const input of methods) {
    input.addEventListener('change', () => {
      if (!input.checked) return;
      method = input.value;
      render();
    });
  }
  sizesControl.addEventListener('change', () => comparison.classList.toggle('actual', sizesControl.checked));
  comparison.classList.toggle('actual', sizesControl.checked);

  Promise.allSettled(characters.map(async ({ id }) => {
    const image = await loadImage(`sources/${id}.png`);
    return { image, source: visibleSource(image) };
  })).then(results => {
    characters.forEach((character, index) => addCharacter(character, results[index]));
    comparison.setAttribute('aria-busy', 'false');
    method = methods.find(input => input.checked).value;
    render();
  });
})();

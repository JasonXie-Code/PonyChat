(() => {
  const groups = { pony: '小马系', cat: '猫系', dog: '狗系' };
  const groupKeys = Object.keys(groups);
  const groupDesigns = Object.fromEntries(groupKeys.map(group => [group, []]));
  for (const design of window.PixelPonyDesigns ?? []) groupDesigns[design.group].push(design);
  const designs = [];
  for (let i = 0; i < Math.max(...groupKeys.map(group => groupDesigns[group].length)); i++) {
    for (const group of groupKeys) {
      if (groupDesigns[group][i]) designs.push(groupDesigns[group][i]);
    }
  }

  const favoriteKey = 'pixel-pony-studio-favorites';
  const saved = new Set();
  try {
    const stored = JSON.parse(localStorage.getItem(favoriteKey) ?? '[]');
    if (Array.isArray(stored)) {
      for (const design of designs) {
        if (stored.includes(design.id)) saved.add(design.id);
      }
    }
  } catch {
    // Browsers that restrict storage can still use favorites during this visit.
  }

  const gallery = document.querySelector('#gallery');
  const filters = document.querySelector('#filters');
  const savedToggle = document.querySelector('#saved-toggle');
  const savedCount = document.querySelector('#saved-count');
  const visibleCount = document.querySelector('#visible-count');
  const galleryTitle = document.querySelector('#gallery-title');
  const empty = document.querySelector('#empty');
  const dialog = document.querySelector('#preview');
  const previewClose = document.querySelector('#preview-close');
  const previewArt = document.querySelector('#preview-art');
  const previewTitle = document.querySelector('#preview-title');
  const previewGroup = document.querySelector('#preview-group');
  const previewDescription = document.querySelector('#preview-description');
  const previewSwatches = document.querySelector('#preview-swatches');
  const previewSave = document.querySelector('#preview-save');
  const previewPosition = document.querySelector('#preview-position');
  const previous = document.querySelector('#previous');
  const next = document.querySelector('#next');

  const sources = new Map();
  const filterButtons = new Map();
  const cards = new Map();
  let filter = 'all';
  let lastGroup = 'all';
  let visible = [];
  let previewList = [];
  let previewIndex = 0;
  let previewTrigger = null;

  function element(tag, className, label) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (label) node.textContent = label;
    return node;
  }

  function sprite(design) {
    if (!sources.has(design.id)) {
      const canvas = document.createElement('canvas');
      canvas.width = 128;
      canvas.height = 128;
      const ctx = canvas.getContext('2d');
      ctx.imageSmoothingEnabled = false;
      design.draw(ctx);
      sources.set(design.id, canvas.toDataURL('image/png'));
    }
    const image = new Image(128, 128);
    image.alt = '';
    image.src = sources.get(design.id);
    return image;
  }

  function swatches(design) {
    return design.colors.map(color => {
      const sample = element('span');
      sample.style.backgroundColor = color;
      return sample;
    });
  }

  function setFavoriteButton(design) {
    const { card, favorite, heart } = cards.get(design.id);
    const active = saved.has(design.id);
    card.classList.toggle('is-saved', active);
    favorite.setAttribute('aria-pressed', String(active));
    favorite.title = active ? '取消收藏' : '收藏这款';
    heart.textContent = active ? '♥' : '♡';
  }

  function toggleFavorite(design) {
    if (saved.has(design.id)) saved.delete(design.id);
    else saved.add(design.id);
    try {
      localStorage.setItem(favoriteKey, JSON.stringify([...saved]));
    } catch {
      // The page can keep this selection in memory.
    }
    setFavoriteButton(design);
    render();
    if (dialog.open) setPreviewFavorite(design);
  }

  function buildCard(design) {
    const card = element('article', 'pony-card');
    card.dataset.group = design.group;
    const artButton = element('button', 'sprite-tile');
    artButton.type = 'button';
    artButton.setAttribute('aria-label', `放大查看${design.name}`);
    artButton.append(sprite(design));
    artButton.addEventListener('click', () => openPreview(design, artButton));

    const tag = element('span', 'group-tag', groups[design.group]);
    const details = element('div', 'card-details');
    const palette = element('div', 'swatches');
    palette.setAttribute('aria-hidden', 'true');
    palette.append(...swatches(design));
    details.append(element('h3', '', design.name), element('p', '', design.description), palette);

    const favorite = element('button', 'favorite');
    favorite.type = 'button';
    favorite.setAttribute('aria-label', `收藏${design.name}`);
    const heart = element('span', 'heart');
    heart.setAttribute('aria-hidden', 'true');
    favorite.append(heart);
    favorite.addEventListener('click', () => {
      toggleFavorite(design);
      if (card.hidden) savedToggle.focus({ preventScroll: true });
    });

    card.append(artButton, details, tag, favorite);
    cards.set(design.id, { card, favorite, heart });
    setFavoriteButton(design);
    return card;
  }

  function setFilter(key) {
    filter = key;
    if (filter !== 'saved') lastGroup = filter;
    render();
  }

  function render() {
    visible = designs.filter(design =>
      filter === 'all' || filter === design.group || (filter === 'saved' && saved.has(design.id)));
    const visibleIds = new Set(visible.map(design => design.id));
    for (const [id, { card }] of cards) card.hidden = !visibleIds.has(id);
    for (const [key, button] of filterButtons) button.setAttribute('aria-pressed', String(filter === key));
    savedToggle.setAttribute('aria-pressed', String(filter === 'saved'));
    savedCount.textContent = saved.size;
    galleryTitle.textContent = filter === 'saved' ? '我的收藏' : '小马图鉴';
    visibleCount.textContent = `${visible.length} 款`;
    empty.hidden = filter !== 'saved' || visible.length > 0;
  }

  function setPreviewFavorite(design) {
    const active = saved.has(design.id);
    previewSave.setAttribute('aria-pressed', String(active));
    previewSave.textContent = active ? '♥ 已收藏' : '♡ 收藏这款';
  }

  function showPreview() {
    const design = previewList[previewIndex];
    dialog.dataset.group = design.group;
    previewArt.replaceChildren(sprite(design));
    previewTitle.textContent = design.name;
    previewGroup.textContent = groups[design.group];
    previewDescription.textContent = design.description;
    previewSwatches.replaceChildren(...swatches(design));
    previewPosition.textContent = `${previewIndex + 1} / ${previewList.length}`;
    previous.disabled = previewIndex === 0;
    next.disabled = previewIndex === previewList.length - 1;
    setPreviewFavorite(design);
  }

  function openPreview(design, trigger) {
    previewList = [...visible];
    previewIndex = previewList.indexOf(design);
    previewTrigger = trigger;
    showPreview();
    dialog.showModal();
    previewClose.focus();
  }

  function stepPreview(direction) {
    const index = previewIndex + direction;
    if (index < 0 || index >= previewList.length) return;
    previewIndex = index;
    showPreview();
  }

  for (const key of ['all', ...groupKeys]) {
    const button = element('button', 'filter-button', groups[key] ?? '全部');
    button.type = 'button';
    button.append(element('span', '', String(groupDesigns[key]?.length ?? designs.length)));
    button.addEventListener('click', () => setFilter(key));
    filterButtons.set(key, button);
    filters.append(button);
  }
  gallery.append(...designs.map(buildCard));

  const heroChoices = { pony: 0, cat: 1, dog: 3 };
  for (const group of groupKeys) {
    const design = groupDesigns[group][heroChoices[group]] ?? groupDesigns[group][0];
    if (design) document.querySelector(`[data-hero="${group}"]`).append(sprite(design));
  }

  savedToggle.addEventListener('click', () => {
    setFilter(filter === 'saved' ? lastGroup : 'saved');
    document.querySelector('#styles').scrollIntoView({ block: 'start' });
  });
  document.querySelector('#show-all').addEventListener('click', () => {
    setFilter('all');
    filterButtons.get('all').focus();
  });
  previewClose.addEventListener('click', () => dialog.close());
  previewSave.addEventListener('click', () => toggleFavorite(previewList[previewIndex]));
  previous.addEventListener('click', () => stepPreview(-1));
  next.addEventListener('click', () => stepPreview(1));
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    stepPreview(event.key === 'ArrowLeft' ? -1 : 1);
  });
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    const target = previewTrigger && !previewTrigger.closest('[hidden]') ? previewTrigger : savedToggle;
    target.focus({ preventScroll: true });
  });
  render();
})();

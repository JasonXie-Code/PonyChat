(() => {
  const world = ValleyWorld;
  const art = ValleyArt;
  const view = document.querySelector('#view');
  const ctx = view.getContext('2d', { alpha: false });
  const minimap = document.querySelector('#minimap');
  const mini = minimap.getContext('2d', { alpha: false });
  const roster = document.querySelector('#roster');
  const location = document.querySelector('#location');
  const mapLocation = document.querySelector('#map-location');
  const snowToggle = document.querySelector('#snow-toggle');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const homes = [[427,329], [371,319], [498,314], [476,367]];
  const characters = art.ponies.map((pony, index) => ({
    pony, x: homes[index][0], y: homes[index][1], facing: index < 2 ? 1 : -1, moving: false,
    animationOffset: index * .9,
  }));
  const buttons = [];
  const keys = new Set();
  const directions = new Map([
    ['arrowup',[0,-1]], ['w',[0,-1]], ['arrowdown',[0,1]], ['s',[0,1]],
    ['arrowleft',[-1,0]], ['a',[-1,0]], ['arrowright',[1,0]], ['d',[1,0]],
  ]);
  let player = characters[0];
  let selected = 0;
  let route = [];
  let destination = null;
  let snowing = !reducedMotion.matches;
  let currentPlace = '';
  let cameraX = 0;
  let cameraY = 0;
  let viewWidth = 1;
  let viewHeight = 1;
  let previousTime;
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

  const gridStep = 8;
  const gridWidth = Math.ceil(world.width / gridStep);
  const gridHeight = Math.ceil(world.height / gridStep);
  const cellCount = gridWidth * gridHeight;
  const cells = Array.from({ length: cellCount }, (_, id) => ({
    x: (id % gridWidth) * gridStep + gridStep / 2,
    y: Math.floor(id / gridWidth) * gridStep + gridStep / 2,
  }));
  const walkable = cells.map(cell => world.canStand(cell.x, cell.y));
  const links = new Array(cellCount);
  const neighbors = [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]];

  function connectedCells(id) {
    if (links[id]) return links[id];
    const neighborsInRange = [];
    const col = id % gridWidth;
    const row = Math.floor(id / gridWidth);
    for (const [dx, dy] of neighbors) {
      const x = col + dx, y = row + dy;
      if (x < 0 || x >= gridWidth || y < 0 || y >= gridHeight) continue;
      const next = x + y * gridWidth;
      if (walkable[next] && world.canWalk(cells[id].x, cells[id].y, cells[next].x, cells[next].y)) neighborsInRange.push(next);
    }
    links[id] = neighborsInRange;
    return neighborsInRange;
  }

  function planWalk(x, y) {
    if (world.canWalk(player.x, player.y, x, y)) return [{ x, y }];
    const parents = new Int32Array(cellCount).fill(-2);
    const queue = [];
    const col = Math.floor(player.x / gridStep);
    const row = Math.floor(player.y / gridStep);
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const id = col + dx + (row + dy) * gridWidth;
        if (walkable[id] && world.canWalk(player.x, player.y, cells[id].x, cells[id].y)) {
          parents[id] = -1;
          queue.push(id);
        }
      }
    }

    let closest = -1;
    let best = Infinity;
    const targetIsWalkable = world.canStand(x, y);
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      const cell = cells[id];
      const distance = (cell.x - x) ** 2 + (cell.y - y) ** 2;
      if (distance < best) {
        closest = id;
        best = distance;
      }
      if (targetIsWalkable && distance < gridStep ** 2 && world.canWalk(cell.x, cell.y, x, y)) {
        closest = id;
        break;
      }
      for (const next of connectedCells(id)) {
        if (parents[next] !== -2) continue;
        parents[next] = id;
        queue.push(next);
      }
    }

    if (closest === -1) return [];
    const points = [];
    for (let id = closest; id !== -1; id = parents[id]) points.push(cells[id]);
    points.reverse();
    if (targetIsWalkable && world.canWalk(cells[closest].x, cells[closest].y, x, y)) points.push({ x, y });

    const waypoints = [];
    let from = player;
    while (points.length > 0) {
      let next = points.length - 1;
      while (next > 0 && !world.canWalk(from.x, from.y, points[next].x, points[next].y)) next--;
      from = points[next];
      waypoints.push(from);
      points.splice(0, next + 1);
    }
    return waypoints;
  }

  function setSnow(enabled) {
    snowing = enabled;
    snowToggle.setAttribute('aria-pressed', String(enabled));
    snowToggle.title = enabled ? '关闭飘雪' : '开启飘雪';
  }
  setSnow(snowing);
  snowToggle.addEventListener('click', () => setSnow(!snowing));
  reducedMotion.addEventListener('change', event => setSnow(!event.matches));

  function selectPony(index) {
    player.moving = false;
    buttons[selected].setAttribute('aria-pressed', 'false');
    selected = index;
    buttons[index].setAttribute('aria-pressed', 'true');
    player = characters[index];
    route = [];
    destination = null;
    updateCamera(1);
    updateLocation();
  }

  characters.forEach(({ pony }, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'pony-button';
    button.setAttribute('aria-pressed', String(index === selected));
    const sprite = document.createElement('canvas');
    sprite.width = 136;
    sprite.height = 124;
    const p = sprite.getContext('2d');
    p.scale(2, 2);
    art.ellipse(p, pony.icon, 34, 31, 29, 28);
    art.ellipse(p, '#ded2eb23', 31, 29, 25, 25);
    art.star(p, 9, 19, '#e4cba8', 2);
    art.star(p, 57, 9, '#e4cba8', 2);
    art.rect(p, '#f4dbaf', 57, 44, 1, 1);
    p.imageSmoothingEnabled = false;
    p.translate(35, 52);
    p.scale(2, 2);
    art.drawPony(p, 0, 0, pony, 0, false, 1, true);
    const portrait = document.createElement('img');
    portrait.className = 'portrait';
    portrait.width = 68;
    portrait.height = 62;
    portrait.alt = '';
    portrait.src = sprite.toDataURL();
    button.append(portrait, pony.name);
    button.addEventListener('click', () => selectPony(index));
    roster.appendChild(button);
    buttons.push(button);
  });

  document.querySelector('#reset').addEventListener('click', () => {
    [player.x, player.y] = homes[selected];
    route = [];
    destination = null;
    keys.clear();
    updateCamera(1);
    updateLocation();
    view.focus({ preventScroll: true });
  });

  window.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    if (!directions.has(key) || event.altKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    keys.add(key);
    route = [];
    destination = null;
  });
  window.addEventListener('keyup', event => keys.delete(event.key.toLowerCase()));
  window.addEventListener('blur', () => keys.clear());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) keys.clear();
  });

  const origin = () => ({
    x: Math.round(clamp(cameraX - viewWidth / 2, 0, world.width - viewWidth)),
    y: Math.round(clamp(cameraY - viewHeight / 2, 0, world.height - viewHeight)),
  });

  view.addEventListener('click', event => {
    const box = view.getBoundingClientRect();
    const offset = origin();
    const x = offset.x + (event.clientX - box.left) * viewWidth / box.width;
    const y = offset.y + (event.clientY - box.top) * viewHeight / box.height;
    view.focus({ preventScroll: true });
    keys.clear();
    route = planWalk(x, y);
    destination = route.at(-1) ?? null;
  });

  function resize() {
    const box = view.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const mobile = matchMedia('(max-width: 680px)').matches;
    const idealScale = mobile ? Math.min(1.6, box.width / 252) : Math.min(2.6, box.width / 490, box.height / 295);
    const scale = Math.max(idealScale, box.width / world.width, box.height / world.height);
    viewWidth = Math.min(world.width, Math.round(box.width / scale));
    viewHeight = Math.min(world.height, Math.round(box.height / scale));
    // Keep terrain pixels aligned while drawing finer pony art in the same world space.
    const density = clamp(Math.ceil(scale * (window.devicePixelRatio || 1)), 2, 4);
    view.width = viewWidth * density;
    view.height = viewHeight * density;
    ctx.setTransform(density, 0, 0, density, 0, 0);
    ctx.imageSmoothingEnabled = false;
    updateCamera(1);
  }
  resize();
  new ResizeObserver(resize).observe(view);

  function updateCamera(weight) {
    cameraX += (player.x - cameraX) * weight;
    cameraY += (player.y - viewHeight * .14 - cameraY) * weight;
  }

  function updateLocation() {
    const next = world.placeAt(player.x, player.y);
    if (next === currentPlace) return;
    currentPlace = next;
    location.textContent = next;
    mapLocation.textContent = next;
  }

  function update(dt) {
    const oldX = player.x, oldY = player.y;
    const speed = dt * 100;
    let dx = 0, dy = 0;
    for (const key of keys) {
      const [kx, ky] = directions.get(key);
      dx += kx;
      dy += ky;
    }
    dx = Math.sign(dx);
    dy = Math.sign(dy);
    if (dx || dy) {
      const length = Math.hypot(dx, dy);
      const nx = player.x + dx * speed / length;
      const ny = player.y + dy * speed / length;
      if (world.canWalk(player.x, player.y, nx, player.y)) player.x = nx;
      if (world.canWalk(player.x, player.y, player.x, ny)) player.y = ny;
    } else if (route.length) {
      const next = route[0];
      dx = next.x - player.x;
      dy = next.y - player.y;
      const remaining = Math.hypot(dx, dy);
      if (remaining <= speed) {
        player.x = next.x;
        player.y = next.y;
        route.shift();
        if (!route.length) destination = null;
      } else {
        player.x += dx * speed / remaining;
        player.y += dy * speed / remaining;
      }
    }

    if (Math.abs(player.x - oldX) > .05) player.facing = player.x > oldX ? 1 : -1;
    player.moving = Math.hypot(player.x - oldX, player.y - oldY) > .04;
    updateCamera(1 - Math.exp(-dt * 9));
    updateLocation();
  }

  const props = [...world.props].sort((a, b) => a.y - b.y);
  const miniBase = document.createElement('canvas');
  miniBase.width = minimap.width;
  miniBase.height = minimap.height;
  const miniArt = miniBase.getContext('2d');
  miniArt.scale(minimap.width / world.width, minimap.height / world.height);
  miniArt.drawImage(world.terrain, 0, 0);
  for (const prop of props) world.drawProp(miniArt, prop);

  function drawMinimap(offset) {
    const sx = minimap.width / world.width;
    const sy = minimap.height / world.height;
    mini.drawImage(miniBase, 0, 0);
    mini.strokeStyle = '#3b325c96';
    mini.lineWidth = 1;
    mini.strokeRect(Math.round(offset.x * sx) + .5, Math.round(offset.y * sy) + .5, Math.round(viewWidth * sx) - 1, Math.round(viewHeight * sy) - 1);
    const x = Math.round(player.x * sx);
    const y = Math.round(player.y * sy);
    art.ellipse(mini, '#3a2e4d', x, y, 4.7, 4.7);
    art.ellipse(mini, '#ffdc95', x, y, 3, 3);
  }

  const flakes = [];
  const flakeRandom = art.random(580);
  for (let i = 0; i < 88; i++) {
    flakes.push({ x: flakeRandom(), y: flakeRandom(), speed: .012 + flakeRandom() * .045, size: i % 7 === 0 ? 2 : 1, phase: flakeRandom() * 6 });
  }

  function draw(time) {
    const offset = origin();
    ctx.drawImage(world.terrain, offset.x, offset.y, viewWidth, viewHeight, 0, 0, viewWidth, viewHeight);
    ctx.save();
    ctx.translate(-offset.x, -offset.y);
    if (destination) {
      const x = Math.round(destination.x), y = Math.round(destination.y);
      art.ellipse(ctx, '#544c687c', x, y, 7, 4);
      art.ellipse(ctx, '#fff0bf', x, y, 5.5, 2.8);
      art.ellipse(ctx, '#887393', x, y, 3.8, 1.5);
    }
    const actors = [...characters].sort((a, b) => a.y - b.y);
    let actorIndex = 0;
    function drawCharacter(character) {
      if (character === player) {
        ctx.strokeStyle = '#fff0bf';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(character.x, character.y, 10, 3.5, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      art.drawPony(ctx, character.x, character.y, character.pony, time + character.animationOffset, character.moving, character.facing);
    }
    for (const prop of props) {
      while (actors[actorIndex] && actors[actorIndex].y <= prop.y) {
        drawCharacter(actors[actorIndex]);
        actorIndex++;
      }
      if (prop.x + 94 >= offset.x && prop.x - 70 <= offset.x + viewWidth
        && prop.y + 18 >= offset.y && prop.y - 120 <= offset.y + viewHeight) world.drawProp(ctx, prop);
    }
    while (actors[actorIndex]) {
      drawCharacter(actors[actorIndex]);
      actorIndex++;
    }
    ctx.restore();

    if (snowing) {
      for (const flake of flakes) {
        const x = Math.floor((flake.x * viewWidth + Math.sin(time * .8 + flake.phase) * 7 + viewWidth) % viewWidth);
        const y = Math.floor(((flake.y + time * flake.speed) % 1) * viewHeight);
        art.rect(ctx, flake.size === 2 ? '#fffdf8df' : '#ffffffa0', x, y, flake.size, flake.size);
      }
    }
    drawMinimap(offset);
  }

  function frame(ms) {
    const dt = previousTime == null ? 0 : Math.min((ms - previousTime) / 1000, .034);
    previousTime = ms;
    update(dt);
    draw(ms / 1000);
    requestAnimationFrame(frame);
  }
  updateLocation();
  requestAnimationFrame(frame);
})();

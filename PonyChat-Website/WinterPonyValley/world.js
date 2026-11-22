const ValleyWorld = (() => {
  const art = ValleyArt;
  const { rect, shape, ellipse, random } = art;
  const width = 880;
  const height = 608;
  const margin = 12;
  const props = [];
  const walls = [];

  const roads = [
    [34,313,116,294,152,298,212,278,285,274,325,286,372,288,401,270,487,267,508,283,549,287,575,301,569,322,531,326,501,340,481,356,459,363,426,363,396,354,374,340,337,328,314,322,273,318,220,325,173,332,130,329,78,351,40,349],
    [381,0,416,0,414,40,447,86,433,133,435,175,450,212,465,244,474,286,435,299,409,275,414,245,404,215,398,178,395,154,401,120,412,92,381,53],
    [410,340,467,343,463,383,479,416,470,451,446,473,437,508,449,556,437,608,402,608,416,557,399,514,405,470,434,441,440,420,423,389],
    [449,398,479,381,524,401,549,425,592,437,637,438,692,416,739,413,796,432,880,429,880,463,797,469,739,450,699,449,639,468,586,470,530,455,501,430,464,423],
    [285,222,318,220,329,259,344,283,326,298,301,285,289,263],
    [515,220,553,221,557,247,541,273,525,303,497,298,508,267,521,244],
    [630,380,664,387,658,431,665,444,628,454,621,427],
    [195,329,225,314,245,347,249,372,281,404,274,427,251,434,224,395,217,375],
  ];

  const pond = [562,313,579,298,605,290,644,286,675,291,701,303,720,319,733,342,731,364,721,383,696,399,664,405,625,404,600,396,572,387,555,372,547,349,550,328];
  // The notch on the west bank keeps the wooden pier accessible.
  const iceBoundary = [558,311,577,294,604,286,644,282,676,287,704,300,723,317,737,341,735,365,723,386,698,402,664,409,625,408,598,400,570,391,551,374,543,351,565,351,565,347,543,347,546,326];

  function inside(x, y, points) {
    let hit = false;
    for (let i = 0, j = points.length - 2; i < points.length; j = i, i += 2) {
      const xi = points[i], yi = points[i + 1], xj = points[j], yj = points[j + 1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }

  function block(left, top, right, bottom) {
    const radius = 4;
    walls.push({ left: left - radius, top: top - radius, right: right + radius, bottom: bottom + radius });
  }

  function prop(type, x, y, ...args) {
    props.push({ type, x, y, args });
  }

  function pine(x, y, size = 1, variant = 0, festive = false) {
    prop('pine', x, y, size, variant, festive);
    block(x - 10 * size, y - 11 * size, x + 10 * size, y + 3 * size);
  }

  function cabin(x, y, variant, size = 1) {
    prop('cabin', x, y, variant, size);
    block(x - 42 * size, y - 49 * size, x + 42 * size, y + 2 * size);
    block(x + 41 * size, y - 50 * size, x + 65 * size, y - 12 * size);
  }

  function fence(x, y, length) {
    prop('fence', x, y, length);
    block(x - 2, y - 8, x + length + 2, y + 2);
  }

  function furnish(type, x, y, w, h, ...args) {
    prop(type, x, y, ...args);
    block(x - w, y - h, x + w, y + 2);
  }

  const rimRandom = random(3982);
  for (let x = 16; x < width; x += 28 + Math.round(rimRandom() * 21)) {
    if (x < 365 || x > 452) {
      pine(x, 22 + Math.round(rimRandom() * 40), .70 + rimRandom() * .48, Math.floor(rimRandom() * 3));
      pine(x + 13, 84 + Math.round(rimRandom() * 38), .76 + rimRandom() * .37, Math.floor(rimRandom() * 3));
    }
    if (x < 374 || x > 461) {
      pine(x + 8, 597 - Math.round(rimRandom() * 37), .77 + rimRandom() * .45, Math.floor(rimRandom() * 3));
    }
  }
  for (let y = 137; y < 551; y += 31 + Math.round(rimRandom() * 19)) {
    if (y < 277 || y > 367) pine(20 + Math.round(rimRandom() * 25), y, .81 + rimRandom() * .32, Math.floor(rimRandom() * 3));
    if (y < 412 || y > 474) pine(850 + Math.round(rimRandom() * 16), y, .79 + rimRandom() * .34, Math.floor(rimRandom() * 3));
  }

  const groves = [
    [147,179,1.1,1],[178,170,.97,0],[189,199,1.22,2],[225,166,.83,1],[238,212,1.05,0],
    [151,228,.79,2],[194,244,.74,0],[246,262,.86,1],[220,239,.78,2],[144,275,.66,1],
    [310,123,.88,2],[348,145,1.05,1],[369,180,.76,2],[380,223,.71,0],
    [466,150,.99,2],[484,204,.64,0],[585,152,1.07,1],[636,176,1.06,2],[675,186,.94,0],
    [621,226,.85,0],[659,243,1.02,1],[709,232,1.18,2],[730,264,.84,0],[773,280,1.08,1],
    [781,312,.85,2],[817,339,1.13,0],[744,391,.72,1],[797,406,.96,2],
    [199,405,.75,1],[175,447,1.08,0],[149,420,.92,1],[132,481,1.2,2],[199,511,1.15,2],
    [234,544,.92,1],[264,503,.74,0],[281,462,.85,2],[309,390,.67,1],[333,423,.88,0],
    [353,479,.73,1],[360,538,1.05,0],[505,486,.95,1],[478,536,.82,2],[523,553,1.30,0],
    [613,510,.76,2],[651,556,1.03,0],[688,498,.9,1],[721,554,1.04,2],[775,510,1.13,0],
    [790,552,.79,1],[101,217,.84,2],[94,379,.97,0],[121,392,.8,1],[68,483,1.05,0],
  ];
  for (const tree of groves) pine(...tree);

  cabin(286, 238, 0, 1.04);
  cabin(525, 234, 1, 1.05);
  cabin(717, 498, 2, .82);
  cabin(252, 433, 3, .84);
  pine(427, 292, 1.13, 2, true);
  fence(167, 263, 66);
  fence(246, 246, 24);
  fence(329, 236, 32);
  fence(463, 246, 26);
  fence(564, 248, 41);
  fence(717, 280, 40);
  fence(132, 356, 57);
  fence(300, 378, 43);
  fence(361, 408, 38);
  fence(488, 380, 23);
  fence(773, 476, 45);

  for (const [x, y] of [[78,319],[138,312],[229,306],[282,272],[343,262],[387,301],[479,300],[497,254],[536,339],[520,388],[577,422],[662,436],[736,425],[786,450],[412,392],[461,463],[425,513],[247,395],[394,172],[446,217]]) {
    furnish('lamp', x, y, 2.5, 2.5);
  }
  for (const [x, y] of [[359,291],[485,267],[553,400],[381,375],[674,414]]) furnish('bench', x, y, 15, 6);
  furnish('snowman', 357, 365, 8, 7);
  furnish('snowman', 765, 449, 8, 7);
  furnish('sign', 214, 350, 2, 2);
  furnish('sign', 538, 318, 2, 2);
  furnish('sign', 395, 433, 2, 2);
  prop('sled', 313, 352);
  prop('sled', 557, 274);
  prop('logPile', 329, 256);
  prop('logPile', 588, 254);
  prop('logPile', 296, 440);
  prop('parcel', 405, 292, '#b26380', '#ede0ad', 12);
  prop('parcel', 440, 292, '#729f9b', '#ffe2a4', 10);
  prop('parcel', 453, 297, '#ba7c84', '#ffe0b7', 9);
  prop('parcel', 734, 502, '#ae7889', '#ffdfb5', 9);
  for (const [i, [x, y]] of [[92,270],[107,348],[156,337],[207,278],[248,276],[330,213],[366,240],[375,339],[395,283],[457,265],[543,263],[593,274],[611,285],[750,363],[700,413],[541,455],[458,412],[405,442],[339,397],[273,379],[259,463],[805,399]].entries()) {
    prop('shrubs', x, y, i % 3 === 0);
  }

  function gradientSnow(g) {
    const fill = g.createLinearGradient(0, 0, width * .68, height);
    fill.addColorStop(0, '#b3c5e5');
    fill.addColorStop(.48, '#dfebf8');
    fill.addColorStop(1, '#bdcde9');
    rect(g, fill, 0, 0, width, height);
    const bright = g.createRadialGradient(421, 318, 35, 421, 318, 300);
    bright.addColorStop(0, '#f6f8ff80');
    bright.addColorStop(1, '#f7f9ff00');
    rect(g, bright, 0, 0, width, height);
  }

  function snowTexture(g) {
    const rnd = random(82480);
    const specks = ['#f4f9ff9c', '#f1f7ffc7', '#aec3e26e', '#b8c9e62e', '#c2d2eb99'];
    for (let i = 0; i < 4080; i++) {
      const x = Math.floor(rnd() * width), y = Math.floor(rnd() * height);
      rect(g, specks[i % specks.length], x, y, 1 + Math.floor(rnd() * 4), i % 5 === 0 ? 2 : 1);
    }
    for (let i = 0; i < 290; i++) {
      const x = Math.floor(rnd() * width), y = Math.floor(rnd() * height);
      const w = 3 + Math.floor(rnd() * 10);
      shape(g, '#b0c4e15b', [x-w,y,x-w+3,y-2,x-2,y-2,x-1,y-4,x+4,y-4,x+4,y-2,x+w,y-1,x+w,y+1,x-w,y+1]);
      rect(g, '#f2f8ffd9', x - 2, y - 3, 5, 1);
      rect(g, '#f1f7ff95', x - w + 2, y, w, 1);
    }
    for (let i = 0; i < 136; i++) {
      const x = Math.floor(rnd() * width), y = Math.floor(rnd() * height);
      rect(g, '#879dbf81', x, y - 3, 1, 4);
      rect(g, '#9cb2d4', x + 1, y, 2, 1);
      rect(g, '#b1c5df', x - 1, y + 1, 5, 1);
    }
  }

  function paving(g) {
    g.save();
    g.translate(0, 2);
    for (const road of roads) shape(g, '#ababc5', road);
    g.restore();
    for (const road of roads) shape(g, '#cfc2ce', road);
    // Each road is painted into the same mask so branching segments merge cleanly.
    const tiles = document.createElement('canvas');
    tiles.width = width;
    tiles.height = height;
    const tileContext = tiles.getContext('2d');
    const rnd = random(37127);
    for (let y = -4; y < height; y += 6) {
      for (let x = y % 12 - 12; x < width; x += 12) {
        const shift = Math.floor(rnd() * 3);
        const w = 8 + Math.floor(rnd() * 3);
        const h = 3 + Math.floor(rnd() * 2);
        const colors = ['#d4c5cf', '#d8cbd5', '#bfb1c4', '#c8bacc', '#dacbd2', '#d0bdc4'];
        rect(tileContext, colors[Math.floor(rnd() * colors.length)], x + shift, y, w, h);
        rect(tileContext, '#e1d5df88', x + shift + 1, y, w - 2, 1);
        rect(tileContext, '#b0a4bc84', x + shift + 1, y + h - 1, w - 2, 1);
      }
    }
    tileContext.globalCompositeOperation = 'destination-in';
    const roadMask = document.createElement('canvas');
    roadMask.width = width;
    roadMask.height = height;
    const mask = roadMask.getContext('2d');
    for (const road of roads) shape(mask, '#000', road);
    tileContext.drawImage(roadMask, 0, 0);
    g.drawImage(tiles, 0, 0);
  }

  function frozenLake(g) {
    g.save();
    g.translate(0, 5);
    shape(g, '#9aaccb', pond);
    g.restore();
    shape(g, '#ecf8ff', pond);
    g.save();
    g.translate(643, 344);
    g.scale(.945, .919);
    g.translate(-643, -344);
    shape(g, '#618da6', pond);
    g.restore();
    g.save();
    g.translate(643, 346);
    g.scale(.916, .870);
    g.translate(-643, -346);
    const ice = g.createLinearGradient(567, 308, 709, 393);
    ice.addColorStop(0, '#7fbbd5');
    ice.addColorStop(.45, '#b4dce9');
    ice.addColorStop(1, '#719bbf');
    shape(g, ice, pond);
    art.path(g, pond);
    g.clip();
    const rnd = random(8434);
    for (let i = 0; i < 115; i++) {
      rect(g, i % 4 === 0 ? '#e7f6fc8a' : '#d3f0fb4c', 550 + Math.floor(rnd() * 183), 293 + Math.floor(rnd() * 115), 2 + Math.floor(rnd() * 20), 1);
    }
    for (const points of [
      [571,348,586,339,597,341,613,330,625,328,620,330,614,331,597,343,588,340,572,350],
      [613,383,631,374,634,365,646,361,649,357,650,359,647,363,636,367,633,375,615,384],
      [671,329,674,341,691,346,700,359,712,363,706,363,699,360,690,348,673,343,670,333],
      [599,370,604,365,611,369,608,375,600,375], [670,388,675,383,682,385,681,389,674,391],
      [648,314,650,307,657,308,662,314,659,319,653,319],
    ]) shape(g, '#e3f5ff97', points);
    g.restore();
    for (const [x, y, w] of [[573,372,17],[600,396,21],[638,402,23],[675,402,25],[722,376,14],[722,324,18],[592,298,22]]) art.snowbank(g, x, y, w);

    rect(g, '#816982', 540, 345, 30, 14);
    rect(g, '#c29892', 540, 342, 30, 13);
    for (let x = 543; x < 570; x += 5) {
      rect(g, '#997688', x, 343, 1, 11);
      rect(g, '#e3bab0', x + 1, 343, 2, 1);
    }
    rect(g, '#edcbb7', 540, 342, 30, 1);
    for (const [x, y] of [[544,342],[567,342],[544,354],[567,354]]) {
      rect(g, '#72566e', x, y - 4, 3, 6);
      rect(g, '#f1f9fd', x, y - 5, 3, 2);
    }
  }

  const terrain = document.createElement('canvas');
  terrain.width = width;
  terrain.height = height;
  const ground = terrain.getContext('2d');
  gradientSnow(ground);
  snowTexture(ground);
  paving(ground);
  frozenLake(ground);

  const driftRandom = random(7648);
  for (let i = 0; i < 115; i++) {
    const x = Math.floor(driftRandom() * width), y = Math.floor(driftRandom() * height);
    if ((x > 535 && x < 745 && y > 278 && y < 410) || roads.some(road => inside(x, y, road))) continue;
    art.snowbank(ground, x, y, Math.floor(12 + driftRandom() * 30));
  }
  const detailRandom = random(6522);
  for (let i = 0; i < 30; i++) {
    const x = Math.round(395 + detailRandom() * 67);
    const y = Math.round(299 + detailRandom() * 54);
    shape(ground, i % 3 ? '#f6e5c488' : '#f9d3a998', [x-1,y,x,y-1,x+2,y,x+1,y+1]);
  }

  const cache = new Map();
  for (const item of props) {
    const id = JSON.stringify([item.type, ...item.args]);
    if (!cache.has(id)) {
      const sprite = document.createElement('canvas');
      sprite.width = 165;
      sprite.height = 139;
      art[item.type](sprite.getContext('2d'), 70, 120, ...item.args);
      cache.set(id, sprite);
    }
    item.sprite = cache.get(id);
  }

  function drawProp(g, item) {
    g.drawImage(item.sprite, item.x - 70, item.y - 120);
  }

  const zones = [
    { name: '铃灯广场', x: 429, y: 323, rx: 95, ry: 62 },
    { name: '枫糖烘焙屋', x: 283, y: 244, rx: 89, ry: 75 },
    { name: '月杉旅店', x: 525, y: 228, rx: 82, ry: 71 },
    { name: '镜霜湖', x: 640, y: 350, rx: 112, ry: 78 },
    { name: '冬信邮局', x: 720, y: 483, rx: 111, ry: 72 },
    { name: '松铃林', x: 262, y: 436, rx: 118, ry: 97 },
  ];

  function placeAt(x, y) {
    let nearest = null;
    let best = 1;
    for (const zone of zones) {
      const distance = ((x - zone.x) / zone.rx) ** 2 + ((y - zone.y) / zone.ry) ** 2;
      if (distance < best) {
        best = distance;
        nearest = zone;
      }
    }
    if (nearest) return nearest.name;
    if (y < 160) return '北坡松林';
    if (y > 495) return '南坡雪径';
    return '谷地雪径';
  }

  function canStand(x, y) {
    if (x < margin || y < margin || x > width - margin || y > height - margin) return false;
    if (walls.some(wall => x > wall.left && x < wall.right && y > wall.top && y < wall.bottom)) return false;
    return x < 543 || x > 737 || y < 282 || y > 409 || !inside(x, y, iceBoundary);
  }

  function canWalk(x, y, tx, ty) {
    if (!canStand(tx, ty)) return false;
    const dx = tx - x, dy = ty - y;
    const left = Math.min(x, tx), right = Math.max(x, tx);
    const top = Math.min(y, ty), bottom = Math.max(y, ty);
    for (const wall of walls) {
      if (right <= wall.left || left >= wall.right || bottom <= wall.top || top >= wall.bottom) continue;
      const x1 = dx ? (wall.left - x) / dx : -Infinity;
      const x2 = dx ? (wall.right - x) / dx : Infinity;
      const y1 = dy ? (wall.top - y) / dy : -Infinity;
      const y2 = dy ? (wall.bottom - y) / dy : Infinity;
      const enter = Math.max(0, Math.min(x1, x2), Math.min(y1, y2));
      const leave = Math.min(1, Math.max(x1, x2), Math.max(y1, y2));
      if (enter < leave) return false;
    }
    if (right < 543 || left > 737 || bottom < 282 || top > 409) return true;
    for (let i = 0, j = iceBoundary.length - 2; i < iceBoundary.length; j = i, i += 2) {
      const ax = iceBoundary[j] - x, ay = iceBoundary[j + 1] - y;
      const ex = iceBoundary[i] - iceBoundary[j], ey = iceBoundary[i + 1] - iceBoundary[j + 1];
      const cross = dx * ey - dy * ex;
      if (cross === 0) continue;
      const alongWalk = (ax * ey - ay * ex) / cross;
      const alongEdge = (ax * dy - ay * dx) / cross;
      if (alongWalk > 0 && alongWalk < 1 && alongEdge >= 0 && alongEdge <= 1) return false;
    }
    return !inside((x + tx) / 2, (y + ty) / 2, iceBoundary);
  }

  return { width, height, terrain, props, drawProp, placeAt, canStand, canWalk };
})();

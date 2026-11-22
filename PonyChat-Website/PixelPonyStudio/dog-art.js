(() => {
  // Scan conversion on a two-pixel grid gives every silhouette a clean pixel edge.
  const unit = 2;

  function cell(ctx, color, x, y, width = 1, height = 1) {
    ctx.fillStyle = color;
    ctx.fillRect(unit * x, unit * y, unit * width, unit * height);
  }

  function polygon(ctx, color, ox, oy, points) {
    const top = Math.floor(Math.min(...points.map(point => point[1])));
    const bottom = Math.ceil(Math.max(...points.map(point => point[1])));
    for (let y = top; y < bottom; y++) {
      const crossings = [];
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const [ax, ay] = points[j];
        const [bx, by] = points[i];
        if ((ay > y + 0.5) !== (by > y + 0.5)) {
          crossings.push(ax + (y + 0.5 - ay) * (bx - ax) / (by - ay));
        }
      }
      crossings.sort((a, b) => a - b);
      for (let i = 0; i < crossings.length; i += 2) {
        const left = Math.ceil(crossings[i] - 0.5);
        const right = Math.ceil(crossings[i + 1] - 0.5);
        if (right > left) cell(ctx, color, ox + left, oy + y, right - left, 1);
      }
    }
  }

  function inset(points, amount = 1) {
    const middleX = (Math.min(...points.map(point => point[0])) + Math.max(...points.map(point => point[0]))) / 2;
    const middleY = (Math.min(...points.map(point => point[1])) + Math.max(...points.map(point => point[1]))) / 2;
    return points.map(([x, y]) => [
      x + Math.sign(middleX - x) * Math.min(Math.abs(middleX - x), amount),
      y + Math.sign(middleY - y) * Math.min(Math.abs(middleY - y), amount),
    ]);
  }

  function piece(ctx, ink, color, ox, oy, points) {
    polygon(ctx, ink, ox, oy, points);
    polygon(ctx, color, ox, oy, inset(points));
  }

  const tails = {
    brush: {
      shape: [[2,-2],[-3,-5],[-8,-4],[-11,-1],[-12,4],[-11,8],[-13,12],[-10,12],[-10,15],[-5,14],[-2,10],[-1,5],[3,2]],
      shine: [[-10,5],[-9,0],[-6,-2],[-4,-2],[-7,1],[-8,6],[-10,9]],
      shade: [[0,0],[-3,3],[-4,8],[-8,12],[-10,13],[-6,13],[-2,9],[-1,5],[2,2]],
    },
    pennant: {
      shape: [[3,-3],[-2,-4],[-6,-7],[-7,-11],[-5,-14],[-7,-14],[-10,-10],[-11,-5],[-10,0],[-7,3],[-1,2],[4,1]],
      shine: [[-8,-8],[-7,-11],[-8,-6],[-7,-2],[-5,0],[-7,0],[-9,-3]],
      shade: [[-10,-3],[-8,1],[-5,2],[-1,1],[2,-1],[3,0],[-1,2],[-7,2],[-9,0]],
    },
    curl: {
      shape: [[4,-1],[0,-4],[-3,-3],[-5,-6],[-4,-9],[-1,-10],[0,-8],[-2,-7],[-1,-4],[3,-5],[4,-8],[3,-12],[-1,-14],[-6,-13],[-9,-10],[-10,-5],[-8,0],[-5,3],[-1,3],[4,1]],
      shine: [[-9,-6],[-8,-10],[-5,-12],[-1,-13],[1,-12],[-3,-11],[-6,-9],[-7,-6],[-6,-3]],
      shade: [[-8,-3],[-5,1],[-2,2],[2,1],[2,-1],[-3,-1],[-6,-3],[-8,-5]],
    },
    pompon: {
      shape: [[3,2],[-2,2],[-6,0],[-8,-2],[-8,-5],[-11,-5],[-13,-8],[-13,-12],[-11,-15],[-8,-15],[-6,-17],[-2,-16],[1,-13],[1,-10],[0,-7],[-4,-5],[-3,-2],[3,-1]],
      shine: [[-11,-10],[-10,-13],[-7,-13],[-6,-15],[-3,-14],[-2,-12],[-5,-12],[-7,-10],[-9,-11]],
      shade: [[-10,-7],[-6,-6],[-4,-8],[-2,-8],[-1,-10],[-2,-7],[-6,-5],[-8,-5]],
    },
    swish: {
      shape: [[3,-2],[-4,-3],[-8,-1],[-10,3],[-10,9],[-12,12],[-14,12],[-12,14],[-8,13],[-5,9],[-4,4],[-1,2],[4,2]],
      shine: [[-7,1],[-6,-1],[-2,-2],[0,-1],[-4,0],[-6,3],[-6,8],[-8,10],[-8,5]],
      shade: [[-9,9],[-6,8],[-5,4],[-3,3],[-5,9],[-8,12],[-11,13],[-10,11]],
    },
    tuft: {
      shape: [[3,-2],[-3,-4],[-8,-2],[-12,-4],[-11,-1],[-14,1],[-11,3],[-13,6],[-8,6],[-9,9],[-4,6],[-2,3],[3,1]],
      shine: [[-11,1],[-7,0],[-6,-2],[-2,-3],[0,-2],[-4,0],[-6,3],[-9,3]],
      shade: [[-3,1],[-6,4],[-9,5],[-7,5],[-8,7],[-4,5],[-2,2],[2,1]],
    },
    flame: {
      shape: [[3,-1],[0,-7],[-3,-6],[-4,-11],[-7,-9],[-8,-14],[-12,-9],[-14,-4],[-14,2],[-11,6],[-12,9],[-6,9],[-4,7],[-1,7],[0,4],[4,2]],
      shine: [[-13,1],[-12,-5],[-9,-9],[-9,-4],[-6,-7],[-6,-3],[-3,-3],[-6,0],[-8,4],[-11,5]],
      shade: [[-11,6],[-7,7],[-4,5],[-2,5],[-1,2],[1,1],[3,1],[0,4],[-2,6],[-5,7],[-8,8]],
    },
    veil: {
      shape: [[2,-2],[-3,-3],[-8,0],[-10,4],[-9,9],[-12,13],[-17,13],[-16,15],[-12,17],[-8,17],[-4,14],[-2,10],[-1,5],[3,2]],
      shine: [[-7,2],[-4,0],[-1,-1],[-2,1],[-5,3],[-6,8],[-8,12],[-13,15],[-15,14],[-11,13],[-9,9],[-9,5]],
      shade: [[-13,16],[-8,15],[-5,12],[-4,7],[-2,4],[0,2],[-2,8],[-3,12],[-6,15],[-9,16]],
    },
  };

  const manes = {
    roll: {
      crest: [[-13,-6],[-14,-10],[-11,-14],[-7,-15],[-3,-14],[0,-16],[5,-14],[8,-14],[11,-10],[12,-7],[9,-6],[6,-8],[4,-5],[1,-8],[-1,-5],[-5,-6],[-7,-2],[-10,-2]],
      neck: [[-12,-7],[-17,-3],[-17,4],[-19,5],[-16,10],[-18,14],[-11,13],[-6,9],[-5,0]],
      shine: [[-11,-11],[-8,-13],[-4,-13],[-1,-11],[1,-13],[5,-12],[8,-10],[4,-11],[1,-9],[-2,-10],[-6,-11],[-9,-9]],
    },
    wind: {
      crest: [[-16,-10],[-12,-13],[-7,-14],[-1,-16],[6,-15],[12,-11],[14,-7],[11,-8],[9,-6],[5,-9],[-1,-9],[-5,-6],[-12,-6],[-17,-4],[-14,-8]],
      neck: [[-12,-8],[-16,-4],[-15,1],[-20,4],[-17,5],[-21,8],[-17,9],[-20,13],[-14,12],[-8,9],[-6,2]],
      shine: [[-13,-11],[-7,-13],[-1,-15],[5,-13],[10,-10],[5,-11],[-1,-12],[-6,-10],[-11,-10],[-13,-8]],
    },
    crop: {
      crest: [[-14,-8],[-13,-12],[-9,-15],[-5,-16],[3,-15],[8,-13],[10,-9],[8,-7],[4,-10],[0,-7],[-5,-8],[-8,-6],[-13,-6]],
      neck: [[-13,-8],[-15,-2],[-15,4],[-18,8],[-16,12],[-11,10],[-8,7],[-6,1]],
      shine: [[-11,-12],[-8,-14],[-3,-14],[2,-13],[5,-11],[0,-12],[-5,-12],[-9,-10]],
    },
    curls: {
      crest: [[-16,-7],[-17,-10],[-15,-13],[-11,-13],[-12,-16],[-8,-18],[-4,-17],[-2,-15],[1,-18],[6,-17],[8,-15],[7,-12],[11,-11],[12,-8],[9,-5],[6,-5],[3,-8],[1,-5],[-3,-5],[-6,-7],[-8,-5],[-13,-5]],
      neck: [[-15,-8],[-18,-4],[-17,-1],[-20,1],[-20,5],[-17,7],[-18,10],[-16,13],[-12,12],[-7,7],[-6,0]],
      shine: [[-14,-9],[-12,-12],[-9,-11],[-9,-14],[-6,-16],[-4,-13],[-7,-13],[-7,-9],[-10,-8]],
    },
    split: {
      crest: [[-13,-7],[-14,-11],[-10,-15],[-3,-17],[5,-15],[8,-12],[10,-9],[7,-9],[6,-7],[3,-9],[0,-11],[-3,-8],[-6,-8],[-9,-5],[-12,-5]],
      neck: [[-14,-8],[-16,-1],[-15,4],[-18,8],[-16,11],[-11,10],[-7,7],[-6,-1]],
      shine: [[-11,-11],[-7,-14],[-3,-15],[2,-14],[5,-12],[1,-12],[-3,-13],[-6,-10],[-9,-9]],
    },
    shag: {
      crest: [[-14,-6],[-17,-9],[-14,-11],[-16,-14],[-10,-15],[-9,-18],[-5,-17],[-1,-19],[2,-16],[6,-17],[8,-14],[12,-14],[10,-11],[12,-8],[8,-7],[8,-3],[5,-6],[3,-5],[0,-9],[-3,-6],[-6,-9],[-8,-5],[-11,-6]],
      neck: [[-13,-8],[-17,-6],[-16,-1],[-20,2],[-17,3],[-20,7],[-17,8],[-18,13],[-13,11],[-11,14],[-7,9],[-7,1]],
      shine: [[-13,-12],[-10,-13],[-7,-16],[-6,-13],[-1,-16],[2,-14],[5,-14],[8,-11],[3,-12],[0,-11],[-3,-13],[-7,-11],[-11,-10]],
    },
    ridge: {
      crest: [[-15,-6],[-14,-12],[-10,-14],[-7,-17],[-3,-16],[0,-18],[4,-16],[8,-16],[8,-13],[12,-11],[12,-8],[9,-8],[7,-6],[4,-9],[1,-7],[-3,-9],[-7,-7],[-10,-5]],
      neck: [[-12,-9],[-17,-5],[-16,-1],[-19,2],[-16,3],[-19,7],[-16,8],[-17,12],[-12,11],[-7,8],[-5,0]],
      shine: [[-11,-11],[-7,-14],[-4,-15],[0,-15],[5,-14],[8,-11],[4,-12],[0,-12],[-5,-12],[-8,-9]],
    },
    silk: {
      crest: [[-14,-9],[-13,-13],[-9,-16],[-2,-17],[5,-16],[10,-13],[13,-9],[10,-7],[7,-7],[5,-10],[1,-11],[-4,-8],[-8,-6],[-12,-6]],
      neck: [[-13,-9],[-17,-3],[-16,3],[-18,9],[-19,14],[-16,15],[-12,13],[-7,9],[-5,2]],
      shine: [[-11,-12],[-8,-14],[-2,-15],[4,-14],[9,-11],[4,-12],[-2,-13],[-7,-10],[-10,-9]],
    },
  };

  const ears = {
    floppy: [[-2,-2],[-2,-5],[1,-7],[4,-6],[6,-1],[6,4],[4,9],[1,10],[-2,7],[-3,3]],
    sail: [[-3,2],[-4,-3],[-4,-10],[-1,-14],[2,-11],[5,-5],[4,0],[2,3]],
    sideways: [[-1,3],[-3,-1],[-6,-8],[-6,-11],[-3,-12],[1,-9],[5,-4],[5,1],[2,4]],
    pompon: [[-3,-1],[-4,-4],[-2,-8],[2,-9],[5,-6],[4,-2],[6,1],[4,5],[0,6],[-3,3]],
    fold: [[-3,3],[-3,-3],[-1,-7],[3,-9],[6,-6],[5,-3],[5,1],[3,4],[-1,5]],
    tuft: [[-4,1],[-5,-3],[-3,-5],[-4,-9],[-1,-8],[0,-12],[3,-7],[5,-6],[5,-2],[3,3],[-1,4]],
    peak: [[-3,3],[-4,-2],[-4,-9],[-2,-13],[2,-10],[5,-6],[5,0],[3,4],[0,5]],
    curtain: [[-3,-1],[-1,-6],[3,-8],[6,-4],[6,4],[5,11],[2,14],[-1,12],[-3,8],[-3,3]],
  };

  const profiles = {
    round: [[-13,-4],[-11,-9],[-7,-12],[-1,-13],[5,-12],[10,-8],[12,-3],[12,0],[15,2],[15,7],[12,10],[6,12],[-1,12],[-7,10],[-11,7],[-13,2]],
    wedge: [[-13,-7],[-10,-11],[-5,-13],[2,-13],[8,-10],[11,-6],[12,0],[15,2],[15,6],[13,9],[8,10],[3,12],[-4,12],[-10,9],[-13,4]],
    broad: [[-14,-6],[-11,-11],[-5,-13],[3,-13],[10,-9],[12,-4],[12,-1],[15,1],[16,5],[14,9],[9,11],[2,11],[-5,11],[-11,8],[-14,4]],
    soft: [[-13,-5],[-10,-10],[-6,-13],[1,-14],[8,-11],[11,-7],[11,-2],[14,1],[14,6],[12,9],[7,11],[1,12],[-5,11],[-10,8],[-13,4]],
    long: [[-13,-6],[-10,-11],[-4,-13],[2,-13],[8,-10],[11,-5],[12,0],[15,3],[15,7],[12,11],[7,13],[1,12],[-5,11],[-10,7],[-12,2]],
    shag: [[-14,-5],[-12,-9],[-6,-13],[1,-14],[9,-10],[11,-6],[12,-2],[15,1],[15,5],[17,8],[14,8],[12,11],[7,12],[0,13],[-5,11],[-9,11],[-8,9],[-13,8],[-12,6],[-15,4]],
    angular: [[-13,-6],[-10,-11],[-4,-13],[2,-13],[8,-11],[12,-7],[12,-2],[15,0],[15,6],[12,9],[8,11],[2,12],[-5,11],[-10,9],[-13,5]],
    slender: [[-12,-5],[-10,-10],[-5,-12],[2,-13],[7,-11],[11,-7],[12,-2],[14,1],[15,5],[13,9],[8,11],[2,12],[-4,11],[-8,8],[-12,4]],
  };

  const bodyMarks = {
    chest: [[1,-2],[7,-5],[11,-4],[11,1],[5,6],[-1,6],[-3,4]],
    saddle: [[-15,-6],[-10,-7],[-4,-7],[1,-6],[1,-3],[-2,1],[-7,3],[-14,3],[-16,0]],
    bib: [[-2,-3],[4,-6],[10,-7],[11,-3],[9,1],[5,5],[-2,5],[-2,3]],
    puff: [[-11,-3],[-8,-6],[-3,-6],[1,-4],[3,0],[1,3],[-3,5],[-9,4],[-12,1]],
    blaze: [[0,-6],[8,-7],[11,-4],[11,0],[8,3],[4,5],[0,3],[-1,0]],
    mask: [[-12,-5],[-4,-7],[3,-6],[9,-7],[11,-5],[8,-1],[0,3],[-8,3],[-13,1]],
    belt: [[-14,-4],[-9,-7],[-5,-7],[-6,-3],[-4,0],[-5,5],[-11,5],[-14,2]],
  };

  function drawLeg(ctx, colors, x, root, foot, width, hind, near, stocking) {
    const lean = hind ? -2 : 1;
    const hock = foot - (hind ? 9 : 7);
    const shape = [
      [-width, root], [width, root], [width + lean, hock], [width - 1, foot - 5],
      [width + 1, foot - 3], [width + 1, foot - 1], [width - 1, foot],
      [-width, foot], [-width - 1, foot - 1], [-width - 1, foot - 4], [lean - width, hock],
    ];
    piece(ctx, colors.ink, near ? colors.coat : colors.shade, x, 0, shape);
    if (stocking) {
      polygon(ctx, near ? colors.socks : colors.light, x, 0, [
        [lean - width + 1, hock], [-width + 1, hock - 1], [width + lean - 1, hock],
        [width - 1, foot - 4], [-width, foot - 4],
      ]);
    }
    cell(ctx, colors.hoof, x - width, foot - 3, width * 2 + 1, 2);
    cell(ctx, near ? colors.light : colors.shade, x - width + 1, foot - 3, width - 1, 1);
  }

  function drawEye(ctx, colors, x, y, width, height, slant = 0) {
    polygon(ctx, colors.ink, x, y, [
      [0,2], [2,0], [width - 2,slant], [width,2], [width,height - 2],
      [width - 2,height], [1,height - 1], [0,height - 2],
    ]);
    polygon(ctx, '#fff8ed', x, y, [
      [1,2], [2,1], [width - 2,slant + 1], [width - 1,2],
      [width - 1,height - 2], [width - 2,height - 1], [2,height - 1], [1,height - 2],
    ]);
    cell(ctx, colors.eye, x + width - 4, y + 2, 3, height - 3);
    cell(ctx, colors.ink, x + width - 3, y + 2, 2, height - 4);
    cell(ctx, '#fff9f2', x + width - 4, y + 2, 2, 2);
  }

  function drawPony(ctx, design) {
    const { colors: c, form } = design;
    const {
      hip, shoulder, top, belly, hx, hy, profile, nearEar, farEar, mane, tail, mark, legWidth, stocking, face,
    } = form;
    const tailArt = tails[tail];
    const hair = manes[mane];
    const y = top + 3;
    piece(ctx, c.ink, c.mane, hip, y, tailArt.shape);
    polygon(ctx, c.trace, hip, y, tailArt.shade);
    polygon(ctx, c.glint, hip, y, tailArt.shine);

    drawLeg(ctx, c, hip + 5, belly - 4, 50, legWidth - 1, true, false, stocking);
    drawLeg(ctx, c, shoulder + 4, belly - 7, 50, legWidth - 1, false, false, stocking);
    drawLeg(ctx, c, hip + 1, belly - 5, 53, legWidth, true, true, stocking);
    drawLeg(ctx, c, shoulder, belly - 5, 53, legWidth, false, true, stocking);

    const body = [
      [hip - 5,top + 4],[hip - 3,top + 1],[hip + 2,top - 1],[hip + 9,top - 1],
      [shoulder - 9,top + 1],[shoulder - 5,top - 2],[shoulder - 3,hy + 6],
      [shoulder + 3,hy + 5],[shoulder + 8,hy + 9],[shoulder + 8,top + 4],
      [shoulder + 6,belly - 4],[shoulder + 2,belly],[shoulder - 4,belly + 1],
      [shoulder - 10,belly - 1],[hip + 7,belly - 1],[hip + 3,belly + 1],
      [hip - 2,belly - 2],[hip - 5,belly - 6],
    ];
    piece(ctx, c.ink, c.coat, 0, 0, body);
    polygon(ctx, c.shade, 0, 0, [
      [hip - 3,belly - 6],[hip + 2,belly - 4],[hip + 8,belly - 4],
      [shoulder - 8,belly - 4],[shoulder - 3,belly - 2],[shoulder + 2,belly - 3],
      [shoulder + 5,belly - 6],[shoulder + 3,belly - 2],[shoulder - 3,belly],
      [shoulder - 10,belly - 2],[hip + 7,belly - 2],[hip + 2,belly],[hip,belly - 2],
    ]);
    cell(ctx, c.light, hip + 1, top + 1, 7, 1);
    cell(ctx, c.light, hip - 1, top + 2, 3, 1);
    if (bodyMarks[mark]) {
      polygon(ctx, c.mark, Math.round((hip + shoulder) / 2), top + 7, bodyMarks[mark]);
    } else {
      const spots = [
        [hip + 1,top + 3,3],[hip + 5,top + 7,4],[hip + 10,top + 3,3],
        [shoulder - 10,top + 6,3],[shoulder - 5,top + 3,2],[hip + 10,top + 9,2],
      ];
      for (const [x,y,size] of spots) {
        cell(ctx, c.mark, x, y, size, 2);
        if (size > 2) cell(ctx, c.mark, x + 1, y + 2, size - 2, 1);
      }
    }
    if (mark === 'puff') {
      cell(ctx, c.light, hip + 6, top + 4, 3, 1);
      cell(ctx, c.light, hip + 10, top + 3, 2, 2);
      cell(ctx, c.light, hip + 13, top + 5, 3, 1);
    }

    piece(ctx, c.ink, c.mane, hx, hy, hair.neck);
    polygon(ctx, c.trace, hx, hy, [
      [-16,0],[-12,3],[-11,8],[-13,10],[-11,7],[-9,5],[-12,2],[-13,0],
    ]);

    piece(ctx, c.ink, c.shade, hx + 8, hy - 8, ears[farEar]);
    piece(ctx, c.ink, c.coat, hx, hy, profiles[profile]);
    polygon(ctx, c.shade, hx, hy, [
      [-11,3],[-7,7],[-2,9],[4,9],[9,9],[13,6],[12,8],[8,10],
      [3,11],[-2,11],[-7,9],[-10,7],
    ]);

    if (face === 'stripe') {
      polygon(ctx, c.light, hx, hy, [
        [1,-10],[7,-9],[7,-5],[6,-1],[8,4],[6,8],[1,8],[-1,5],[2,0],[2,-5],
      ]);
    } else if (face === 'patch') {
      polygon(ctx, c.mark, hx, hy, [
        [-7,-7],[-2,-8],[4,-6],[6,-2],[4,2],[2,5],[-2,7],[-7,4],[-8,-1],
      ]);
    } else if (face === 'mask') {
      polygon(ctx, c.light, hx, hy, [
        [-11,-2],[-6,-3],[-2,-1],[2,-4],[6,-4],[7,-1],[11,-4],[12,-1],[11,4],
        [13,5],[11,8],[6,10],[-2,9],[-8,6],[-11,4],
      ]);
    } else if (face === 'freckles') {
      cell(ctx, c.mark, hx - 6, hy - 5, 2, 2);
      cell(ctx, c.mark, hx - 9, hy + 2, 3, 2);
      cell(ctx, c.mark, hx + 2, hy + 6, 1, 1);
    }

    polygon(ctx, c.muzzle, hx, hy, [
      [4,2],[8,1],[12,1],[14,3],[14,6],[12,8],[9,10],
      [4,10],[1,8],[1,5],
    ]);
    cell(ctx, c.light, hx + 6, hy + 3, 5, 1);
    cell(ctx, c.ink, hx + 11, hy + 4, 2, 1);
    cell(ctx, c.ink, hx + 8, hy + 8, 4, 1);
    cell(ctx, c.ink, hx + 7, hy + 7, 1, 1);
    cell(ctx, c.cheek, hx - 6, hy + 5, 4, 1);
    if (face === 'patch') cell(ctx, c.muzzle, hx - 5, hy + 7, 2, 1);

    drawEye(ctx, c, hx + 7, hy - 5, 5, 6);
    drawEye(ctx, c, hx - 4, hy - 5, 8, 8, form.glance ?? 0);

    const lowHair = mane === 'shag' ? -1 : 0;
    piece(ctx, c.ink, c.mane, hx, hy + lowHair, hair.crest);
    polygon(ctx, c.glint, hx, hy + lowHair, hair.shine);
    if (mane === 'curls') {
      cell(ctx, c.glint, hx + 3, hy - 15, 3, 2);
      cell(ctx, c.glint, hx + 7, hy - 10, 2, 2);
      cell(ctx, c.glint, hx - 16, hy, 1, 2);
    }

    const earX = hx - (form.earBack ?? 10);
    const earY = hy - (form.earHeight ?? 8);
    const earColor = ['floppy','curtain','tuft','pompon'].includes(nearEar) ? c.mane : c.coat;
    piece(ctx, c.ink, earColor, earX, earY, ears[nearEar]);
    if (nearEar === 'floppy' || nearEar === 'curtain') {
      polygon(ctx, c.trace, earX, earY, [[2,-4],[4,-2],[4,5],[2,9],[0,8],[1,4],[0,1]]);
      polygon(ctx, c.glint, earX, earY, [[-1,-1],[0,-3],[2,-4],[2,-2],[1,0],[1,3],[0,4]]);
    } else {
      polygon(ctx, c.cheek, earX, earY, inset(ears[nearEar], 2));
      cell(ctx, earColor, earX, earY - 2, 2, 2);
    }

    if (mane === 'silk') {
      polygon(ctx, c.glint, hx, hy, [
        [-15,1],[-13,2],[-14,6],[-15,11],[-16,12],[-16,8],[-15,5],
      ]);
      cell(ctx, c.glint, hx - 12, hy + 7, 1, 3);
    }
  }

  const group = [
    {
      id:'d01', name:'垂蜜', description:'宽额圆脸、两侧低垂的软耳，短躯配刷状马尾。',
      form:{ hip:18,shoulder:41,top:31,belly:44,hx:43,hy:25,profile:'round',nearEar:'floppy',farEar:'fold',mane:'roll',tail:'brush',mark:'chest',legWidth:5,stocking:false,face:'muzzle',earBack:12,earHeight:4 },
      colors:{ ink:'#583543',coat:'#e9ab73',shade:'#c47c63',light:'#ffe1af',muzzle:'#f6c892',mane:'#9c5a62',trace:'#713e52',glint:'#d2837d',cheek:'#d88175',hoof:'#764758',socks:'#ffe3ac',mark:'#f7cc9e',eye:'#8e6853' },
    },
    {
      id:'d02', name:'风哨', description:'高挑立耳、窄脸和细长小腿，鬃尾都向后掠。',
      form:{ hip:19,shoulder:40,top:30,belly:41,hx:41,hy:24,profile:'wedge',nearEar:'sail',farEar:'fold',mane:'wind',tail:'pennant',mark:'saddle',legWidth:3,stocking:true,face:'stripe',earBack:11,earHeight:5,glance:1 },
      colors:{ ink:'#304b56',coat:'#93b7ac',shade:'#5d928a',light:'#bce2ce',muzzle:'#a6cdbe',mane:'#425e79',trace:'#344d63',glint:'#698ca1',cheek:'#c2b2a8',hoof:'#3c5e69',socks:'#aedbd5',mark:'#6f9f9e',eye:'#639e87' },
    },
    {
      id:'d03', name:'奶油卷', description:'外张的高耳、低矮长躯和宽蹄，马尾卷成圈。',
      form:{ hip:16,shoulder:42,top:34,belly:47,hx:44,hy:26,profile:'broad',nearEar:'sideways',farEar:'peak',mane:'crop',tail:'curl',mark:'bib',legWidth:5,stocking:true,face:'stripe',earBack:11,earHeight:7 },
      colors:{ ink:'#61403c',coat:'#dfa775',shade:'#bd7d58',light:'#ffedcb',muzzle:'#fae2bd',mane:'#866751',trace:'#6b4a47',glint:'#b38d68',cheek:'#dd9a8b',hoof:'#9f6858',socks:'#fae2bb',mark:'#fae6c7',eye:'#9c724f' },
    },
    {
      id:'d04', name:'绒球', description:'卷团鬃毛和球状马尾，圆眼短脸搭配细腿。',
      form:{ hip:21,shoulder:40,top:30,belly:41,hx:41,hy:25,profile:'soft',nearEar:'pompon',farEar:'fold',mane:'curls',tail:'pompon',mark:'puff',legWidth:3,stocking:true,face:'muzzle',earBack:12,earHeight:4 },
      colors:{ ink:'#644c70',coat:'#dfb9d8',shade:'#b28ebf',light:'#f3ddeb',muzzle:'#efcfe1',mane:'#9873b1',trace:'#79588a',glint:'#ccb0dd',cheek:'#cb95b6',hoof:'#775a8a',socks:'#f0d5e8',mark:'#eacde8',eye:'#8663a4' },
    },
    {
      id:'d05', name:'陨斑', description:'窄长额线与折角耳，浅色斑点、细长蹄和流线马尾。',
      form:{ hip:19,shoulder:40,top:29,belly:41,hx:43,hy:24,profile:'long',nearEar:'fold',farEar:'fold',mane:'split',tail:'swish',mark:'spots',legWidth:3,stocking:false,face:'patch',earBack:11,earHeight:8,glance:1 },
      colors:{ ink:'#463f52',coat:'#dcdceb',shade:'#a6a6bf',light:'#fbf3f6',muzzle:'#d6cbdf',mane:'#5f596f',trace:'#50495e',glint:'#9793aa',cheek:'#c59eae',hoof:'#696275',socks:'#f1e7f2',mark:'#79768f',eye:'#6c8ba4' },
    },
    {
      id:'d06', name:'剪影', description:'锯齿额发、翘尖耳与蓬松脸颊，短尾像一簇毛刷。',
      form:{ hip:18,shoulder:41,top:32,belly:44,hx:43,hy:25,profile:'shag',nearEar:'tuft',farEar:'fold',mane:'shag',tail:'tuft',mark:'belt',legWidth:4,stocking:false,face:'freckles',earBack:12,earHeight:5 },
      colors:{ ink:'#414753',coat:'#b4a5bf',shade:'#8f839f',light:'#e2cbd7',muzzle:'#cfb5bc',mane:'#555d76',trace:'#454a65',glint:'#7f90a6',cheek:'#c696a9',hoof:'#596177',socks:'#e5d4de',mark:'#9186a5',eye:'#7998a1' },
    },
    {
      id:'d07', name:'霜围', description:'立耳、双色面罩和厚胸，竖起的长尾像一面羽旗。',
      form:{ hip:19,shoulder:42,top:29,belly:42,hx:43,hy:23,profile:'angular',nearEar:'peak',farEar:'sail',mane:'ridge',tail:'flame',mark:'mask',legWidth:4,stocking:true,face:'mask',earBack:11,earHeight:4 },
      colors:{ ink:'#34445c',coat:'#9db4ca',shade:'#7089aa',light:'#e6eaf4',muzzle:'#d8e5ee',mane:'#63799a',trace:'#4b6083',glint:'#c1d3e8',cheek:'#b8b5cd',hoof:'#586f93',socks:'#d7e5ee',mark:'#7d98b5',eye:'#4f8fac' },
    },
    {
      id:'d08', name:'拾枝', description:'侧边长耳、窄肩细腰与很长的披散马尾。',
      form:{ hip:22,shoulder:41,top:29,belly:41,hx:43,hy:24,profile:'slender',nearEar:'curtain',farEar:'fold',mane:'silk',tail:'veil',mark:'blaze',legWidth:4,stocking:true,face:'muzzle',earBack:12,earHeight:4 },
      colors:{ ink:'#554141',coat:'#bb8970',shade:'#976958',light:'#f4d4a8',muzzle:'#deb699',mane:'#a46c57',trace:'#775047',glint:'#ddb187',cheek:'#c58a82',hoof:'#755650',socks:'#f2cc9d',mark:'#e8b889',eye:'#79906f' },
    },
  ];

  window.PixelPonyDesigns ??= [];
  for (const design of group) {
    window.PixelPonyDesigns.push({
      id: design.id,
      name: design.name,
      group: 'dog',
      description: design.description,
      colors: [design.colors.coat, design.colors.mane, design.colors.muzzle],
      draw(ctx) { drawPony(ctx, design); },
    });
  }
})();

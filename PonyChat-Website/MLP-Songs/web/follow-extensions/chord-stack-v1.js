/* Candidate-local chord-stack layout derived from frozen numbered renderer.
 * Original SHA256: 3d2cce7cbfada5f1f2fd39da132d35388cd2b92a636e65b17518962f9bcb0499.
 * Only canonical-backed chord grouping, display lanes, vertical spacing and
 * chord interaction rectangles differ. Source tokens/pitches/lyrics never change.
 * A source without chords returns the original base render object unchanged.
 * Load before unpitched-heads-v1.js; that tail replaces only declared X placeholders.
 * This file does not install itself into any production frame. */
(function (root) {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  function parse(token) {
    const m = String(token || "0").match(/^(#{1,2}|b{1,2})?([0-7])([',]*)$/);
    return m ? {acc: ({"#":"♯","##":"𝄪",b:"♭",bb:"𝄫"})[m[1]] || "", num: m[2], octave: [...m[3]].reduce((n, c) => n + (c === "'" ? 1 : -1), 0)} : {acc: "", num: "?", octave: 0};
  }
  function rhythm(t) {
    const d = Number(t.durationBeats) || 1;
    const explicit = {whole: 4, half: 2, quarter: 1, eighth: .5, "16th": .25, "32nd": .125, "64th": .0625}[t.noteType];
    const dotted = t.dots || ([.1875, .375, .75, 1.5].some((v) => Math.abs(v - d) < .001) ? 1 : 0);
    const base = explicit || d / (dotted ? 1.5 : 1);
    return {beams: Math.max(0, Math.min(4, Math.round(-Math.log2(base)))), dots: dotted};
  }
  function lyric(t) {
    return (t.lyric || "") + (["begin", "middle"].includes(t.syllabic) && t.lyric ? "-" : "");
  }
  function needsTimingLabel(t) {
    return t.sourceOnlyUntimed === true && Number.isInteger(t.sourceEventIndex);
  }

  const ORIGINAL_RENDERER_SHA256 = "3d2cce7cbfada5f1f2fd39da132d35388cd2b92a636e65b17518962f9bcb0499";
  const canonical = v => v && typeof v === "object" ? (Array.isArray(v) ? v.map(canonical) :
    Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])]))) : v;
  const same = (a, b) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
  const require = (ok, message) => {if (!ok) throw Error(message);};
  const key = t => JSON.stringify([t.sourcePart, t.voice]);
  function absolutePitch(pitch) {
    const m = /^([A-G])(#{1,2}|b{1,2})?(-?\d)$/.exec(pitch || "");
    require(m, "Chord absolute source pitch is missing");
    const alter = [...(m[2] || "")].reduce((n,c) => n+(c === "#" ? 1 : -1),0);
    return (Number(m[3])+1)*12 + {C:0,D:2,E:4,F:5,G:7,A:9,B:11}[m[1]]+alter;
  }
  function headRoom(t) {
    const p = parse(t.token), r = rhythm(t);
    require(p.num !== "?" && p.num !== "0", "A canonical pitched chord has an invalid numbered glyph");
    return {above:Math.max(24, p.octave > 0 ? 29+(p.octave-1)*7 : 0,
      t.tuplet ? 45 : 0, t.tieTo || t.tieStart || t.tieStop ? 43 : 0),
      below:Math.max(6, r.beams ? 11+(r.beams-1)*6 : 0,
        p.octave < 0 ? 19+r.beams*6+(-p.octave-1)*7 : 0)};
  }
  function planSourceChords(data) {
    require(data && Array.isArray(data.tokens) && Array.isArray(data.measures), "Source notation tables missing");
    const declared = data.sourceChordGroups;
    const actualChords = data.tokens.filter(t => t.chordTone === true);
    if (!actualChords.length && (!declared || !declared.groups?.length)) return null;
    require(declared && same(Object.keys(declared).sort(), ["canonicalSha256","groups","schema"])
      && declared.schema === "canonical-source-chord-groups/v1"
      && /^[a-f0-9]{64}$/.test(data.canonicalSha256 || "")
      && declared.canonicalSha256 === data.canonicalSha256 && Array.isArray(declared.groups)
      && declared.groups.length, "Exact canonical chord group binding required");
    const bySource = new Map(), ids = new Set(), physicalIds = new Set(), groupByToken = new Map();
    const partOrder = [];
    for (const t of data.tokens) {
      require(t && typeof t === "object" && typeof t.originalSourceNoteId === "string"
        && t.originalSourceNoteId && !bySource.has(t.originalSourceNoteId)
        && ["string","number"].includes(typeof t.id) && String(t.id) && !ids.has(String(t.id))
        && typeof t.sourcePart === "string" && t.sourcePart && typeof t.voice === "string" && t.voice
        && Number.isInteger(t.sourceNoteIndex) && t.sourceNoteIndex >= 0
        && typeof t.chordTone === "boolean", "Source chord token identity/type is ambiguous");
      require(typeof t.sourcePhysicalId === "string" && t.sourcePhysicalId && !physicalIds.has(t.sourcePhysicalId),
        "Physical source identity is missing or duplicated");
      ids.add(String(t.id)); physicalIds.add(t.sourcePhysicalId); bySource.set(t.originalSourceNoteId,t);
      if (!partOrder.includes(t.sourcePart)) partOrder.push(t.sourcePart);
    }
    const nested = data.measures.flatMap(m => m.tokens || []), seen = new Set();
    require(nested.length === data.tokens.length, "Flat/nested chord source counts differ");
    for (const t of nested) {
      require(!seen.has(t.originalSourceNoteId) && same(t,bySource.get(t.originalSourceNoteId)),
        "Flat/nested chord source payload differs"); seen.add(t.originalSourceNoteId);
    }
    for (const g of declared.groups) {
      require(g && same(Object.keys(g).sort(), ["anchorSourceNoteId","beat","durationBeats","measure",
        "sourceNoteIds","sourcePart","voice"]) && Array.isArray(g.sourceNoteIds) && g.sourceNoteIds.length > 1
        && g.anchorSourceNoteId === g.sourceNoteIds[0] && new Set(g.sourceNoteIds).size === g.sourceNoteIds.length,
        "Canonical chord anchor/group membership is incomplete");
      const members = g.sourceNoteIds.map(id => bySource.get(id));
      require(members.every(Boolean), "A canonical chord physical head was dropped");
      const anchor = members[0];
      require(anchor.chordTone === false && Number.isInteger(g.measure) && g.measure > 0
        && typeof g.beat === "number" && Number.isFinite(g.beat) && g.beat >= 0
        && typeof g.durationBeats === "number" && Number.isFinite(g.durationBeats) && g.durationBeats > 0,
        "Canonical chord onset/anchor is invalid");
      for (let i=0; i<members.length; i++) {
        const t = members[i];
        require(!groupByToken.has(t.originalSourceNoteId) && t.isRest === false && t.isUnpitched !== true
          && t.chordTone === (i > 0) && t.sourcePart === g.sourcePart && t.voice === g.voice
          && t.measure === g.measure && t.beat === g.beat && t.durationBeats === g.durationBeats
          && (!i || t.sourceNoteIndex > members[i-1].sourceNoteIndex),
          "False chord, mixed voice/onset/duration, or duplicated physical member");
        require(i === 0 || t.lyric === "", "A chord syllable was wrongly copied onto a nonanchor head");
        absolutePitch(t.pitch); headRoom(t);
        groupByToken.set(t.originalSourceNoteId,g);
      }
      const ordered = [...members].sort((a,b) => absolutePitch(b.pitch)-absolutePitch(a.pitch)
        || g.sourceNoteIds.indexOf(a.originalSourceNoteId)-g.sourceNoteIds.indexOf(b.originalSourceNoteId));
      let offset = 0;
      const placements = new Map();
      for (let i=0;i<ordered.length;i++) {
        if (i) offset += headRoom(ordered[i-1]).below+headRoom(ordered[i]).above+8;
        placements.set(ordered[i].originalSourceNoteId,{offset,slot:ordered.length-1-i,room:headRoom(ordered[i])});
      }
      for (const t of members) groupByToken.set(t.originalSourceNoteId,{...placements.get(t.originalSourceNoteId),
        span:offset,topRoom:headRoom(ordered[0]).above,anchor:g.anchorSourceNoteId,group:g});
    }
    require(actualChords.every(t => groupByToken.has(t.originalSourceNoteId)), "Canonical chord membership is missing");
    const sourceSlurs=data.sourceSlurs;
    if(sourceSlurs) require(sourceSlurs.schema==="canonical-source-slurs/v1" && sourceSlurs.canonicalSha256===data.canonicalSha256
      && Array.isArray(sourceSlurs.curves) && sourceSlurs.curves.every(c=>bySource.has(c.fromSourceNoteId)
        && bySource.has(c.toSourceNoteId) && bySource.get(c.fromSourceNoteId).sourcePart===c.sourcePart
        && bySource.get(c.toSourceNoteId).sourcePart===c.sourcePart
        && bySource.get(c.fromSourceNoteId).voice===c.voice && bySource.get(c.toSourceNoteId).voice===c.voice),
      "Source slur display endpoints are absent or in another voice");
    return {bySource,groupByToken,partOrder,sourceSlurs:sourceSlurs?.curves || []};
  }
  function rowChordLanes(frags,plan,timingLabel) {
    const tokens = frags.flatMap(f => f.measure.tokens), laneKeys = [...new Set(tokens.map(key))];
    laneKeys.sort((a,b) => {const [ap,av]=JSON.parse(a),[bp,bv]=JSON.parse(b);
      return plan.partOrder.indexOf(ap)-plan.partOrder.indexOf(bp) || av.localeCompare(bv,undefined,{numeric:true});});
    const metrics = laneKeys.map(k => {
      const members = tokens.filter(t => key(t) === k);
      const chord = members.map(t => plan.groupByToken.get(t.originalSourceNoteId)).filter(Boolean);
      const span = Math.max(0,...chord.map(p => p.span));
      const sourceSlur=plan.sourceSlurs.some(c=>JSON.stringify([c.sourcePart,c.voice])===k
        && frags.some(f=>f.measure.measure>=c.fromMeasure && f.measure.measure<=c.toMeasure));
      const topExtra = Math.max(0,...chord.map(p => p.topRoom-32))+(sourceSlur ? 20 : 0);
      return {key:k,span,topExtra,height:(timingLabel ? 128 : 112)+span+topExtra};
    });
    let offset=0;
    for (const m of metrics) {m.offset=offset;offset+=m.height;}
    return {metrics,total:offset};
  }

  function layout(data, available, scale = 1, textWidth = (s) => s.length * 7, chordPlan = null) {
    const width = Math.max(180, Math.floor(available)), inset = 14 * scale;
    const room = width - inset * 2, fragments = [];
    function fragmentTitleWidth(measure,start) {
      const omitted=measure.tokens.length && measure.tokens.every(t=>t.scoreOmitted);
      const untimed=measure.tokens.length && measure.tokens.every(t=>t.sourceOnlyUntimed===true);
      const title=`${measure.measure===0 ? "起拍" : measure.measure}${omitted ? " · 未演奏" : untimed ? " · 未定位" : ""}${start>0 ? " · 续" : ""}`;
      const prior=data.measures[data.measures.indexOf(measure)-1];
      const meter=start===0 && (measure===data.measures[0] || measure.timeSignature!==prior?.timeSignature);
      return textWidth(title,11*scale)+(meter ? textWidth(measure.timeSignature || "",11*scale)+18*scale : 10*scale);
    }
    for (const measure of data.measures || []) {
      const snap = (v) => Math.round(v*1000)/1000;
      const end = snap(Math.max(measure.beatsPerMeasure || 4, ...measure.tokens.map((t) => t.beat + t.durationBeats)));
      const points = new Set([0, end]);
      for (let beat = 1; beat < end; beat++) points.add(beat);
      measure.tokens.forEach((t) => {points.add(snap(t.beat)); points.add(snap(t.beat + t.durationBeats));});
      const sorted = [...points].sort((a, b) => a-b), units = [];
      for (let i = 0; i < sorted.length - 1; i++) {
        const start = sorted[i], stop = sorted[i+1];
        const starts = measure.tokens.filter((t) => Math.abs(t.beat - start) < .001);
        const min = Math.max(22 * scale * Math.sqrt(stop-start), ...starts.map((t) => Math.max(34*scale, textWidth(lyric(t), 13*scale) + 14*scale, parse(t.token).acc ? 44*scale : 0,
          needsTimingLabel(t) ? textWidth("未定位", 11*scale)+14*scale : 0)));
        units.push({start, end: stop, width: Math.min(room - 16*scale, min)});
      }
      let chunk = [], size = 16*scale;
      for (const unit of units) {
        if (chunk.length && size + unit.width > room) {
          fragments.push({measure, units: chunk, width: Math.max(size,fragmentTitleWidth(measure,chunk[0].start))}); chunk = []; size = 16*scale;
        }
        chunk.push(unit); size += unit.width;
      }
      if (chunk.length) fragments.push({measure, units: chunk, width: Math.max(size,fragmentTitleWidth(measure,chunk[0].start))});
    }
    const rows = [];
    let row = [], used = 0;
    for (const fragment of fragments) {
      if (row.length && used + fragment.width > room) {rows.push(row); row = []; used = 0;}
      row.push(fragment); used += fragment.width;
    }
    if (row.length) rows.push(row);
    let y = 8*scale;
    const placed = rows.map((frags, ri) => {
      const timingLabel = frags.some((f) => f.measure.tokens.some((t) => needsTimingLabel(t) && lyric(t)));
      const chordLanes = rowChordLanes(frags,chordPlan,timingLabel);
      const lanes = chordLanes.metrics.length;
      // Only new unlocated notes carrying lyrics need a second text baseline.
      // Leave room before the next voice's high triplet mark as well as digits.
      const laneHeight = Math.max(...chordLanes.metrics.map(m => m.height));
      const height = (36 + chordLanes.total)*scale;
      const raw = frags.reduce((s, f) => s + f.width, 0);
      const stretch = Math.min(1.35, room/raw);
      let x = inset;
      const placements = frags.map((f) => {
        const start = f.units[0].start, end = f.units.at(-1).end;
        let ux = x + 8*scale;
        const units = f.units.map((u) => {const placed = {...u, x: ux, width: u.width*stretch}; ux += placed.width; return placed;});
        const out = {...f, x, width: f.width*stretch, units, start, end}; x += out.width; return out;
      });
      const r = {index: ri, y, height, lanes, laneHeight, chordLanes:chordLanes.metrics, fragments: placements}; y += height; return r;
    });
    return {width, height: y + 10*scale, rows: placed, scale};
  }
  function renderChord(data, available, scale = 1, chordPlan) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const geometry = layout(data, available, scale, (s, fs) => {ctx.font = `${fs}px Arial`; return ctx.measureText(s).width;}, chordPlan);
    const s = scale, pieces = new Map();
    const text = (x, y, value, cls, extra = "") => `<text x="${x}" y="${y}" class="${cls}" ${extra}>${esc(value)}</text>`;
    const line = (x1, y1, x2, y2, cls = "jp-beam") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${cls}"/>`;
    let body = "";
    for (const row of geometry.rows) {
      body += `<g class="jp-row" data-row="${row.index}"><rect class="jp-row-bg" x="0" y="${row.y}" width="${geometry.width}" height="${row.height-4*s}" rx="10"/>`;
      for (const f of row.fragments) {
        const m = f.measure;
        const at = (beat) => {
          beat = Math.round(beat*1000)/1000;
          if (beat >= f.end) return f.x + f.width - 8*s;
          const u = f.units.find((u) => beat >= u.start-.0001 && beat < u.end) || f.units[0];
          return u.x + u.width * (beat-u.start)/(u.end-u.start);
        };
        const numY = row.y + 18*s;
        const omitted = m.tokens.length && m.tokens.every((token) => token.scoreOmitted);
        const untimed = m.tokens.length && m.tokens.every((token) => token.sourceOnlyUntimed === true);
        const measureLabel = m.measure === 0 ? "起拍" : m.measure;
        body += text(f.x+5*s, numY, `${measureLabel}${omitted ? " · 未演奏" : untimed ? " · 未定位" : ""}${f.start > 0 ? " · 续" : ""}`, "jp-measure-number");
        if (f.start === 0 && (m === data.measures[0] || m.timeSignature !== data.measures[data.measures.indexOf(m)-1]?.timeSignature)) {
          body += text(f.x+f.width-6*s, numY, m.timeSignature || "", "jp-meter", 'text-anchor="end"');
        }
        for (let lane = 0; lane < row.lanes; lane++) {
          const metric = row.chordLanes[lane];
          const topBase = row.y+(64+metric.offset+metric.topExtra)*s;
          const laneBottom = topBase+metric.span*s;
          body += line(f.x, topBase-27*s, f.x, laneBottom+14*s, f.start > 0 ? "jp-bar jp-continuation" : "jp-bar");
          body += line(f.x+f.width, topBase-27*s, f.x+f.width, laneBottom+14*s, f.end < m.beatsPerMeasure ? "jp-bar jp-continuation" : "jp-bar");
          const laneTokens = m.tokens.filter((t) => key(t) === metric.key && t.beat < f.end-.001 && t.beat+t.durationBeats > f.start+.001);
          const previousBySlot = new Map();
          for (const t of laneTokens) {
            const stack = chordPlan.groupByToken.get(t.originalSourceNoteId);
            const base = laneBottom+(stack ? stack.offset-stack.span : 0)*s;
            const slot = stack ? stack.slot : 0;
            const previous = previousBySlot.get(slot);
            const start = Math.max(t.beat, f.start), end = Math.min(t.beat+t.durationBeats, f.end);
            const x = at(start), right = at(end), u = f.units.find((u) => Math.abs(u.start-start)<.001) || f.units[0];
            const cx = x + Math.min(u.width, right-x)/2;
            const continued = t.beat < f.start;
            const label = lyric(t), id = t.id ?? t.eventIndex;
            const parsed = parse(t.token);
            const split = continued || end < t.beat+t.durationBeats-.001;
            const shown = split ? {...t, durationBeats:end-start, noteType:"", dots:0} : t;
            const r = rhythm(shown);
            const region = {x, right, cx, base, row, start, end, t};
            if (!pieces.has(String(id))) pieces.set(String(id), []);
            pieces.get(String(id)).push(region);
            const playable = !t.scoreOmitted && !t.skipCursorHighlight && typeof t.time === "number" && Number.isFinite(t.time);
            const timingNotice = t.scoreOmitted ? "（录音未演奏，仅供阅读）" : t.sourceOnlyUntimed === true ? "（时间未定位，仅供阅读）" : "";
            const alt = `${m.measure === 0 ? "起拍" : `第 ${m.measure} 小节`}，${t.isRest ? "休止" : t.token}${t.lyric ? "，"+t.lyric : ""}${timingNotice}`;
            const interaction = playable ? `data-time="${t.time}" role="button" tabindex="0"` : 'role="img"';
            body += `<g class="jp-note${t.isRest ? " jp-rest" : ""}${!playable ? " jp-readonly" : ""}" data-id="${esc(id)}"${Number.isInteger(t.eventIndex) ? ` data-event-index="${t.eventIndex}"` : ""} ${interaction} data-row="${row.index}" data-start="${start}" data-end="${end}" aria-label="${esc(alt)}"${stack ? ` data-source-physical-id="${esc(t.sourcePhysicalId)}" data-chord-anchor="${esc(stack.anchor)}" data-chord-slot="${slot}"` : ""}>`;
            body += `<rect class="jp-bg" x="${x}" y="${base-32*s}" width="${Math.max(8, right-x-2*s)}" height="${(stack ? 32+stack.room.below+6 : 91)*s}" rx="7"/>`;
            body += `<rect class="jp-progress" x="${x}" y="${laneBottom+58*s}" width="0" height="${3*s}" rx="1.5" data-width="${Math.max(8, right-x-2*s)}"/>`;
            body += text(cx, base, parsed.num, "jp-digit", 'text-anchor="middle"');
            if (!t.isRest) {
              if (parsed.acc) body += text(cx-15*s, base-4*s, parsed.acc, "jp-accidental", 'text-anchor="middle"');
              for (let oct = 0; oct < Math.abs(parsed.octave); oct++) {
                const dy = parsed.octave > 0 ? -27-oct*7 : 17+r.beams*6+oct*7;
                body += `<circle cx="${cx}" cy="${base+dy*s}" r="${2*s}" class="jp-dot"/>`;
              }
            }
            // Long notes/rests occupy readable beat slots; no overlapping filler 0s.
            for (let beat = Math.floor(start)+1; beat < end-.001; beat++) {
              if (shown.durationBeats < 2) break;
              const nextUnit = f.units.find((u) => u.start === beat);
              if (nextUnit) body += text(nextUnit.x+nextUnit.width/2, base, t.isRest ? "0" : "—", "jp-digit", 'text-anchor="middle"');
            }
            if (shown.durationBeats < 2) {
              for (let dot = 0; dot < r.dots; dot++) body += `<circle cx="${cx+(14+dot*6)*s}" cy="${base-8*s}" r="${2*s}" class="jp-dot"/>`;
            }
            for (let b = 0; b < r.beams; b++) body += line(cx-9*s, base+(9+b*6)*s, cx+9*s, base+(9+b*6)*s);
            if (!continued) {
              if (label) body += text(cx, laneBottom+49*s, label, "jp-lyric", 'text-anchor="middle"');
              if (needsTimingLabel(t)) body += text(cx, laneBottom+(label ? 65 : 49)*s, "未定位", "jp-timing-notice", 'text-anchor="middle"');
              if (t.tuplet) body += text(cx, base-39*s, t.tuplet.actual, "jp-tuplet", 'text-anchor="middle"');
            }
            body += "</g>";
            // Join short-note beams by beat, never across a rest or another voice.
            if (previous && Math.abs(previous.base-base)<1 && !t.isRest && !previous.t.isRest && Math.abs(previous.end-start)<.001 && Math.floor(previous.start) === Math.floor(start)) {
              const count = Math.min(r.beams, rhythm(previous.t).beams);
              for (let b = 0; b < count; b++) body += line(previous.cx+9*s, base+(9+b*6)*s, cx-9*s, base+(9+b*6)*s);
            }
            if (t.isRest) previousBySlot.clear();
            else previousBySlot.set(slot,region);
          }
        }
      }
      body += "</g>";
    }
    function arc(x1, y1, x2, y2) {
      return `<path class="jp-tie" d="M ${x1} ${y1} C ${x1+(x2-x1)*.3} ${Math.min(y1,y2)-13*s}, ${x1+(x2-x1)*.7} ${Math.min(y1,y2)-13*s}, ${x2} ${y2}"/>`;
    }
    // Tied continuations also represent a sustained note split by mobile reflow.
    for (const segments of pieces.values()) {
      if (segments[0]?.t.isRest) continue;
      for (let i = 1; i < segments.length; i++) {
        const a = segments[i-1], b = segments[i];
        body += arc(a.cx+8*s, a.base-33*s, geometry.width-12*s, a.base-33*s);
        body += arc(12*s, b.base-33*s, b.cx-8*s, b.base-33*s);
      }
    }
    for (const t of data.tokens || []) {
      if (!t.tieTo) continue;
      const a = pieces.get(String(t.id))?.at(-1), b = pieces.get(String(t.tieTo))?.[0];
      if (!a || !b) continue;
      if (a.row.index === b.row.index) body += arc(a.cx+8*s, a.base-33*s, b.cx-8*s, b.base-33*s);
      else {
        body += arc(a.cx+8*s, a.base-33*s, geometry.width-12*s, a.base-33*s);
        body += arc(12*s, b.base-33*s, b.cx-8*s, b.base-33*s);
      }
    }
    // Source melisma curves include every intermediate reflow row. Their
    // source endpoints are not interpreted as recorded attacks or pitch Gold.
    for(const c of chordPlan.sourceSlurs) {
      const from=chordPlan.bySource.get(c.fromSourceNoteId),to=chordPlan.bySource.get(c.toSourceNoteId);
      const a=pieces.get(String(from.id))?.[0],b=pieces.get(String(to.id))?.[0];
      require(a && b && a.row.index<=b.row.index,"Source slur endpoint is absent from rendered physical scope");
      for(let ri=a.row.index;ri<=b.row.index;ri++) {
        const row=geometry.rows[ri],metric=row.chordLanes.find(m=>m.key===JSON.stringify([c.sourcePart,c.voice]));
        require(metric,"Source slur intermediate voice lane is absent");
        const y=row.y+(64+metric.offset+metric.topExtra-38)*s;
        const x1=ri===a.row.index ? a.cx+8*s : 14*s,x2=ri===b.row.index ? b.cx-8*s : geometry.width-14*s;
        const id=[c.sourcePart,c.voice,c.number,c.fromSourceNoteId,c.toSourceNoteId].join(":");
        body+=`<path class="jp-source-slur" data-source-slur-id="${esc(id)}" data-from-source-id="${esc(c.fromSourceNoteId)}" data-to-source-id="${esc(c.toSourceNoteId)}" data-source-row="${ri}" d="M ${x1} ${y} C ${x1+(x2-x1)*.3} ${y-13*s}, ${x1+(x2-x1)*.7} ${y-13*s}, ${x2} ${y}"/>`;
      }
    }
    const tonic = String(data.tonic || "C").replace(/^([A-G])b$/, "♭$1").replace(/^([A-G])#$/, "♯$1");
    const hint = "同声部和弦叠排 · 双击音符定位";
    const tempoMap = data.sourceTempoMap;
    const validTempoMap = Array.isArray(tempoMap) && tempoMap.length && tempoMap[0]?.measure === 1 &&
      tempoMap.every((point, index) => Number.isInteger(point.measure) && point.measure >= 1 && Number.isFinite(point.bpm) && point.bpm > 0 &&
        (!index || point.measure > tempoMap[index-1].measure));
    const tempo = validTempoMap ? tempoMap.map((point, index) => {
      const label = esc(`${index ? `第 ${point.measure} 小节 ` : ""}♩ = ${point.bpm}`);
      return point.feel === "swing" ? `<span class="jp-tempo-change">${label}（摇摆）</span>` : label;
    }).join(" · ") : esc(`♩ = ${data.tempo || "—"}`);
    const header = `<div class="jp-head"><strong>1 = ${esc(tonic)}</strong><span>${esc(data.measures?.[0]?.timeSignature || "")}　${tempo}</span><span>${hint}</span></div>`;
    return {html: header + `<svg class="jp-svg" xmlns="http://www.w3.org/2000/svg" width="${geometry.width}" height="${geometry.height}" viewBox="0 0 ${geometry.width} ${geometry.height}" style="--note-size:${24*s}px;--lyric-size:${13*s}px;--small-size:${11*s}px">${body}</svg>`, geometry};
  }
  function create(base) {
    require(typeof base === "function", "Frozen numbered renderer is unavailable");
    return function render(data,available,scale=1) {
      const plan = planSourceChords(data);
      if (!plan) return base(data,available,scale);
      const before = JSON.stringify(data);
      const result = renderChord(data,available,scale,plan);
      require(JSON.stringify(data) === before,"Chord layout mutated physical source data");
      const rendered = [...result.html.matchAll(/<g class="jp-note[^>]* data-id="([^"]*)"/g)].map(m => m[1]);
      require(data.tokens.every(t => rendered.includes(esc(t.id))),"Chord rendering dropped a source physical head");
      return result;
    };
  }
  function createLayout(base) {
    require(typeof base === "function", "Frozen numbered layout is unavailable");
    return function (data,available,scale=1,textWidth) {
      const plan=planSourceChords(data);
      return plan ? layout(data,available,scale,textWidth,plan) : base(data,available,scale,textWidth);
    };
  }
  const api = {create,createLayout,planSourceChords,originalRendererSha256:ORIGINAL_RENDERER_SHA256};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    require(root.MusicNotation,"Frozen notation module is unavailable");
    root.MusicNotation.render=create(root.MusicNotation.render);
    root.MusicNotation.layout=createLayout(root.MusicNotation.layout);
  }
})(typeof window === "undefined" ? {} : window);

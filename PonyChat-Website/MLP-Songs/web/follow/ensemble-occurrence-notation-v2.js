/* Occurrence v2 chord-aware presentation derived from stock notation; no music data mutations.
 * Responsive numbered notation. Geometry and typography use separate units:
 * spacing may expand, but glyphs and lyric syllables are never squashed. */
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
  // A chord stays in its original lane/voice. Pitch order is only vertical presentation.
  function chordInfo(measure, token) {
    const group = measure.tokens.filter(t => !t.isRest && !t.isUnpitched &&
      (t.lane || 0) === (token.lane || 0) && t.sourcePart === token.sourcePart &&
      t.voice === token.voice && t.staff === token.staff && t.beat === token.beat);
    if (token.isRest || token.isUnpitched || group.length < 2) return {depth:1, rank:0};
    if (!group.some(t => t.chordTone === true)) throw Error("Same-voice simultaneous heads require original chord semantics");
    if (!group.every(t => Number.isInteger(t.midi))) throw Error("Source chord absolute pitches required");
    group.sort((a,b) => a.midi-b.midi || String(a.id).localeCompare(String(b.id)));
    return {depth:group.length, rank:group.findIndex(t => t.id === token.id)};
  }
  function fragmentPlacements(geometry) {
    const result=[]; const s=geometry.scale;
    for(const row of geometry.rows) for(const f of row.fragments) for(const t of f.measure.tokens) {
      if(!(t.beat<f.end-.001 && t.beat+t.durationBeats>f.start+.001)) continue;
      const start=Math.max(t.beat,f.start), end=Math.min(t.beat+t.durationBeats,f.end);
      const at=beat=>{if(beat>=f.end)return f.x+f.width-8*s;
        const u=f.units.find(u=>beat>=u.start-.0001&&beat<u.end)||f.units[0];
        return u.x+u.width*(beat-u.start)/(u.end-u.start);};
      const x=at(start),right=at(end),u=f.units.find(u=>Math.abs(u.start-start)<.001)||f.units[0];
      const chord=chordInfo(f.measure,t),base=row.y+(64+row.laneOffsets[t.lane||0]+(row.laneDepths[t.lane||0]-1-chord.rank)*row.noteStep)*s;
      result.push({id:t.id,row:row.index,lane:t.lane||0,sourcePart:t.sourcePart,voice:t.voice,staff:t.staff,
        start,end,continued:t.beat<f.start,chordRank:chord.rank,chordDepth:chord.depth,
        x,right,cx:x+Math.min(u.width,right-x)/2,base,hitBox:{x,y:base-32*s,width:Math.max(8,right-x-2*s),height:91*s}});
    }
    return result;
  }
  function layout(data, available, scale = 1, textWidth = (s) => s.length * 7) {
    const width = Math.max(180, Math.floor(available)), inset = 14 * scale;
    const room = width - inset * 2, fragments = [];
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
          fragments.push({measure, units: chunk, width: size}); chunk = []; size = 16*scale;
        }
        chunk.push(unit); size += unit.width;
      }
      if (chunk.length) fragments.push({measure, units: chunk, width: size});
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
      const lanes = Math.max(...frags.map((f) => f.measure.lanes || 1));
      // Only new unlocated notes carrying lyrics need a second text baseline.
      // Leave room before the next voice's high triplet mark as well as digits.
      const chordDepth=Math.max(1,...frags.flatMap(f=>f.measure.tokens.map(t=>chordInfo(f.measure,t).depth)));
      const noteStep=112;
      const laneHeight = (frags.some((f) => f.measure.tokens.some((t) => needsTimingLabel(t) && lyric(t))) ? 128 : 112);
      const laneDepths=Array.from({length:lanes},(_,lane)=>Math.max(1,...frags.flatMap(f=>f.measure.tokens.filter(t=>(t.lane||0)===lane).map(t=>chordInfo(f.measure,t).depth))));
      const laneOffsets=[];let total=0;for(const depth of laneDepths){laneOffsets.push(total);total+=laneHeight+(depth-1)*noteStep;}
      const height = (36 + total)*scale;
      const raw = frags.reduce((s, f) => s + f.width, 0);
      const stretch = Math.min(1.35, room/raw);
      let x = inset;
      const placements = frags.map((f) => {
        const start = f.units[0].start, end = f.units.at(-1).end;
        let ux = x + 8*scale;
        const units = f.units.map((u) => {const placed = {...u, x: ux, width: u.width*stretch}; ux += placed.width; return placed;});
        const out = {...f, x, width: f.width*stretch, units, start, end}; x += out.width; return out;
      });
      const r = {index: ri, y, height, lanes, laneHeight, chordDepth, noteStep, laneDepths, laneOffsets, fragments: placements}; y += height; return r;
    });
    return {width, height: y + 10*scale, rows: placed, scale};
  }
  function render(data, available, scale = 1) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const geometry = layout(data, available, scale, (s, fs) => {ctx.font = `${fs}px Arial`; return ctx.measureText(s).width;});
    geometry.fragmentPlacements=fragmentPlacements(geometry);
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
          const laneBase = row.y + (64 + row.laneOffsets[lane]+(row.laneDepths[lane]-1)*row.noteStep)*s;
          body += line(f.x, laneBase-(27+(row.laneDepths[lane]-1)*row.noteStep)*s, f.x, laneBase+14*s, f.start > 0 ? "jp-bar jp-continuation" : "jp-bar");
          body += line(f.x+f.width, laneBase-(27+(row.laneDepths[lane]-1)*row.noteStep)*s, f.x+f.width, laneBase+14*s, f.end < m.beatsPerMeasure ? "jp-bar jp-continuation" : "jp-bar");
          const laneTokens = m.tokens.filter((t) => (t.lane || 0) === lane && t.beat < f.end-.001 && t.beat+t.durationBeats > f.start+.001);
          let previous = null;
          for (const t of laneTokens) {
            const chord=chordInfo(m,t),base=laneBase-chord.rank*row.noteStep*s;
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
            body += `<g class="jp-note${t.isRest ? " jp-rest" : ""}${!playable ? " jp-readonly" : ""}" data-id="${esc(id)}"${Number.isInteger(t.eventIndex) ? ` data-event-index="${t.eventIndex}"` : ""} ${interaction} data-chord-rank="${chord.rank}" data-chord-depth="${chord.depth}" data-row="${row.index}" data-start="${start}" data-end="${end}" aria-label="${esc(alt)}">`;
            body += `<rect class="jp-bg" x="${x}" y="${base-32*s}" width="${Math.max(8, right-x-2*s)}" height="${91*s}" rx="7"/>`;
            body += `<rect class="jp-progress" x="${x}" y="${base+58*s}" width="0" height="${3*s}" rx="1.5" data-width="${Math.max(8, right-x-2*s)}"/>`;
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
              if (label) body += text(cx, base+49*s, label, "jp-lyric", 'text-anchor="middle"');
              if (needsTimingLabel(t)) body += text(cx, base+(label ? 65 : 49)*s, "未定位", "jp-timing-notice", 'text-anchor="middle"');
              if (t.tuplet) body += text(cx, base-39*s, t.tuplet.actual, "jp-tuplet", 'text-anchor="middle"');
            }
            body += "</g>";
            // Join short-note beams by beat, never across a rest or another voice.
            if (chord.rank===0 && previous && Math.abs(previous.base-base)<.001 && !t.isRest && !previous.t.isRest && Math.abs(previous.end-start)<.001 && Math.floor(previous.start) === Math.floor(start)) {
              const count = Math.min(r.beams, rhythm(previous.t).beams);
              for (let b = 0; b < count; b++) body += line(previous.cx+9*s, base+(9+b*6)*s, cx-9*s, base+(9+b*6)*s);
            }
            if(chord.rank===0) previous = region;
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
    const tonic = String(data.tonic || "C").replace(/^([A-G])b$/, "♭$1").replace(/^([A-G])#$/, "♯$1");
    const hint = data.measures?.some((m) => m.lanes > 1) ? "重叠声部分行显示" : "双击音符定位";
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
  const api = {layout, parse, rhythm, render, chordInfo, fragmentPlacements};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MusicNotation = api;
})(typeof window === "undefined" ? {} : window);

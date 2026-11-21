/* Responsive numbered notation. Geometry and typography use separate units:
 * spacing may expand, but glyphs and lyric syllables are never squashed. */
(function (root) {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const isGrace = t => t.isGrace === true && t.durationBeats === 0;
  function parse(token) {
    if (["×","⊗","/","◇"].includes(token)) return {acc:"",num:token,octave:0};
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
  function harmonyIn(h,measure,start,end) {
    return h.measure===measure && (h.untimed ? start===0 : h.beat>=start && h.beat<end);
  }
  // Opt-in source-dialogue blocks retain the source measure, part and speaker.
  // Their reading position is after all voices, never a fabricated voice or beat.
  function dialogueDirections(data) {
    const plan = data.sourceDialogueLayoutProposal;
    if (plan?.schema !== "source-dialogue-block-layout/v1" || plan.followId !== data.songId ||
        plan.canonicalSha256 !== data.canonicalSha256 || !Array.isArray(plan.directionIds)) return new Map();
    const ids = new Set(plan.directionIds), used = new Set(), result = new Map();
    const sources = data.sourcePaperMarkup?.directions || [];
    for (const direction of data.displayDirections || []) {
      const source = sources.find(d => ids.has(d.id) && !used.has(d.id) && typeof d.speakerSourceLabel === "string" &&
        d.speakerSourceLabel.trim() && d.measure === direction.measure && d.beat === direction.beat &&
        d.sourcePart === direction.sourcePart && d.literalText === direction.label);
      if (source) {used.add(source.id);result.set(direction, source);}
    }
    return result;
  }
  function wrapDirectionText(value, available, fontSize, textWidth) {
    const limit = Math.max(1, available), lines = [];
    for (const paragraph of String(value).replace(/\r/g, "").split("\n")) {
      let line = "";
      for (const word of paragraph.trim().split(/\s+/).filter(Boolean)) {
        const combined = line ? line + " " + word : word;
        if (textWidth(combined, fontSize) <= limit) {line = combined;continue;}
        if (line) {lines.push(line);line = "";}
        if (textWidth(word, fontSize) <= limit) {line = word;continue;}
        for (const character of Array.from(word)) {
          if (line && textWidth(line + character, fontSize) > limit) {lines.push(line);line = "";}
          line += character;
        }
      }
      if (line || !paragraph.trim()) lines.push(line);
    }
    return lines;
  }
  function layout(data, available, scale = 1, textWidth = (s) => s.length * 7) {
    const dialogue = dialogueDirections(data);
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
        const graces = starts.filter(isGrace);
        const graceWidth = Math.max(0, ...graces.map(t => graces.filter(g => g.lane === t.lane).length)) * 22 * scale;
        const chordWidth=Math.max(0,...(data.displayHarmonies||[]).filter(h=>harmonyIn(h,measure.measure,start,stop)).map(h=>textWidth(h.label+(h.untimed?"（小节参考）":""),12*scale)+16*scale));
        const min = Math.max(chordWidth, 22 * scale * Math.sqrt(stop-start), ...starts.map((t) => Math.max(34*scale, textWidth(lyric(t), 13*scale) + 14*scale, parse(t.token).acc ? 44*scale : 0,
          needsTimingLabel(t) ? textWidth("未定位", 11*scale)+14*scale : 0)));
        units.push({start, end: stop, graces, graceWidth, width: Math.min(room - 16*scale, min + graceWidth)});
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
      const laneHeight = frags.some((f) => f.measure.tokens.some((t) => needsTimingLabel(t) && lyric(t)) ||
        (data.displayDirections || []).some(d=>d.measure===f.measure.measure)) ? 128 : 112;
      const chordHeader = frags.some(f => (data.displayHarmonies || []).some(h => harmonyIn(h,f.measure.measure,f.units[0].start,f.units.at(-1).end))) ? 24 : 0;
      const labelHeader = data.sourceParts?.length > 1 && lanes > 1 ? 32 : 0;
      const height = (36 + chordHeader + labelHeader + laneHeight*lanes)*scale;
      const raw = frags.reduce((s, f) => s + f.width, 0);
      const stretch = Math.min(1.35, room/raw);
      let x = inset;
      const placements = frags.map((f) => {
        const start = f.units[0].start, end = f.units.at(-1).end;
        let ux = x + 8*scale;
        const units = f.units.map((u) => {const placed = {...u, x: ux, width: u.width*stretch}; ux += placed.width; return placed;});
        const out = {...f, x, width: f.width*stretch, units, start, end}; x += out.width; return out;
      });
      const blocks = [];
      let dialogueHeight = 0;
      for (const f of placements) for (const direction of data.displayDirections || []) {
        const source = dialogue.get(direction);
        if (!source || direction.measure !== f.measure.measure || direction.beat < f.start || direction.beat >= f.end ||
            (direction.sourcePart && !f.measure.tokens.some(t => t.sourcePart === direction.sourcePart))) continue;
        const fontSize = 11*scale, lineHeight = 17*scale;
        const x = inset+8*scale, maxWidth = width-inset*2-16*scale;
        const label = `第 ${direction.measure} 小节 · ${source.sourcePart} · ${source.speakerSourceLabel}`;
        const headerLines = wrapDirectionText(label,maxWidth,fontSize,textWidth);
        const lines = wrapDirectionText(direction.label,maxWidth,fontSize,textWidth);
        const top = y+height+dialogueHeight;
        const blockHeight = (headerLines.length+lines.length)*lineHeight+12*scale;
        blocks.push({sourceDirectionId:source.id,measure:direction.measure,beat:direction.beat,
          sourcePart:source.sourcePart,speakerSourceLabel:source.speakerSourceLabel,
          literalText:direction.label,x,top,width:maxWidth,height:blockHeight,fontSize,lineHeight,headerLines,lines});
        dialogueHeight += blockHeight;
      }
      const r = {index: ri, y, height:height+dialogueHeight, lanes, laneHeight, chordHeader, labelHeader, fragments: placements};
      if (blocks.length) r.dialogueBlocks = blocks;
      y += r.height; return r;
    });
    return {width, height: y + 10*scale, rows: placed, scale};
  }
  function render(data, available, scale = 1, sectionMeasures = new Set()) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const geometry = layout(data, available, scale, (s, fs) => {ctx.font = `${fs}px Arial`; return ctx.measureText(s).width;});
    const s = scale, pieces = new Map();
    const dialogue = dialogueDirections(data);
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
        for (const harmony of (data.displayHarmonies || []).filter(h=>harmonyIn(h,m.measure,f.start,f.end))) {
          body += text((harmony.untimed?f.x:at(harmony.beat))+8*s,row.y+38*s,harmony.label+(harmony.untimed?"（小节参考）":""),"jp-chord");
        }
        const omitted = m.tokens.length && m.tokens.every((token) => token.scoreOmitted);
        const untimed = m.tokens.length && m.tokens.every((token) => token.sourceOnlyUntimed === true);
        const changedKey = m.localTonic && (m === data.measures[0] || m.localTonic !== data.measures[data.measures.indexOf(m)-1]?.localTonic);
        const measureLabel = (m.measure === 0 ? "起拍" : m.measure) + (changedKey ? " · 1=" + m.localTonic : "");
        const section = sectionMeasures.has(m.measure);
        const number = text(f.x+5*s, numY, `${measureLabel}${omitted ? " · 未演奏" : untimed && !section ? " · 未定位" : ""}${f.start > 0 ? " · 续" : ""}`, "jp-measure-number");
        if (section) {
          const label = m.measure === 0 ? "定位到起拍所在段落" : `定位到第 ${m.measure} 小节所在段落`;
          body += `<g class="jp-section-seek" data-section-measure="${m.measure}" role="button" tabindex="0" aria-label="${label}"><rect x="${f.x+1}" y="${row.y}" width="${f.width-2}" height="${27*s}" rx="4"/>${number}</g>`;
        } else body += number;
        if (f.start === 0 && (m === data.measures[0] || m.timeSignature !== data.measures[data.measures.indexOf(m)-1]?.timeSignature)) {
          body += text(f.x+f.width-6*s, numY, m.timeSignature || "", "jp-meter", 'text-anchor="end"');
        }
        for (let lane = 0; lane < row.lanes; lane++) {
          const base = row.y + (64 + row.chordHeader + row.labelHeader + lane*row.laneHeight)*s;
          if (data.sourceParts?.length > 1 && row.lanes > 1 && m.laneLabels?.[lane]) body += text(f.x+6*s, base-(lane===0?60:40)*s, m.laneLabels[lane], "jp-lane-label");
          body += line(f.x, base-27*s, f.x, base+14*s, f.start > 0 ? "jp-bar jp-continuation" : "jp-bar");
          body += line(f.x+f.width, base-27*s, f.x+f.width, base+14*s, f.end < m.beatsPerMeasure ? "jp-bar jp-continuation" : "jp-bar");
          const laneTokens = m.tokens.filter((t) => !isGrace(t) && (t.lane || 0) === lane && t.beat < f.end-.001 && t.beat+t.durationBeats > f.start+.001);
          for (const unit of f.units) {
            const graces = unit.graces.filter(t => (t.lane || 0) === lane);
            for (const [index, t] of graces.entries()) {
              const parsed = parse(t.token), cx = unit.x+(13+index*22)*s, y = base-7*s;
              const label = `第 ${m.measure} 小节，装饰音 ${t.token}，仅供读谱`;
              const accidental = t.sourceGraceAccidental === "natural" ? "♮" : parsed.acc;
              const beams = rhythm(t).beams;
              body += `<g class="jp-note jp-grace jp-readonly" data-id="${esc(t.id)}" data-source-id="${esc(t.sourcePhysicalId || t.originalSourceNoteId || t.id)}" data-row="${row.index}" role="img" aria-label="${esc(label)}">`;
              body += text(cx, y, parsed.num, "jp-digit", `text-anchor="middle" style="font-size:${14*s}px"`);
              if (accidental) body += text(cx-8*s, y-2*s, accidental, "jp-accidental", `text-anchor="middle" style="font-size:${10*s}px"`);
              for (let b = 0; b < beams; b++) body += line(cx-5*s, y+(3+b*3)*s, cx+5*s, y+(3+b*3)*s);
              for (let oct = 0; oct < Math.abs(parsed.octave); oct++) {
                const dy = parsed.octave > 0 ? -16-oct*4 : 7+beams*3+oct*4;
                body += `<circle cx="${cx}" cy="${y+dy*s}" r="${1.2*s}" class="jp-dot"/>`;
              }
              body += "</g>";
            }
          }
          for(const direction of (data.displayDirections || []).filter(d=>d.measure===m.measure && d.beat>=f.start && d.beat<f.end &&
            (!d.sourcePart || laneTokens.some(t=>t.sourcePart===d.sourcePart)))) {
            if(!dialogue.has(direction))body+=text(at(direction.beat)+8*s,base+80*s,direction.label,"jp-direction");
          }
          let previous = null;
          for (const t of laneTokens) {
            const start = Math.max(t.beat, f.start), end = Math.min(t.beat+t.durationBeats, f.end);
            const right = at(end), u = f.units.find((u) => Math.abs(u.start-start)<.001) || f.units[0];
            const x = at(start)+u.graceWidth;
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
            const playable = t.seekAllowed !== false && !t.scoreOmitted && !t.skipCursorHighlight && typeof t.time === "number" && Number.isFinite(t.time);
            const timingNotice = t.scoreOmitted ? "（录音未演奏，仅供阅读）" : t.sourceOnlyUntimed === true ? "（时间未定位，仅供阅读）" : "";
            const alt = `${m.measure === 0 ? "起拍" : `第 ${m.measure} 小节`}，${t.isRest ? "休止" : t.token}${t.lyric ? "，"+t.lyric : ""}${timingNotice}`;
            const interaction = playable ? `data-time="${t.time}" role="button" tabindex="0"` : 'role="img"';
            body += `<g class="jp-note${t.isRest ? " jp-rest" : ""}${!playable ? " jp-readonly" : ""}" data-id="${esc(id)}" data-source-id="${esc(t.sourcePhysicalId || t.originalSourceNoteId || id)}"${Number.isInteger(t.eventIndex) ? ` data-event-index="${t.eventIndex}"` : ""} ${interaction} data-row="${row.index}" data-start="${start}" data-end="${end}" aria-label="${esc(alt)}">`;
            body += `<rect class="jp-bg" x="${x}" y="${base-32*s}" width="${Math.max(8, right-x-2*s)}" height="${91*s}" rx="7"/>`;
            body += `<rect class="jp-progress" x="${x}" y="${base+58*s}" width="0" height="${3*s}" rx="1.5" data-width="${Math.max(8, right-x-2*s)}"/>`;
            body += text(cx, base, parsed.num, "jp-digit", 'text-anchor="middle"');
            if(t.displayBreath)body+=text(cx+16*s,base-28*s,"，","jp-direction");
            if (t.parentheses) {
              body += text(cx-17*s,base,"(","jp-source-parenthesis",'text-anchor="middle"');
              body += text(cx+17*s,base,")","jp-source-parenthesis",'text-anchor="middle"');
            }
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
            if (previous && !t.isRest && !previous.t.isRest && Math.abs(previous.end-start)<.001 && Math.floor(previous.start) === Math.floor(start)) {
              const count = Math.min(r.beams, rhythm(previous.t).beams);
              for (let b = 0; b < count; b++) body += line(previous.cx+9*s, base+(9+b*6)*s, cx-9*s, base+(9+b*6)*s);
            }
            previous = region;
          }
        }
      }
      for (const block of row.dialogueBlocks || []) {
        body += `<g class="jp-source-dialogue" data-source-direction-id="${esc(block.sourceDirectionId)}" data-source-measure="${block.measure}" data-source-part="${esc(block.sourcePart)}" data-source-speaker="${esc(block.speakerSourceLabel)}">`;
        let baseline = block.top+block.lineHeight;
        for (const header of block.headerLines) {
          body += text(block.x,baseline,header,"jp-direction jp-dialogue-label",`style="font:${block.fontSize}px Arial"`);
          baseline += block.lineHeight;
        }
        for (const value of block.lines) {
          body += text(block.x,baseline,value,"jp-direction jp-dialogue-line",`style="font:${block.fontSize}px Arial"`);
          baseline += block.lineHeight;
        }
        body += "</g>";
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
      if (a.row.index === b.row.index && Math.abs(a.base-b.base)<1) body += arc(a.cx+8*s, a.base-33*s, b.cx-8*s, b.base-33*s);
      else {
        body += arc(a.cx+8*s, a.base-33*s, geometry.width-12*s, a.base-33*s);
        body += arc(12*s, b.base-33*s, b.cx-8*s, b.base-33*s);
      }
    }
    // Printed source slurs and lyric extenders are independent from sounding ties.
    const physicalIds=new Map((data.tokens||[]).map(t=>[t.sourcePhysicalId || t.originalSourceNoteId || t.id,t.id]));
    const sourcePieces=key=>pieces.get(String(key)) || pieces.get(String(physicalIds.get(key)));
    const curves = data.sourceSlurs || data.sourceConnections || [];
    const seenCurves=new Set();
    for (const connection of curves) {
      const from = connection.fromSourceNoteId || connection.fromSourcePhysicalId || connection.from || connection.startSourceId || connection.start;
      const to = connection.toSourceNoteId || connection.toSourcePhysicalId || connection.to || connection.stopSourceId || connection.end;
      const curveKey=JSON.stringify([from,to]);if(seenCurves.has(curveKey))continue;seenCurves.add(curveKey);
      const a = sourcePieces(from)?.at(-1), b = sourcePieces(to)?.[0];
      if (a && b) {
        if (a.row.index === b.row.index) body += arc(a.cx+8*s,a.base-40*s,b.cx-8*s,b.base-40*s);
        else {
          body += arc(a.cx+8*s,a.base-40*s,geometry.width-12*s,a.base-40*s);
          body += arc(12*s,b.base-40*s,b.cx-8*s,b.base-40*s);
        }
      }
    }
    for(const chain of data.displayExtenderChains || []) {
      const anchors=new Set(chain.anchorSourcePhysicalIds || [chain.anchorSourcePhysicalId]);
      const ids=[...anchors,...chain.continuationSourcePhysicalIds],groups=new Map();
      for(const id of ids)for(const p of sourcePieces(id)||[]) {
        const key=p.row.index+":"+p.base;
        if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);
      }
      for(const regions of groups.values()) {
        regions.sort((a,b)=>a.x-b.x);const a=regions[0],b=regions.at(-1);
        const anchor=anchors.has(a.t.sourcePhysicalId || a.t.originalSourceNoteId || a.t.id);
        ctx.font=`${13*s}px Arial`;
        const left=anchor?a.cx+ctx.measureText(chain.literalLyric || a.t.lyric || "").width/2+4*s:a.x+4*s;
        if(b.right-4*s>left)body+=line(left,a.base+51*s,b.right-4*s,a.base+51*s,"jp-source-extender");
      }
    }
    for (const segments of pieces.values()) {
      const t = segments[0]?.t;
      if (!t) continue;
      const articulations = JSON.stringify(t.sourceArticulations || t.sourceNotations || []);
      if (articulations.includes('staccato')) {
        const a=segments[0]; body += `<circle class="jp-source-staccato" cx="${a.cx}" cy="${a.base-37*s}" r="${1.7*s}"/>`;
      }
      if (t.lyricExtend || t.lyricExtender || t.sourceExtenderIds?.length) {
        for (const a of segments) body += line(a.cx+12*s,a.base+51*s,a.right-4*s,a.base+51*s,"jp-source-extender");
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
  const api = {layout, parse, rhythm, render};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MusicNotation = api;
})(typeof window === "undefined" ? {} : window);

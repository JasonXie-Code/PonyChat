/* The score's data determines which kinds of following the reader can offer. */
(function (root) {
  "use strict";
  function playable(token) {
    return !token.scoreOmitted && !token.skipCursorHighlight && typeof token.time === "number" && Number.isFinite(token.time);
  }
  function formatChord(chord, score) {
    const source = String(score || "").split("/").at(-1);
    // The reviewed Season 2 chart prints Db7; MusicXML calls its kind dominant.
    if (source === "MLP212_Piggy Dance 2 CHART.pdf" && chord === "Dbdominant") return "Db7";
    // This reviewed PDF's OpusChords font extracts sharp as © and minor as ‹.
    // Keep the correction tied to its verified source, never copyright text.
    if (source !== "MLP226_This Day Aria - Part 2 CHART.pdf") return chord;
    const verified = {"C©/G©":"C#/G#", "G©m/B":"G#m/B", "G©‹/B":"G#m/B", "F©/A©":"F#/A#", "C©m":"C#m", "C©‹":"C#m"};
    return verified[chord] || chord;
  }
  function verifiedRecordingKeyShift(data) {
    const shift = data.song?.quality?.recordingVersion?.transposition;
    if (shift?.verified !== true || !Number.isInteger(shift.semitones) || !shift.semitones ||
        !shift.evidence || !/^[a-f0-9]{64}$/i.test(shift.evidenceSha256 || "")) return null;
    const parseKey = (key) => {
      const match = /^([A-G])([#b]{0,2})(?: (major|minor))?$/.exec(key || "");
      if (!match || /#b|b#/.test(match[2])) return null;
      const pitch = {C:0,D:2,E:4,F:5,G:7,A:9,B:11}[match[1]] + [...match[2]].reduce((n, char) => n+(char === "#" ? 1 : -1), 0);
      return {pitch, mode:match[3], label:match[1]+match[2].replaceAll("#", "♯").replaceAll("b", "♭")+(match[3] === "minor" ? " 小调" : "")};
    };
    const source = parseKey(shift.sourceKey), recording = parseKey(shift.recordingKey);
    if (!source || !recording || source.mode !== recording.mode ||
        ((recording.pitch-source.pitch-shift.semitones)%12+12)%12 !== 0) return null;
    return {source, recording, semitones:shift.semitones};
  }
  function recordingKeyNotice(data) {
    const keys = verifiedRecordingKeyShift(data);
    if (!keys) return "";
    const {source, recording, semitones} = keys;
    return `原谱 ${source.label} · 录音 ${recording.label}（${semitones < 0 ? "低" : "高"} ${Math.abs(semitones)} 个半音）`;
  }
  function jianpuKeyNotice(data) {
    const keys = verifiedRecordingKeyShift(data);
    return keys ? `简谱调性 1=${keys.recording.label}` : "";
  }
  function recordingPitchNotice(data) {
    const relation = data.song?.quality?.recordingPitchRelation;
    const syncRelation = data.sync?.recordingPitchRelation;
    if (relation?.status !== "verified-global-octave-relation" || !syncRelation ||
        !Number.isInteger(relation.semitones) || !relation.semitones || relation.semitones % 12 ||
        typeof relation.evidence !== "string" || !relation.evidence.trim() ||
        !/^[a-f0-9]{64}$/i.test(relation.evidenceSha256 || "") ||
        ["status", "semitones", "evidence", "evidenceSha256"].some((key) => relation[key] !== syncRelation[key])) return "";
    const octaves = Math.abs(relation.semitones) / 12;
    return `原谱音高 · 录音${relation.semitones < 0 ? "低" : "高"}${octaves === 1 ? "八度" : ` ${octaves} 个八度`}`;
  }
  function recordingNotice(data) {
    return recordingPitchNotice(data) || recordingKeyNotice(data);
  }
  function primaryIndices(sync = {}) {
    const policy = sync.cursorPolicy;
    if (policy?.verified !== true) return null;
    const indices = policy.primaryEventIndices;
    if (!Array.isArray(indices) || typeof policy.evidence !== "string" || !policy.evidence.trim() || !/^[a-f0-9]{64}$/i.test(policy.evidenceSha256 || "")) return new Set();
    const selected = new Set(indices);
    if (selected.size !== indices.length || indices.some((index) => {
      const event = sync.events?.[index];
      const roleIdentity = typeof event?.sourceRole === "string" ? event.sourceRole : event?.partId;
      const hasRoleIdentity = typeof roleIdentity === "string" && !!roleIdentity.trim() &&
        (typeof event?.sourceRole === "string" || (typeof event?.sourceVoice === "string" && !!event.sourceVoice.trim()));
      return !Number.isInteger(index) || index < 0 || !event || event.eventIndex !== index ||
        event.cursorPrimary !== true || !hasRoleIdentity || !playable(event) ||
        !Number.isFinite(event.endTime) || event.endTime <= event.time;
    })) return new Set();
    return selected;
  }
  function seekableEvents(sync = {}) {
    return (sync.events || []).filter((event) => playable(event) && (sync.precision === "score-section" || !event.pdfLyricCue))
      .sort((a, b) => a.time - b.time);
  }
  function cursorEvents(sync = {}) {
    const selected = primaryIndices(sync);
    return seekableEvents(sync).filter((event) => selected === null || selected.has(event.eventIndex));
  }
  function sameSource(token, event) {
    return event && token.time === event.time && token.pitch === event.pitch && !!token.isRest === !!event.isRest &&
      token.sourceRole === event.sourceRole && token.cursorPrimary === event.cursorPrimary &&
      token.sourcePart === (event.partId || event.sourcePart);
  }
  function playbackTokens(jianpu = {}, sync = {}) {
    const selected = primaryIndices(sync);
    return tokenInstances(jianpu, sync).filter((token) => playable(token) && (selected === null ||
      (selected.has(token.eventIndex) && sameSource(token, sync.events[token.eventIndex]))))
      .sort((a, b) => a.time - b.time);
  }
  function tokenInstances(jianpu = {}, sync = {}) {
    const physical = jianpu.tokens || [];
    if (!physical.some((t) => Array.isArray(t.occurrenceEventIndices))) return physical;
    const map = jianpu.performanceMap;
    if (map?.verified !== true || typeof map.evidence !== "string" || !map.evidence.trim() ||
        !/^[a-f0-9]{64}$/i.test(map.evidenceSha256 || "")) return [];
    const result = [], used = new Set(), occurrenceIds = new Set();
    for (const token of physical) {
      const indices = token.occurrenceEventIndices;
      if (!Array.isArray(indices)) {result.push(token); continue;}
      if (!indices.length || token.isRest || token.scoreOmitted || token.sourceOnlyUntimed ||
          typeof token.originalSourceNoteId !== "string" || !token.originalSourceNoteId) return [];
      for (const index of indices) {
        const event = sync.events?.[index];
        if (!Number.isInteger(index) || used.has(index) || !event || event.eventIndex !== index ||
            !playable(event) || event.isRest || event.pitch !== token.pitch ||
            event.originalSourceNoteId !== token.originalSourceNoteId || event.partId !== token.sourcePart ||
            !Number.isFinite(event.endTime) || event.endTime <= event.time ||
            typeof event.occurrenceId !== "string" || !event.occurrenceId || occurrenceIds.has(event.occurrenceId)) return [];
        used.add(index); occurrenceIds.add(event.occurrenceId);
        result.push({...token, eventIndex:index, time:event.time, endTime:event.endTime,
          mappedDurationSeconds:event.endTime-event.time, sourceRole:event.sourceRole,
          cursorPrimary:event.cursorPrimary, occurrenceId:event.occurrenceId});
      }
    }
    return result;
  }
  function tokenAtSource(jianpu, sync, id, time) {
    const candidates = tokenInstances(jianpu, sync).filter((t) => playable(t) && String(t.id ?? t.eventIndex) === String(id));
    return candidates.reduce((best, t) => !best || Math.abs(t.time-time) < Math.abs(best.time-time) ? t : best, null);
  }
  function cursorPair(events, tokens, time, canonical = false, section = false) {
    const event = eventAt(events, time, section, canonical);
    const token = canonical ? (event ? tokens.find((item) => item.eventIndex === event.eventIndex) || null : null) : eventAt(tokens, time);
    return {event, token};
  }
  function manualCursor(sync, jianpu, index) {
    const selected = primaryIndices(sync);
    if (!selected?.size || !Number.isInteger(index) || selected.has(index)) return null;
    const event = sync.events[index], token = tokenInstances(jianpu, sync).find((item) => item.eventIndex === index && playable(item));
    if (!event || event.eventIndex !== index || !playable(event) || !event.visual || !token || !sameSource(token, event)) return null;
    return {event, token, pendingAck:true};
  }
  function updateManualCursor(selection, time, paused, jump) {
    if (!selection || !paused) return null;
    const arrived = Math.abs(time-selection.event.time) < .0001;
    if (jump && (!selection.pendingAck || !arrived)) return null;
    return arrived ? {...selection, pendingAck:false} : selection;
  }
  function headCenter(event, canonical = false) {
    const head = canonical && event?.visual?.noteheadCenter;
    return head && Number.isFinite(head.x) && Number.isFinite(head.y) && head.x >= 0 && head.x <= 1 && head.y >= 0 && head.y <= 1 ? head : null;
  }
  function nearestScoreEvent(events, page, nx, ny, time, section = false, canonical = false) {
    let best = null, distance = Infinity;
    for (const event of events) {
      const v = event.visual;
      if (!playable(event) || !v || Number(v.page || event.page) !== Number(page)) continue;
      // Source-only bars and empty page margins have no playback target.
      const head = headCenter(event, canonical), center = head?.x ?? v.x+v.width/2;
      const horizontalHit = section ? nx >= v.x-.018 && nx <= v.x+v.width+.018 : Math.abs(nx-center) <= .014;
      const verticalHit = head ? Math.abs(ny-head.y) <= .012 : ny >= v.y-.015 && ny <= v.y+v.height+.015;
      if (!horizontalHit || !verticalHit) continue;
      const d = ((center-nx)*1.45)**2 + ((head?.y ?? v.y+v.height/2)-ny)**2;
      if (d < distance-1e-8 || (Math.abs(d-distance)<1e-8 && Math.abs(event.time-time)<Math.abs(best.time-time))) {best=event; distance=d;}
    }
    return best;
  }
  function capabilities(data) {
    const section = data.sync?.precision === "score-section";
    const primary = primaryIndices(data.sync);
    const hasSync = cursorEvents(data.sync).some((event) => event.visual);
    const hasNotation = !section && !!data.jianpu?.tokens?.length && !!data.jianpu?.measures?.length;
    return {
      section, hasSync, hasNotation, canonicalCursor:!!primary?.size,
      staffTitle: section || !hasSync ? "原谱" : "五线谱",
      resumeTitle: section ? "回到当前谱行" : "回到当前音符",
      interaction: hasSync ? (section ? "双击谱行定位" : "双击音符定位") : "自由浏览原谱",
      notice: section ? "按词句跟随原谱，暂不支持逐音符高亮与简谱。" : (!hasSync ? "此曲暂时仅支持原谱浏览。" : ""),
    };
  }
  function eventAt(events, time, section = false, bounded = false) {
    let lo = 0, hi = events.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (events[mid].time <= time + (bounded ? .00001 : 0)) lo = mid + 1; else hi = mid - 1;
    }
    const event = hi >= 0 ? events[hi] : null;
    return (section || bounded) && event && Number.isFinite(event.endTime) && time >= event.endTime ? null : event;
  }
  function position(event, section, time = 0, events = []) {
    if (!event) return time > (events[0]?.time ?? Infinity) ? "间奏" : "前奏";
    if (section) return event.label || `原谱第 ${event.visual?.page || event.page || 1} 页`;
    if (event.measure === 0 || event.measure === "0") return "起拍";
    return event.measure != null ? `第 ${event.measure} 小节` : "原谱";
  }
  const api = {capabilities, cursorEvents, playbackTokens, eventAt, position, playable, nearestScoreEvent, formatChord, recordingKeyNotice, jianpuKeyNotice, recordingPitchNotice, recordingNotice,
    primaryIndices, seekableEvents, cursorPair, manualCursor, updateManualCursor, headCenter, tokenInstances, tokenAtSource};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MusicFollowPolicy = api;
})(typeof window === "undefined" ? {} : window);

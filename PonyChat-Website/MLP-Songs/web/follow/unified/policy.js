/* Keep the original reader's permissions, including repeated source occurrences. */
(function (root) {
  "use strict";
  const base = root.MusicFollowPolicy;
  const id = t => root.MusicUnifiedModel.id(t);
  function instances(n, sync) {
    if (!sync.instances) return base.tokenInstances(n, sync);
    const byId = new Map(n.tokens.map(t => [id(t), t]));
    return sync.events.flatMap(e => {
      const t = byId.get(id(e));
      if (!t || t.isRest || t.isUnpitched || e.seekAllowed === false || typeof e.time !== "number") return [];
      return [{...t, eventIndex:e.eventIndex, time:e.time, endTime:e.endTime,
        occurrenceId:e.occurrenceId, mappedDurationSeconds:e.endTime-e.time, skipCursorHighlight:false}];
    });
  }
  root.MusicFollowPolicy = {...base,
    capabilities(data) {
      const result = base.capabilities(data);
      return {...result, hasSync:data.sync.events.some(e => e.visual), canonicalCursor:true,
        staffTitle:"五线谱", notice:result.section ? result.notice : ""};
    },
    playbackTokens:(n,sync) => (sync.instances ? instances(n,sync).filter(base.playable) : base.playbackTokens(n,sync)).sort((a,b) => a.time-b.time),
    tokenInstances:instances,
    cursorPair(events, tokens, time) {
      const event = base.eventAt(events,time,false,true);
      const token = event ? tokens.find(t => t.eventIndex === event.eventIndex) ||
        tokens.find(t => id(t) === id(event) && t.time <= time && time < t.endTime) : null;
      return {event,token};
    },
    tokenAtSource(n,sync,key,time) {
      return instances(n,sync).filter(t => t.seekAllowed !== false && String(t.id) === key && base.playable(t)).reduce((best,t) =>
        !best || Math.abs(t.time-time) < Math.abs(best.time-time) ? t : best,null);
    },
    sectionAtMeasure(events, measure, time) {
      const matches = events.filter(({jianpuSection}) => jianpuSection &&
        measure >= jianpuSection.firstMeasure && measure <= jianpuSection.lastMeasure);
      return matches.find(event => event.time <= time && time < event.endTime) || matches.reduce((best, event) =>
        !best || Math.abs(event.time-time) < Math.abs(best.time-time) ? event : best, null);
    },
    sectionNoteReferences(notation, sync) {
      if (sync.precision !== "score-section" || !Array.isArray(sync.noteReferences)) return [];
      const notes = new Map(notation.tokens.map(token => [id(token), token]));
      const windows = [];
      for (const row of sync.noteReferences) {
        const {sourcePhysicalId, time, endTime} = row || {};
        const token = notes.get(sourcePhysicalId);
        if (!token?.pitch || token.isRest || token.isUnpitched || token.isGrace ||
            !Number.isFinite(time) || !Number.isFinite(endTime) || time < 0 || endTime <= time ||
            endTime > sync.duration || time < (windows.at(-1)?.endTime ?? 0)) return [];
        const section = sync.events.find(event => event.jianpuSection && event.time <= time && endTime <= event.endTime &&
          event.jianpuSection.firstMeasure <= token.measure && token.measure <= event.jianpuSection.lastMeasure);
        if (!section) return [];
        windows.push({id:token.id, measure:token.measure, lyric:token.lyric, time, endTime});
      }
      return windows;
    },
    harmonyReferences(data, primaryEvents) {
      const {sync, jianpu, presentation, song} = data;
      if (sync.precision === "score-section" || !Array.isArray(sync.harmonyReferences)) return [];
      const notes = new Map(jianpu.tokens.map(token => [id(token), token]));
      const previousEnds = new Map();
      const windows = [];
      for (const row of sync.harmonyReferences) {
        const {sourcePhysicalId, time, endTime} = row || {};
        const token = notes.get(sourcePhysicalId);
        const head = presentation?.heads?.[sourcePhysicalId];
        if (!token?.pitch || !token.sourcePart || token.isRest || token.isUnpitched || token.isGrace || token.scoreOmitted ||
            !Number.isFinite(time) || !Number.isFinite(endTime) || !Number.isFinite(sync.duration) ||
            time < (previousEnds.get(sourcePhysicalId) ?? 0) || endTime <= time || endTime > sync.duration ||
            !head || !Number.isInteger(head.page) || head.page < 1 || !song.charts?.[head.page-1]) return [];
        const {x, y, width, height} = head;
        if (![x, y, width, height].every(Number.isFinite) || x < 0 || y < 0 ||
            width <= 0 || height <= 0 || x + width > 1 || y + height > 1) return [];
        const primary = base.eventAt(primaryEvents, time, false, true);
        const primaryPart = primary?.sourcePart || primary?.partId;
        if (!primary?.pitch || primary.isRest || primary.isUnpitched || !primaryPart || primaryPart === token.sourcePart ||
            primary.time > time || !Number.isFinite(primary.endTime) || endTime > primary.endTime ||
            primary.visual?.page !== head.page) return [];
        const next = primaryEvents[primaryEvents.indexOf(primary)+1];
        if (next && endTime > next.time) return [];
        previousEnds.set(sourcePhysicalId, endTime);
        windows.push({sourcePhysicalId, id:String(token.id ?? sourcePhysicalId), time, endTime, head, primary});
      }
      return windows;
    },
    manualCursor(sync,n,index) {
      const event = sync.events.find(e => e.eventIndex === index);
      const token = instances(n,sync).find(t => t.eventIndex === index);
      return event && event.seekAllowed !== false && token && token.seekAllowed !== false && base.playable(token) ? {event,token,pendingAck:true} : null;
    },
    seekableEvents:sync => base.seekableEvents(sync).filter(e => e.seekAllowed !== false)
  };
})(window);

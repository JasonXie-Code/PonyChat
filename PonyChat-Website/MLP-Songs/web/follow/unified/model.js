/* A display projection of the admitted API. Recording and signed source data stay immutable. */
(function (root) {
  "use strict";
  const id = t => String(t.sourcePhysicalId || t.originalSourceNoteId || t.id || t.sourceNoteId);
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const unpitchedSymbols = new Map([["circle-x", "⊗"], ["slash", "/"], ["hollow-diamond", "◇"]]);
  function normalize(payload, display) {
    const data = JSON.parse(JSON.stringify(payload)), n = data.jianpu;
    if (display.schema !== "unified-follow-display/v1" || display.followId !== data.song.id ||
        display.certificateSha256 !== (data.song.acceptance?.sha256 ?? null) ||
        display.canonicalSha256 !== (n.canonicalSha256 ?? null) ||
        JSON.stringify(display.physicalIds) !== JSON.stringify(n.tokens.map(id))) throw Error("Display geometry is stale");
    const byId = new Map(n.tokens.map(t => [id(t), t]));
    const sourceSystems=[...display.systems];
    const geometry=n.sourceSystemGeometry;
    for(const s of geometry?.systems || []) {
      if(!finite(s.top)||!finite(s.bottom))continue;
      const page=geometry.pages?.find(p=>p.page===s.page);
      const divisor=s.bottom>1?page?.height:1;
      if(!finite(divisor)||divisor<=0)continue;
      sourceSystems.push({...s,top:s.top/divisor,bottom:s.bottom/divisor,
        firstMeasure:s.firstMeasure??s.first,lastMeasure:s.lastMeasure??s.last});
    }
    const eventsById = new Map();
    for (const e of data.sync.events || []) {
      const key = id(e), t = byId.get(key);
      if (!eventsById.has(key)) eventsById.set(key, []);
      eventsById.get(key).push(e);
      const visual = display.heads[key] || t?.visual || e.visual;
      if (visual) {
        e.visual = {...visual, page:visual.page || t?.page || e.page || 1};
        const center = e.visual.noteheadCenter;
        // A reader hit target is display geometry, never inferred source ink.
        if (center) {
          e.visual.x ??= center.x-.005; e.visual.y ??= center.y-.005;
          e.visual.width ??= .01; e.visual.height ??= .01;
        }
        // Extend the reading line across the complete printed ensemble.
        const measure = Number(e.measureNo ?? e.measure ?? t?.measure);
        const system = sourceSystems.find(s => s.page === e.visual.page && measure >= s.firstMeasure && measure <= s.lastMeasure);
        if (system) e.visual = {...e.visual, y:system.top, height:system.bottom-system.top,
          noteheadCenter:e.visual.noteheadCenter, sourceSystemId:system.sourceSystemId};
      }
      if (t) {
        e.measure ??= t.measure; e.measureNo ??= t.measure; e.beatInMeasure ??= t.beat ?? t.beatInMeasure;
        e.sourcePart ??= t.sourcePart; e.partId ??= t.sourcePart;
        e.lyric ??= e.sourceLyric ?? t.lyric ?? t.sourceLyric;
        e.sourceRole ??= t.sourceRole;
      }
    }
    const partNames = new Map((n.sourceParts || []).map(p => typeof p === "string" ? [p,p] : [p.id,p.name || p.label || p.id]));
    const parentheses=new Set(display.printed.parentheses || []);
    for (const t of n.tokens) {
      t.id ??= id(t); t.beat ??= t.beatInMeasure; t.lyric ??= t.sourceLyric || "";
      if(t.lyricExtender && t.lyric === "__")t.lyric="";
      if(parentheses.has(id(t)))t.parentheses=true;
      if (t.isUnpitched) t.token = unpitchedSymbols.get(t.sourceNoteheadShape) ?? unpitchedSymbols.get(t.noteheadShape) ?? "×";
      else if (Number.isInteger(t.degree) && Number.isInteger(t.octave)) {
        // Several old readers kept octave dots outside the token string.
        t.token = t.isRest ? "0" : (t.accidental ?? t.token?.match(/^(#{1,2}|b{1,2})/)?.[0] ?? "").replaceAll("♯", "#").replaceAll("♭", "b") + t.degree +
          (t.octave > 0 ? "'".repeat(t.octave) : ",".repeat(-t.octave));
      }
      if (!t.isRest && !t.isUnpitched && (!t.token || t.token === "?")) throw Error("Missing source numeral: " + t.id);
      const es = eventsById.get(id(t)) || [], playable = es.find(e => finite(e.time) && e.seekAllowed !== false && !e.isRest && !e.isUnpitched);
      if (data.sync.instances && playable) {
        t.time = playable.time; t.endTime = playable.endTime; t.eventIndex = playable.eventIndex;
        t.skipCursorHighlight = false; t.sourceOnlyUntimed = false;
      }
      const tuple = t.sourceTimeModification;
      if (!t.tuplet && tuple) {
        const child = tuple.children?.find(c => c.tag === "actual-notes");
        const actual = Number(child?.text || tuple.actualNotes);
        if (actual > 0) t.tuplet = {actual};
      }
    }
    // Some admitted APIs store measures part-by-part. Join printed bars before
    // laying out simultaneous voices; performance repetitions stay in sync.events.
    const joined = new Map();
    for (const source of n.measures) {
      const number = source.measure ?? source.number;
      if (!joined.has(number)) joined.set(number,{...source,measure:number,tokens:[]});
      const target=joined.get(number),seen=new Set(target.tokens.map(id));
      for (const token of source.tokens) if (!seen.has(id(token))) {target.tokens.push(token);seen.add(id(token));}
      target.beatsPerMeasure ??= source.beatsPerMeasure;
      target.timeSignature ||= source.timeSignature;
    }
    n.measures=[...joined.values()].sort((a,b)=>Number(a.measure)-Number(b.measure));
    const starts=new Map();
    for (const m of n.measures) {
      const values=m.tokens.filter(t=>finite(t.sourceQuarter)&&finite(t.beat ?? t.beatInMeasure)).map(t=>t.sourceQuarter-(t.beat ?? t.beatInMeasure));
      const printed=display.printed.measures?.find(p=>p.measure===m.measure);
      if (printed) Object.assign(m,printed);
      if (finite(m.sourceQuarterStart)) starts.set(m.measure,m.sourceQuarterStart);
      else if (values.length) starts.set(m.measure,Math.min(...values));
    }
    for (const [mi,m] of n.measures.entries()) {
      // Use the original measure inventory; never collapse voices into a melody.
      m.tokens = m.tokens.map(t => byId.get(id(t)) || t);
      m.measure ??= m.number;
      const next=n.measures[mi+1],length=next?starts.get(next.measure)-starts.get(m.measure):NaN;
      m.beatsPerMeasure ??= length>0?length:Math.max(...m.tokens.map(t => Number(t.beat) + Number(t.durationBeats)), 1);
      m.timeSignature ||= n.measures.find(x => x.timeSignature)?.timeSignature || "";
      const lanes = [], ends = new Map();
      const grace = t => Number(t.isGrace === true && t.durationBeats === 0);
      for (const t of [...m.tokens].sort((a,b) => a.beat-b.beat || grace(b)-grace(a) || (a.chordPosition || 0)-(b.chordPosition || 0))) {
        const voice = [t.sourcePart, t.voice ?? t.sourceVoice ?? "1", t.staff ?? "1"].join(":");
        let chord = 0, key = voice + ":" + chord;
        while ((ends.get(key) ?? -Infinity) > t.beat + .0001) key = voice + ":" + (++chord);
        ends.set(key, t.beat + t.durationBeats);
        if (!lanes.includes(key)) lanes.push(key);
        t.lane = lanes.indexOf(key);
      }
      m.lanes = Math.max(1, lanes.length);
      m.laneLabels = lanes.map(key => partNames.get(key.split(":")[0]) || key.split(":")[0]);
      const keyPlan=display.printed.keyReferenceMap || display.printed.keyPlan || [];
      const key=keyPlan.filter(k => (k.measure ?? k.from ?? (finite(k.q0)?-Infinity:1))<=m.measure &&
        (!finite(k.q0)||starts.get(m.measure)>=k.q0)).at(-1);
      m.localTonic = m.localTonic || m.tokens.find(t => t.localTonic)?.localTonic ||
        m.tokens.find(t => t.sourceTonic)?.sourceTonic || m.sourceTonic || key?.key || key?.tonic ||
        key?.label?.replace(/^1\s*=\s*/,"") || n.tonic;
    }
    n.tonic ||= n.measures[0]?.localTonic || "C";
    const harmonyRows=value=>Array.isArray(value)?value:value?.rows||[];
    const harmonies=[...harmonyRows(n.sourcePrintedChords),...harmonyRows(n.sourceUntimedHarmonies),...harmonyRows(n.sourcePaperMarkup?.harmonies),...harmonyRows(display.printed.harmonies)];
    const seenHarmonies=new Set();
    n.displayHarmonies=harmonies.flatMap(h=>{
      let measure=h.measure,beat=h.beatInMeasure ?? h.beat ?? h.sourceBeat;
      if (measure == null && finite(h.sourceQuarter)) {
        const m=[...n.measures].reverse().find(m=>starts.get(m.measure)<=h.sourceQuarter);
        if (m) {measure=m.measure;beat=h.sourceQuarter-starts.get(measure);}
      }
      const label=h.label || h.text || h.chord;
      const key=JSON.stringify([measure,beat??null,label]);
      if (!label || seenHarmonies.has(key)) return [];
      seenHarmonies.add(key);return [{measure,beat:finite(beat)?beat:null,label,untimed:!finite(beat)}];
    });
    const untimed=new Map();
    for(const h of n.displayHarmonies.filter(h=>h.untimed)) {
      if(!untimed.has(h.measure))untimed.set(h.measure,{...h,labels:[]});
      untimed.get(h.measure).labels.push(h.label);
    }
    n.displayHarmonies=[...n.displayHarmonies.filter(h=>!h.untimed),...Array.from(untimed.values(),h=>({...h,label:h.labels.join(" · ")}))];
    const breathIds=new Set(n.sourcePaperMarkup?.breathSourcePhysicalIds || []);
    for(const t of n.tokens) if(breathIds.has(id(t)))t.displayBreath=true;
    n.displayDirections=(n.sourcePaperMarkup?.directions || []).flatMap(d=>{
      const xml=d.sourceXML || "";
      const words=[...xml.matchAll(/<words\b[^>]*>([\s\S]*?)<\/words>/g)].map(m=>m[1].replace(/<[^>]+>/g,"")).join(" ");
      const dynamic=xml.match(/<dynamics>\s*<([a-z]+)\b/)?.[1];
      const bpm=xml.match(/<per-minute>([^<]+)<\/per-minute>/)?.[1];
      const wedge=xml.match(/<wedge\b[^>]*type="(diminuendo|crescendo)"/)?.[1];
      const label=words || dynamic || (bpm?"♩ = "+bpm:"") || ({diminuendo:"渐弱",crescendo:"渐强"}[wedge]);
      return label?[{measure:d.measure,beat:d.beat,sourcePart:d.sourcePart,label}]:[];
    });
    for(const a of display.printed.annotations || [])n.displayDirections.push({measure:a.measure,beat:0,sourcePart:a.sourcePart,label:a.literalText});
    n.displayExtenderChains=display.printed.extenderChains || [];
    // Preserve notation ties; source slurs/extenders remain separate decorations.
    const sourceRows = value => Array.isArray(value) ? value : value?.curves || value?.logicalConnections || [];
    const connections = sourceRows(n.sourceConnections);
    for (const connection of connections.filter(c => c.kind === "tie")) {
      const from = byId.get(connection.start || connection.fromSourceNoteId);
      if (from) from.tieTo = connection.end || connection.toSourceNoteId;
    }
    const ties = new Map(), slurs = new Map(), sourceSlurs = [...sourceRows(n.sourceSlurs), ...connections.filter(c => c.kind !== "tie")];
    for (const t of n.tokens) {
      const key = [t.sourcePart,t.voice,t.staff,t.pitch].join(":");
      if (t.tieStop && ties.has(key)) ties.get(key).tieTo = t.id;
      if (t.tieStart) ties.set(key,t); else if (t.tieStop) ties.delete(key);
      for (const mark of t.slurs || []) {
        const type = mark.type || mark.attributes?.type, number = mark.number || mark.attributes?.number || "1";
        const slurKey=[t.sourcePart,t.voice,t.staff,number].join(":");
        if (type === "stop" && slurs.has(slurKey)) {
          sourceSlurs.push({from:slurs.get(slurKey),to:t.id});slurs.delete(slurKey);
        }
        if (type === "start") slurs.set(slurKey,t.id);
      }
    }
    n.sourceSlurs = sourceSlurs;
    data.presentation = display;
    data.presentationEventsById = Object.fromEntries(eventsById);
    return data;
  }
  async function load(song) {
    if (!/^[a-z0-9-]+$/.test(song)) throw Error("Invalid recording");
    let response;
    for (const view of ["", "source-tempo-beats-v1", "key-changes-v1"]) {
      response = await fetch("/api/follow/demo?song=" + encodeURIComponent(song) + (view ? "&view=" + view : ""), {cache:"no-store"});
      if (response.ok) break;
      if (response.status !== 409) throw Error("Score unavailable");
    }
    if (!response.ok) throw Error("Score unavailable");
    const payload = await response.json();
    const layout = await fetch("/follow/layouts/" + song + ".json?v=20261027-1", {cache:"no-cache"});
    if (!layout.ok) throw Error("Display geometry unavailable");
    return normalize(payload, await layout.json());
  }
  const api = {normalize,load,id};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MusicUnifiedModel = api;
})(typeof window === "undefined" ? {} : window);

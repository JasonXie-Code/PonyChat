/* Candidate-local source annotation. It never schedules recording playback. */
(function (root) {
  "use strict";
  const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  function points(data) {
    const meta = data.sourceTempoBeats;
    if (!meta) return null;
    if (meta.schema !== "source-tempo-beats/v1" || meta.verified !== true || meta.recordingSchedule !== false ||
        meta.positionUnits !== "quarter-note-beats-from-source-start" ||
        !/^[a-f0-9]{64}$/.test(meta.canonicalSha256 || "") || !/^[a-f0-9]{64}$/.test(meta.evidenceSha256 || "") ||
        typeof meta.evidence !== "string" || !meta.evidence.trim() || !Array.isArray(meta.points) || !meta.points.length) {
      throw Error("Unverified source tempo offsets");
    }
    const measures = new Map(), starts = new Map();
    let quarter = 0;
    for (const m of data.measures || []) {
      if (!Number.isFinite(m.beatsPerMeasure) || m.beatsPerMeasure <= 0 || m.measure !== measures.size+1) throw Error("Invalid actual source meter");
      measures.set(m.measure, m);
      starts.set(m.measure, quarter);
      quarter += m.beatsPerMeasure;
    }
    meta.points.forEach((point, i) => {
      const bar = measures.get(point.measure), before = meta.points[i-1];
      if (!Number.isInteger(point.measure) || point.measure < 1 || !Number.isFinite(point.beatInMeasure) || point.beatInMeasure < 0 ||
          !Number.isFinite(point.bpm) || point.bpm <= 0 || !bar || point.beatInMeasure >= bar.beatsPerMeasure ||
          !Number.isFinite(point.quarter) || Math.abs(point.quarter-starts.get(point.measure)-point.beatInMeasure)>.00001 ||
          (!i && (point.measure !== 1 || point.beatInMeasure !== 0)) ||
          (i && (point.measure < before.measure || (point.measure === before.measure && point.beatInMeasure <= before.beatInMeasure)))) {
        throw Error("Unsupported source tempo position");
      }
    });
    const normalize = p => ({measure:p.measure, beatInMeasure:p.beatInMeasure, quarter:p.quarter, bpm:p.bpm});
    if (!Array.isArray(data.sourceTempoMap) || JSON.stringify(data.sourceTempoMap.map(normalize)) !== JSON.stringify(meta.points.map(normalize))) {
      throw Error("Source tempo tables disagree");
    }
    return meta.points;
  }
  function pointLabel(p, first = false) {
    const position = p.beatInMeasure, fraction = position - Math.floor(position);
    const beat = fraction === 0 ? `第 ${position+1} 拍` : fraction === .5 ? `第 ${Math.floor(position)+1} 拍后半` :
      `第 ${Number((position+1).toFixed(4))} 拍处（以四分音符计）`;
    return `${first ? "" : `第 ${p.measure} 小节${position ? ` ${beat}` : "起"} `}♩ = ${p.bpm}`;
  }
  function label(data) {
    const map = points(data);
    return map ? "原谱速度 · " + map.map((p, i) => pointLabel(p, !i)).join(" · ") : "";
  }
  function create(base) {
    return function (data, available, scale) {
      const map = points(data);
      const output = base(data, available, scale);
      if (!map) return output;
      const at = output.html.indexOf('<svg '), header = output.html.slice(0, at);
      const match = header.match(/^(<div class="jp-head"><strong>[^<]*<\/strong>)[\s\S]*(<span>[^<]*<\/span><\/div>)$/);
      if (at < 0 || !match) throw Error("Frozen notation header shape changed");
      const tempo = map.map((p, i) => `<span class="jp-source-tempo-point">${esc(pointLabel(p, !i))}</span>`).join(" · ");
      return {...output, html:match[1] + `<span>${esc(data.measures?.[0]?.timeSignature || "")}　原谱速度 · ${tempo}</span>` + match[2] + output.html.slice(at)};
    };
  }
  function showNotice(data) {
    const node = root.document?.getElementById("sourceTempoNotice");
    if (!node) return;
    const text = label(data);
    node.hidden = !text;
    node.textContent = text;
  }
  const api = {points, pointLabel, label, create};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    root.MusicNotation.render = create(root.MusicNotation.render);
    const fetch = root.fetch.bind(root);
    root.fetch = function (input, options) {
      let follow = false;
      if (typeof input === "string") {
        const url = new URL(input, root.location.href);
        if (url.origin === root.location.origin && url.pathname === "/api/follow/demo") {
          url.searchParams.set("view", "source-tempo-beats-v1");
          input = url.href;
          follow = true;
        }
      }
      const response = fetch(input, options);
      return follow ? response.then(async result => {
        if (result.ok) {
          const data = await result.clone().json();
          showNotice(data.jianpu || {});
        }
        return result;
      }) : response;
    };
  }
})(typeof window === "undefined" ? {} : window);

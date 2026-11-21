/* Candidate-local addon. The existing renderer and player remain byte-frozen. */
(function (root) {
  "use strict";
  function sections(data) {
    const map = data.sourceKeyChanges;
    if (!map) return null;
    if (map.schema !== "source-key-changes/v1" || map.verified !== true || typeof map.evidence !== "string" || !map.evidence.trim() ||
        !/^[a-f0-9]{64}$/.test(map.evidenceSha256 || "") || !Array.isArray(map.changes) || !map.changes.length) throw Error("Unverified key changes");
    const parts = [...new Set(data.tokens.filter(t => !t.isRest).map(t => t.sourcePart))].sort();
    map.changes.forEach((point, i) => {
      if (!Number.isInteger(point.measure) || point.measure < 1 || (!i && point.measure !== 1) ||
          (i && point.measure <= map.changes[i-1].measure) || point.mode !== "major" || !/^[A-G](?:#|b)?$/.test(point.tonic) ||
          JSON.stringify([...point.sourceParts].sort()) !== JSON.stringify(parts)) throw Error("Unsupported source key scope");
    });
    if (data.tonic !== map.changes[0].tonic) throw Error("Initial source tonic mismatch");
    const source = new Map(data.tokens.map(t => [String(t.id ?? t.eventIndex),t]));
    const nested = data.measures.flatMap(m => m.tokens);
    const canonical = v => v && typeof v === "object" ? (Array.isArray(v) ? v.map(canonical) : Object.fromEntries(Object.keys(v).sort().map(k => [k,canonical(v[k])]))) : v;
    const signature = t => JSON.stringify(canonical(Object.fromEntries(Object.entries(t).filter(([k]) => !["token","sourceTonic"].includes(k)))));
    if (source.size !== data.tokens.length || nested.length !== data.tokens.length || new Set(nested.map(t => String(t.id ?? t.eventIndex))).size !== nested.length || nested.some(t => !source.has(String(t.id ?? t.eventIndex)) || signature(t) !== signature(source.get(String(t.id ?? t.eventIndex))))) throw Error("Source token tables differ");
    const groups = map.changes.map((point, i) => {
      const measures = data.measures.filter(m => (!i || m.measure >= point.measure) && (!map.changes[i+1] || m.measure < map.changes[i+1].measure));
      const tokens = measures.flatMap(m => m.tokens);
      if (!measures.length || tokens.some(t => t.sourceTonic !== point.tonic)) throw Error("Missing local-tonic tokens");
      return {point, data:{...data,tonic:point.tonic,key:point.tonic+" major",measures,tokens}};
    });
    const groupOf = new Map(groups.flatMap((g, i) => g.data.tokens.map(t => [String(t.id ?? t.eventIndex),i])));
    for (const t of data.tokens) if (t.tieTo && groupOf.get(String(t.id ?? t.eventIndex)) !== groupOf.get(String(t.tieTo))) throw Error("Cross-key tie requires a reviewed extension");
    return groups;
  }
  function create(base) {
    return function render(data, available, scale = 1) {
      const groups = sections(data);
      if (!groups) return base(data, available, scale);
      let offset = 0;
      const rendered = groups.map(({point,data:segment}) => {
        const result = base(segment, available, scale);
        const html = result.html.replace(/data-row="(\d+)"/g, (_, row) => `data-row="${Number(row)+offset}"`);
        offset += result.geometry.rows.length;
        return {html:`<section class="jp-key-section" data-source-tonic="${point.tonic}"><div class="jp-key-caption">第 ${point.measure} 小节起 · 原谱调号</div>${html}</section>`,geometry:result.geometry};
      });
      return {html:rendered.map(x => x.html).join(""),geometry:{width:rendered[0].geometry.width,segments:rendered.map(x => x.geometry)}};
    };
  }
  const api = {create,sections};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    root.MusicNotation.render = create(root.MusicNotation.render);
    const fetch = root.fetch.bind(root);
    root.fetch = function (input, options) {
      if (typeof input === "string") {
        const url = new URL(input, root.location.href);
        if (url.origin === root.location.origin && url.pathname === "/api/follow/demo") {
          url.searchParams.set("view", "key-changes-v1");
          input = url.href;
        }
      }
      return fetch(input, options);
    };
  }
})(typeof window === "undefined" ? {} : window);

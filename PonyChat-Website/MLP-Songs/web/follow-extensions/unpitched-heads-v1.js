/* Candidate-local spoken-head display; five shared core files stay frozen. */
(function (root) {
  "use strict";
  const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;
  const degreePattern = /^(#{1,2}|b{1,2})?([0-7])([',]*)$/;
  const canonical = v => v && typeof v === "object" ? (Array.isArray(v) ? v.map(canonical) :
    Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])]))) : v;

  function headShape(token) {
    // Old frozen cross tokens retain the exact previous markup path.
    if (token.sourceNotehead === undefined) return null;
    const heads = token.sourceNotehead, display = token.sourceUnpitchedDisplay;
    if (!Array.isArray(heads) || heads.length !== 1 || heads[0]?.tag !== "notehead" ||
        !["x", "circle-x"].includes(heads[0].text) || !Array.isArray(heads[0].children) || heads[0].children.length ||
        !display || display.tag !== "unpitched" || !Array.isArray(display.children) ||
        display.children.some(child => !["display-step", "display-octave"].includes(child.tag)) ||
        ["time", "endTime", "eventIndex"].some(key => token[key] !== null) ||
        token.sourceOnlyUntimed !== true || token.skipCursorHighlight !== true || token.cursorPrimary !== false ||
        token.seekAllowed === true || Object.entries(token).some(([key, value]) => key.endsWith("Gold") && value !== false)) {
      throw Error("Typed unpitched shape must retain actual XML and untimed readonly scope");
    }
    return heads[0].text;
  }

  function sourceCrosses(data) {
    if (!data || !Array.isArray(data.tokens) || !Array.isArray(data.measures)) throw Error("Missing source token tables");
    const flat = new Map(), crosses = new Map(), physicalIds = new Set();
    for (const token of data.tokens) {
      const identity = token.id ?? token.eventIndex;
      if (identity === undefined || identity === null) throw Error("Source display identity is missing");
      const id = String(identity);
      if (flat.has(id)) throw Error("Ambiguous source token identity");
      flat.set(id, token);
      if (token.isUnpitched !== undefined && token.isUnpitched !== true && token.isUnpitched !== false) {
        throw Error("Unpitched source flag must be Boolean");
      }
      if (token.isUnpitched === true) {
        if (token.token !== "×" || token.isRest !== false || !idPattern.test(id) ||
            typeof token.sourcePhysicalId !== "string" || !idPattern.test(token.sourcePhysicalId) ||
            physicalIds.has(token.sourcePhysicalId) || ![null, undefined, ""].includes(token.pitch) ||
            ![null, undefined, ""].includes(token.sourcePitch) || ![null, undefined].includes(token.midi)) {
          throw Error("Spoken source cross needs a unique physical identity and no invented pitch");
        }
        physicalIds.add(token.sourcePhysicalId);
        headShape(token);
        crosses.set(id, token);
      } else if (!degreePattern.test(String(token.token))) {
        throw Error("Undeclared or invalid source glyph is not a spoken cross");
      }
    }
    const nested = data.measures.flatMap(m => m.tokens || []);
    const seen = new Set();
    if (nested.length !== data.tokens.length) throw Error("Flat and nested source counts differ");
    for (const token of nested) {
      const id = String(token.id ?? token.eventIndex);
      if (seen.has(id) || !flat.has(id) || JSON.stringify(canonical(token)) !== JSON.stringify(canonical(flat.get(id)))) {
        throw Error("Flat and nested source payloads differ");
      }
      seen.add(id);
    }
    return crosses;
  }

  function replaceCrosses(html, crosses, scale = 1) {
    if (typeof html !== "string") throw Error("Source renderer returned no SVG markup");
    const seen = new Set();
    const result = html.replace(/<g\b(?=[^>]*\bclass="[^"]*\bjp-note\b)([^>]*)>([\s\S]*?)<\/g>/g,
      (whole, attrs, body) => {
        const match = attrs.match(/\bdata-id="([^"]*)"/);
        const token = match && crosses.get(match[1]);
        const question = /(<text\b[^>]*\bclass="jp-digit"[^>]*>)\?(<\/text>)/g;
        const questions = [...body.matchAll(question)];
        if (!token) {
          if (questions.length) throw Error("Unknown numbered glyph has no typed unpitched identity");
          return whole;
        }
        if (questions.length !== 1) throw Error("Spoken cross lacks exactly one frozen-renderer placeholder");
        seen.add(match[1]);
        const shape = headShape(token);
        let replaced = body.replace(question, "$1×$2");
        if (shape === "circle-x") {
          const tag = questions[0][1], x = Number(tag.match(/\bx="([^"]+)"/)?.[1]), y = Number(tag.match(/\by="([^"]+)"/)?.[1]);
          if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(scale) || scale <= 0) {
            throw Error("Actual numbered glyph position required for a circle-x");
          }
          replaced += `<circle class="jp-unpitched-circle" cx="${x}" cy="${y-8*scale}" r="${11*scale}" fill="none" stroke="#8790a0" stroke-width="${1.5*scale}" aria-hidden="true"/>`;
        }
        if (shape) {
          const description = `原谱${shape === "circle-x" ? "圆圈叉" : "叉形"}无音高音头，时间未定位，仅供阅读`;
          attrs = attrs.replace(/\baria-label="([^"]*)"/, (_, label) => `aria-label="${label}，${description}"`);
        }
        return `<g${attrs} data-source-physical-id="${token.sourcePhysicalId}">${replaced}</g>`;
      });
    if (seen.size !== crosses.size || [...crosses.keys()].some(id => !seen.has(id))) {
      throw Error("A spoken physical head is absent from source rendering");
    }
    return result;
  }

  function create(base) {
    if (typeof base !== "function") throw Error("Frozen numbered renderer is unavailable");
    return function render(data, available, scale = 1) {
      const crosses = sourceCrosses(data);
      const result = base(data, available, scale);
      if (!crosses.size) return result;
      return {...result, html: replaceCrosses(result.html, crosses, scale)};
    };
  }

  const api = {create, sourceCrosses, replaceCrosses};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    if (!root.MusicNotation) throw Error("Frozen notation module is unavailable");
    root.MusicNotation.render = create(root.MusicNotation.render);
  }
})(typeof window === "undefined" ? {} : window);

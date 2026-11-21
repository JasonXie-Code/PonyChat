/* Printed separators are independent of the source word grouping used by alignment. */
(function (root) {
  "use strict";
  function displayScore(score) {
    const corrected = new Map();
    for (const token of score?.tokens || []) {
      if (token.printedHyphenAfter === false && ["begin", "middle"].includes(token.syllabic)) {
        corrected.set(token.id, {...token, syllabic: "single"});
      }
    }
    if (!corrected.size) return score;
    const replace = token => corrected.get(token.id) || token;
    return {...score, tokens: score.tokens.map(replace),
      measures: score.measures.map(measure => ({...measure, tokens: measure.tokens.map(replace)}))};
  }
  function install(win) {
    const cache = new WeakMap(), wrapped = new WeakSet();
    const display = score => {
      if (!score || typeof score !== "object") return score;
      if (!cache.has(score)) cache.set(score, displayScore(score));
      return cache.get(score);
    };
    const wrap = api => {
      if (!api || wrapped.has(api)) return api;
      for (const name of ["render", "layout"]) {
        const original = api[name];
        if (typeof original !== "function") continue;
        api[name] = function (score, ...args) { return original.call(this, display(score), ...args); };
      }
      wrapped.add(api);
      return api;
    };
    let api = wrap(win.MusicNotation);
    Object.defineProperty(win, "MusicNotation", {configurable: true, enumerable: true,
      get: () => api, set: value => {api = wrap(value);}});
    // If the async addon arrived after the first render, use the owner's existing
    // render callback at the same scale. No seek, audio state, or source data changes.
    if (win.document.querySelector(".jp-svg")) {
      win.document.getElementById("notationSize")?.dispatchEvent(new win.Event("change", {bubbles: true}));
    }
  }
  const api = {displayScore, install};
  if (typeof module === "object" && module.exports) module.exports = api;
  else install(root);
})(typeof window === "object" ? window : {});

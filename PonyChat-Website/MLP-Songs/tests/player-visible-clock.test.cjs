const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const nodes = new Map(), frames = new Map();
  let frameId = 0, writes = 0, time = 37.79;
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: false, listeners: {}, style: {setProperty() {}},
      addEventListener(name, callback) {this.listeners[name] = callback;},
      getAttribute() {return null;}, setAttribute() {}, removeAttribute() {},
    });
    return nodes.get(selector);
  };
  const audio = get('#audio'); audio.paused = false;
  Object.defineProperty(audio, 'currentTime', {get: () => time, set: value => {writes++; time = value;}});
  get('#followPane').hidden = true;
  const context = {document: {querySelector: get}, navigator: {}, location: {origin: 'https://music.example'},
    Audio: class {removeAttribute() {}}, window: {addEventListener() {}},
    requestAnimationFrame(callback) {frames.set(++frameId, callback); return frameId;},
    cancelAnimationFrame(id) {frames.delete(id);}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/player.js'), 'utf8'), context);
  const seen = [];
  context.window.MusicPlayer.setCallbacks({onTime: value => seen.push(value)});
  return {get, audio, seen, frames, player: context.window.MusicPlayer,
    time(value) {time = value;}, writes: () => writes,
    tick(stamp) {const entries = [...frames.values()]; frames.clear(); entries.forEach(fn => fn(stamp));}};
}

test('visible lyrics read the live clock across explicit ends without waiting for timeupdate or seeking', () => {
  const ui = harness();
  ui.player.syncFollow(); assert.equal(ui.seen.at(-1), 37.79);
  ui.time(37.81); ui.tick(40); assert.equal(ui.seen.at(-1), 37.81);
  ui.time(38.04); ui.tick(80); assert.equal(ui.seen.at(-1), 38.04);
  assert.equal(ui.writes(), 0);
  assert.equal(ui.frames.size, 1);
});

test('pause, hidden player, and queue stop animation; opening lyrics synchronizes immediately', () => {
  for (const stop of ['pause', 'player', 'queue']) {
    const ui = harness(); ui.player.syncFollow();
    if (stop === 'pause') ui.audio.paused = true;
    if (stop === 'player') ui.get('#nowPlaying').hidden = true;
    if (stop === 'queue') ui.get('#lyricsPane').hidden = true;
    const before = ui.seen.length; ui.time(38); ui.tick(40);
    assert.equal(ui.frames.size, 0); assert.equal(ui.seen.length, before);
    ui.get('#nowPlaying').hidden = false; ui.get('#lyricsPane').hidden = false;
    ui.player.syncFollow(); assert.equal(ui.seen.at(-1), 38);
    assert.equal(ui.frames.size, ui.audio.paused ? 0 : 1);
    assert.equal(ui.writes(), 0);
  }
});

test('repeated pane synchronization keeps one animation and pause updates the current lyric', () => {
  const ui = harness();
  ui.player.syncFollow(); ui.player.syncFollow(); assert.equal(ui.frames.size, 1);
  ui.audio.paused = true; ui.time(37.82); ui.audio.listeners.pause();
  assert.equal(ui.seen.at(-1), 37.82); assert.equal(ui.frames.size, 0);
});

test('the ended event synchronizes the final lyric clock without another timeupdate', () => {
  const ui = harness(); ui.audio.paused = true; ui.audio.ended = true; ui.time(39.912938);
  ui.audio.listeners.ended();
  assert.equal(ui.seen.at(-1), 39.912938); assert.equal(ui.frames.size, 0);
  assert.equal(ui.writes(), 0);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/analytics.js'), 'utf8');

function fixture() {
  const handlers = {}, events = [], beacon = [];
  let clock = 0, song = 'first-song', heartbeat, sequence = 0, offline = false;
  const audio = {currentTime: 0, playbackRate: 1, addEventListener(name, fn) { (handlers[name] ||= []).push(fn); }};
  const document = {getElementById: () => audio, addEventListener() {}};
  const window = {MusicPlayer: {current: () => ({id: song})}, addEventListener(name, fn) { handlers[name] = [fn]; }};
  vm.runInNewContext(source, {
    window, document, crypto: {randomUUID: () => `test-id-${String(++sequence).padStart(10, '0')}`},
    localStorage: {getItem: () => null, setItem() {}}, performance: {now: () => clock}, Blob,
    navigator: {sendBeacon: (_, blob) => { beacon.push(blob); return true; }},
    setInterval: fn => { heartbeat = fn; },
    fetch: async (_, options) => { if (offline) throw Error('offline'); events.push(JSON.parse(options.body)); return {ok: true}; },
  });
  return {events, beacon, fire: event => handlers[event]?.forEach(fn => fn()),
    tick(seconds, position = seconds) { clock += seconds * 1000; audio.currentTime += position; handlers.timeupdate?.forEach(fn => fn()); },
    flush: () => heartbeat(), offline: value => { offline = value; }, song: value => { song = value; }};
}
const settled = () => new Promise(resolve => setImmediate(resolve));

test('pause, buffering, seek and resume preserve one play and count audible wall time', async () => {
  const f = fixture(); await settled(); f.fire('playing'); await settled();
  f.tick(5); f.fire('pause'); await settled();
  f.tick(30, 0); f.fire('playing'); f.tick(3);
  f.fire('seeking'); f.tick(1, 90); f.fire('seeked');
  f.tick(2); f.fire('waiting'); f.tick(20, 0); f.fire('playing');
  f.tick(4); f.flush(); await settled();
  const plays = f.events.filter(e => e.kind === 'play');
  assert.equal(new Set(plays.map(e => e.id)).size, 1);
  assert.equal(plays.at(-1).seconds, 14);
  assert.equal(f.events.filter(e => e.kind === 'visit').length, 1);
});

test('ended or track change starts a new play while retries preserve IDs and the zero start', async () => {
  const f = fixture(); await settled();
  f.offline(true); f.fire('playing'); await settled(); f.tick(10); f.flush(); await settled();
  assert.equal(f.events.filter(e => e.kind === 'play').length, 0);
  f.offline(false); f.flush(); await settled();
  const retry = f.events.filter(e => e.kind === 'play');
  assert.equal(retry[0].seconds, 0);
  assert.equal(retry[1].seconds, 10);
  assert.equal(retry[0].id, retry[1].id);
  f.fire('ended'); f.song('second-song'); f.fire('loadstart'); f.fire('playing');
  f.tick(2); f.flush(); await settled();
  const plays = f.events.filter(e => e.kind === 'play');
  assert.equal(new Set(plays.map(e => e.id)).size, 2);
  assert.equal(plays.at(-1).song, 'second-song');
  assert.equal(plays.at(-1).seconds, 2);
});

test('pagehide sends the final partial interval and playback rate does not inflate minutes', async () => {
  const f = fixture(); await settled(); f.fire('playing'); await settled();
  f.tick(3, 6); f.fire('pagehide');
  const last = JSON.parse(await f.beacon.at(-1).text());
  assert.equal(last.seconds, 3);
});

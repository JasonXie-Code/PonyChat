const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(withServiceWorker = true, installed = null) {
  const messages = [], audioListeners = {};
  let updates = 0, registrations = 0;
  const callbacks = {};
  const player = {setCallbacks(value) {Object.assign(callbacks, value);}};
  const audio = {paused: false, readyState: 4, duration: 100, currentTime: 5,
    muted: false, currentSrc: 'https://music.example/audio/a.flac?v=a', loads: 0,
    load() {this.loads++; this.currentSrc = ''; this.readyState = 0; this.currentTime = 0; this.error = null;},
    buffered: {length: 1, start: () => 0, end: () => 40},
    addEventListener(type, fn) {(audioListeners[type] ||= new Set()).add(fn);},
    removeEventListener(type, fn) {audioListeners[type]?.delete(fn);}};
  const button = new EventTarget(), slider = new EventTarget();
  const mode = new EventTarget();
  mode.textContent = '顺序播放';
  class Warmer {
    removeAttribute() {this.src = '';}
    load() {}
  }
  const warmer = new Warmer();
  button.setAttribute = (key, value) => {button[key] = value;};
  button.dataset = {};
  slider.value = '100';
  const service = {
    controller: installed && {scriptURL: installed, postMessage(value) {messages.push(value);}},
    getRegistration: async () => installed ? {scope: 'https://music.example/',
      active: {scriptURL: installed}, update: async () => {updates++;}} : undefined,
    register: async () => {registrations++;},
  };
  const context = {URL, Event, Audio: function () {return warmer;},
    navigator: {serviceWorker: withServiceWorker ? service : undefined},
    document: {querySelector: id => ({'#audio': audio, '#toggleMute': button, '#vol': slider, '#playMode': mode})[id]},
    location: {origin: 'https://music.example', href: 'https://music.example/'},
    window: {MusicPlayer: player}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/audio-preload.js'), 'utf8'), context);
  player.setCallbacks({onSong() {}});
  return {audio, messages, player, button, slider, warmer, mode, callbacks, output: value => {context.window.MusicAudioOutput = value;},
    updates: () => updates, registrations: () => registrations,
    song(song) {audio.src = song ? new URL(song.src, context.location.href).href : ''; callbacks.onSong(song);},
    fire(type) {for (const callback of [...(audioListeners[type] || [])]) callback();}};
}

const songs = ['a', 'b', 'c'].map(id => ({id, src: `/audio/${id}.flac?v=${id}`}));

test('volume toggle preserves the slider and changes the restored mute state during a handoff', () => {
  const ui = harness();
  ui.slider.value = '37';
  ui.slider.dispatchEvent(new Event('input'));
  ui.button.dispatchEvent(new Event('click'));
  assert.equal(ui.audio.muted, true);
  assert.equal(ui.slider.value, '37');
  ui.song(songs[1]);
  ui.button.dispatchEvent(new Event('click'));
  assert.equal(ui.audio.muted, true);
  ui.audio.currentSrc = 'https://music.example/audio/b.flac?v=b';
  ui.audio.readyState = 2;
  ui.fire('loadeddata');
  assert.equal(ui.audio.muted, false);
  assert.equal(ui.slider.value, '37');
  ui.slider.value = '0';
  ui.slider.dispatchEvent(new Event('input'));
  ui.button.dispatchEvent(new Event('click'));
  assert.equal(ui.slider.value, '37');
  assert.equal(ui.button['aria-pressed'], 'false');
});

test('switching flushes the old decoder and waits for the selected recording data', () => {
  const ui = harness(); let calls = 0;
  ui.player.setCallbacks({onSong: () => calls++});
  ui.player.setCallbacks({onTime() {}});
  ui.song(songs[1]);
  assert.equal(ui.audio.loads, 1);
  assert.equal(ui.audio.currentSrc, '');
  assert.equal(ui.audio.readyState, 0);
  assert.equal(ui.audio.muted, true);
  assert.equal(calls, 1);
  ui.audio.currentSrc = 'https://music.example/audio/a.flac?v=a';
  ui.audio.readyState = 2; ui.fire('loadeddata');
  assert.equal(ui.audio.muted, true);
  ui.audio.currentSrc = ui.audio.src; ui.fire('loadeddata');
  assert.equal(ui.audio.muted, false);
});

test('rapid replacements retain the original mute state and clear stale listeners', () => {
  const ui = harness();
  ui.song(songs[1]); ui.song(songs[2]);
  assert.equal(ui.audio.loads, 2);
  ui.audio.currentSrc = 'https://music.example/audio/b.flac?v=b';
  ui.audio.readyState = 2; ui.fire('loadeddata');
  assert.equal(ui.audio.muted, true);
  ui.audio.currentSrc = ui.audio.src; ui.fire('loadeddata');
  assert.equal(ui.audio.muted, false);
  ui.audio.muted = true; ui.song(songs[0]);
  ui.audio.currentSrc = ui.audio.src; ui.audio.readyState = 2; ui.fire('loadeddata');
  assert.equal(ui.audio.muted, true);
  ui.audio.muted = false; ui.song(songs[1]); ui.song(null);
  assert.equal(ui.audio.muted, false);
  ui.fire('loadeddata');
  assert.equal(ui.audio.muted, false);
});

test('source handoff works when service workers are unavailable and after loading errors', () => {
  const ui = harness(false);
  ui.song(songs[1]);
  assert.equal(ui.audio.muted, true);
  ui.audio.error = {code: 2}; ui.fire('error');
  assert.equal(ui.audio.muted, false);
  ui.song(songs[2]);
  assert.equal(ui.audio.error, null);
  ui.audio.currentSrc = ui.audio.src; ui.audio.readyState = 3; ui.fire('playing');
  assert.equal(ui.audio.muted, false);
});

test('the PCM gate stays closed until the selected recording is playing', () => {
  const ui = harness();
  const actions = [];
  ui.output({hold: () => actions.push('hold'), open: () => actions.push('open'), smooth: () => true});
  ui.song(songs[1]);
  assert.equal(ui.audio.muted, false);
  ui.audio.readyState = 4;
  ui.audio.currentSrc = 'https://music.example/audio/a.flac?v=a';
  ui.fire('playing');
  ui.audio.currentSrc = ui.audio.src;
  ui.fire('loadeddata');
  assert.deepEqual(actions, ['hold']);
  ui.fire('playing');
  assert.deepEqual(actions, ['hold', 'open']);
});

test('sequential warming follows actual playback and is cleared in shuffle', () => {
  const ui = harness();
  ui.song(songs[0]);
  ui.callbacks.onQueue(songs, 0);
  assert.equal(ui.warmer.src, undefined);
  ui.audio.currentSrc = ui.audio.src;
  ui.audio.readyState = 3;
  ui.fire('playing');
  assert.equal(ui.warmer.preload, 'auto');
  assert.equal(ui.warmer.src, 'https://music.example/audio/b.flac?v=b');
  ui.song(songs[1]);
  ui.callbacks.onQueue(songs, 1);
  assert.equal(ui.warmer.src, ui.audio.src);
  ui.audio.currentSrc = ui.audio.src;
  ui.audio.readyState = 3;
  ui.fire('playing');
  assert.equal(ui.warmer.src, 'https://music.example/audio/c.flac?v=c');
  ui.mode.textContent = '随机播放';
  ui.mode.dispatchEvent(new Event('click'));
  assert.equal(ui.warmer.src, '');
});

test('only the legacy audio worker is cleared and updated', async () => {
  const old = harness(true, 'https://music.example/audio-preload-worker.js');
  const clean = harness();
  const other = harness(true, 'https://music.example/other-worker.js');
  await Promise.resolve();
  assert.equal(old.messages[0]?.type, 'music-preload-clear');
  assert.equal(old.updates(), 1);
  assert.equal(clean.messages.length, 0);
  assert.equal(clean.updates(), 0);
  assert.equal(other.messages.length, 0);
  assert.equal(other.updates(), 0);
  assert.equal(old.registrations() + clean.registrations() + other.registrations(), 0);
});

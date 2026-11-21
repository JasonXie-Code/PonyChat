const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function setup() {
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; }
    setAttribute() {}
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    get innerHTML() { return this.textContent || ''; }
    set innerHTML(value) { this.markup = value; }
  }
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, new Element('div'));
    return nodes.get(selector);
  };
  const ctx = {document: {querySelector: get, querySelectorAll: () => [],
    createElement: tag => new Element(tag)}, window: {MusicPlayer: {current: () => null}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/recording-credits.js'), 'utf8'), ctx);
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/library.js'), 'utf8'), ctx);
  return {library: ctx.window.MusicLibrary, get, Element};
}

test('normalized recording displays its served format and uses a FLAC download name without changing source fields', () => {
  const ui = setup();
  const song = Object.freeze({title: 'Find A Pet Song', src: '/audio/original.mp3',
    ext: 'mp3', bitrate: 320, normalizedPeakDbfs: -0.1000496});
  ui.get('#nowQuality').textContent = 'MP3 · 320 kbps';
  ui.get('#downloadCurrent').href = song.src;
  ui.library.updateAudioPresentation(song);
  assert.equal(ui.get('#nowQuality').textContent, 'FLAC · 峰值 −0.1 dBFS');
  assert.equal(ui.get('#downloadCurrent').download, 'Find A Pet Song.flac');
  assert.equal(ui.get('#downloadCurrent').href, '/audio/original.mp3');
  assert.equal(song.ext, 'mp3');
});

test('legacy API and empty queue retain frozen-player MP3 presentation', () => {
  const ui = setup();
  for (const normalizedPeakDbfs of [undefined, null, '-0.1', NaN]) {
    ui.get('#nowQuality').textContent = 'MP3 · 192 kbps';
    ui.library.updateAudioPresentation({title: 'Legacy', normalizedPeakDbfs});
    assert.equal(ui.get('#nowQuality').textContent, 'MP3 · 192 kbps');
    assert.equal(ui.get('#downloadCurrent').download, 'Legacy.mp3');
  }
  ui.get('#nowQuality').textContent = '';
  ui.library.updateAudioPresentation(null);
  assert.equal(ui.get('#nowQuality').textContent, '');
});

test('Opus playback labels the bitrate and downloads with the .opus extension', () => {
  const ui = setup();
  ui.library.updateAudioPresentation({title: 'Opus recording', normalizedPeakDbfs: -0.47,
    normalizedAudioExt: 'opus', normalizedAudioBitrate: 320});
  assert.equal(ui.get('#nowQuality').textContent, 'Opus · 320 kbps');
  assert.equal(ui.get('#downloadCurrent').download, 'Opus recording.opus');
});

test('song row downloads use each recording format while retaining the API URL', () => {
  const ui = setup(), container = new ui.Element('section');
  const normalized = Object.freeze({id: 'new', title: 'Normalized', src: '/audio/new.mp3',
    versionKind: 'original', normalizedPeakDbfs: -0.1});
  const legacy = Object.freeze({id: 'old', title: 'Legacy', src: '/audio/old.mp3', versionKind: 'original'});
  ui.library.rowList(container, [normalized, legacy]);
  const links = [];
  const visit = node => { if (node.tagName === 'a') links.push(node); node.children.forEach(visit); };
  visit(container);
  assert.deepEqual(links.map(link => [link.download, link.href]), [
    ['Normalized.flac', '/audio/new.mp3'], ['Legacy.mp3', '/audio/old.mp3']]);
});

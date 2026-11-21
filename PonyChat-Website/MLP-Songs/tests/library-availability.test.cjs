const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const deferred = () => {let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject};};
const settle = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const nodes = new Map(), timers = new Map(), badges = [];
  let current = null, queue = [], timer = 0, lyricsUpdates = 0, clock = 0;
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: true, attrs: {}, classList: {toggle() {}},
      removeAttribute(name) {delete this.attrs[name];},
      getAttribute(name) {return this.attrs[name] || null;},
      set src(value) {this.attrs.src = value;}, get src() {return this.attrs.src;},
    });
    return nodes.get(selector);
  };
  const document = {querySelector: get, querySelectorAll: () => [], documentElement: {dataset: {}}};
  const window = {MusicPlayer: {current: () => current, getQueue: () => queue, syncFollow() {}},
    MusicLyrics: {update() {lyricsUpdates++;}, refresh() {}},
    MusicFollowBadges: {setSongs(songs) {badges.push(songs);}}};
  const context = {document, window, navigator: {}, Date: {now: () => clock}, clearTimeout: id => timers.delete(id),
    setTimeout: fn => {timers.set(++timer, fn); return timer;}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/library.js'), 'utf8'), context);
  return {context, window, get, document, badges, library: window.MusicLibrary,
    select(song, list = song ? [song] : []) {current = song; queue = list;},
    flush() {const work = [...timers.values()]; timers.clear(); work.forEach(fn => fn());},
    advance(ms) {clock += ms;}, timerCount: () => timers.size,
    current: () => current, queue: () => queue, lyricsUpdates: () => lyricsUpdates};
}
const accepted = {id: 'one', followId: 'one-score', followViewPath: '/follow-media/generated/one-score/accepted-frontend/frame.html'};

test('preview matches the exact recording and yields to a formally admitted reader', async () => {
  const h = harness(), song = {id: 'one', src: '/audio/original.mp3'};
  h.context.fetch = async path => {
    assert.equal(path, '/follow/layouts/preview/index.json');
    return {ok: true, json: async () => [{songId: song.id, src: song.src, followId: 'one-preview'}]};
  };
  h.select({...song, src: '/audio/alternate.mp3'});
  await h.library.validateFollows([song], async () => ({songs: []}));
  await settle();
  assert.equal(h.get('#followTab').hidden, true);
  h.select(song);
  h.library.prefetchFollow(song);
  h.flush();
  assert.equal(h.get('#followTab').textContent, '跟谱试用');
  assert.match(h.get('#followFrame').src, /&song=one-preview&preview=1$/);
  assert.equal(song.followId, undefined);
  h.library.applyFollowAvailability([song], [{...accepted, src: song.src}]);
  h.flush();
  assert.equal(h.get('#followTab').textContent, '跟谱');
  assert.match(h.get('#followFrame').src, /&song=one-score$/);
});

test('base catalog becomes rendered and interactive while strict validation is still pending', async () => {
  const h = harness(), validation = deferred(), calls = [], rendered = [];
  const baseSong = {id: 'one', title: 'Base', followId: 'untrusted', followViewPath: '/old'};
  const state = {};
  h.window.MusicLibrary.init = () => rendered.push('init');
  h.window.MusicPlayer.setCallbacks = callbacks => {h.callbacks = callbacks;};
  h.window.MusicLibrary.prefetchFollow = () => {};
  h.window.MusicLibrary.updateAudioPresentation = () => {};
  h.window.MusicLibrary.markPlaying = () => {};
  h.window.MusicLibrary.selectPane = () => {};
  Object.assign(h.context, {state, performance: {now: () => 321.25},
    api: path => {calls.push(path); return path === '/api/library' ?
      Promise.resolve({albums: [{id: 'album'}], songs: [baseSong], scores: []}) : validation.promise;},
    renderSidebar: () => rendered.push('sidebar'), renderAlbumGrid: () => rendered.push('albums'),
    renderScores: () => rendered.push('scores'), updateSidebarSections: () => rendered.push('sections')});
  const app = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
  const start = app.indexOf('  async function load() {'), end = app.indexOf('  /* ── 播放器事件', start);
  await vm.runInNewContext(app.slice(start, end) + '\nload();', h.context);
  assert.deepEqual(calls, ['/api/library', '/api/songs']);
  assert.deepEqual(rendered, ['init', 'sidebar', 'albums', 'sections']);
  assert.equal(h.document.documentElement.dataset.libraryReadyMs, '321.25');
  assert.equal(h.document.documentElement.dataset.libraryReady, 'true');
  assert.equal(baseSong.followId, undefined);
  assert.strictEqual(state.songs[0], baseSong);
  assert.equal(typeof h.callbacks.onSong, 'function');
  validation.resolve({songs: [accepted]});
  await validation.promise; await Promise.resolve();
  assert.equal(baseSong.followId, 'one-score');
});

test('late validation updates exact current and queue references without replacing playback or user state', async () => {
  const h = harness(), base = {id: 'one', title: 'Base', src: '/original.mp3'}, clone = {...base};
  const other = {id: 'two', followId: 'stale', followViewPath: '/old'};
  const queue = [clone, other], pending = deferred();
  h.select(clone, queue);
  Object.assign(h.get('#audio'), {currentTime: 89, paused: false, src: '/original.mp3'});
  h.get('#q').value = 'user search'; h.get('#nowPlaying').hidden = false;
  const work = h.library.validateFollows([base, other], () => pending.promise);
  assert.equal(clone.followId, undefined);
  pending.resolve({songs: [{...accepted, title: 'Must not replace', src: '/original.mp3'}]});
  await work; h.flush();
  assert.strictEqual(h.current(), clone); assert.strictEqual(h.queue(), queue);
  assert.equal(base.followId, 'one-score'); assert.equal(clone.followId, 'one-score');
  assert.equal(other.followId, undefined); assert.equal(other.followViewPath, undefined);
  assert.equal(clone.title, 'Base'); assert.equal(clone.src, '/original.mp3');
  assert.equal(h.get('#audio').currentTime, 89); assert.equal(h.get('#audio').paused, false);
  assert.equal(h.get('#q').value, 'user search'); assert.equal(h.get('#nowPlaying').hidden, false);
  assert.equal(h.get('#followTab').hidden, false);
  assert.match(h.get('#followFrame').src, /^\/follow\/unified\/index\.html\?v=[\d-]+&song=one-score$/);
});

test('same ID cannot grant a new recording follow to a currently playing older source URL', async () => {
  const h = harness(), base = {id: 'one', src: '/new-recording.mp3'}, playing = {id: 'one', src: '/old-recording.mp3'};
  h.select(playing, [playing]); h.get('#audio').currentTime = 61; h.get('#audio').paused = false;
  await h.library.validateFollows([base], async () => ({songs: [{...accepted, src: '/new-recording.mp3'}]}));
  h.flush();
  assert.equal(base.followId, 'one-score'); assert.equal(playing.followId, undefined);
  assert.equal(h.get('#followTab').hidden, true); assert.equal(h.get('#followFrame').src, undefined);
  assert.equal(playing.src, '/old-recording.mp3'); assert.equal(h.get('#audio').currentTime, 61);
  assert.equal(h.get('#audio').paused, false);
  const mismatch = {id: 'one', src: '/old-recording.mp3'};
  h.library.applyFollowAvailability([mismatch], [{...accepted, src: '/new-recording.mp3'}]);
  assert.equal(mismatch.followId, undefined);
});

test('switching recordings or clearing queue during validation never preloads the old selection', async () => {
  for (const next of [{id: 'two'}, null]) {
    const h = harness(), first = {id: 'one'}, pending = deferred(); h.select(first);
    const work = h.library.validateFollows([first], () => pending.promise);
    h.select(next); pending.resolve({songs: [accepted]}); await work; h.flush();
    assert.equal(first.followId, 'one-score'); assert.equal(h.get('#followTab').hidden, true);
    assert.equal(h.get('#followFrame').src, undefined);
  }
});

test('failure or malformed validation removes stale entries without preventing ordinary playback', async () => {
  for (const response of [() => Promise.reject(Error('offline')), () => Promise.resolve({})]) {
    const h = harness(), song = {...accepted}; h.select(song);
    h.get('#audio').currentTime = 52; h.get('#audio').paused = false;
    h.get('#followFrame').attrs.src = '/old-reader';
    await h.library.validateFollows([song], response); h.flush();
    assert.equal(song.followId, undefined); assert.equal(song.followViewPath, undefined);
    assert.equal(h.get('#followTab').hidden, true); assert.equal(h.get('#followFrame').src, undefined);
    assert.equal(h.get('#audio').currentTime, 52); assert.equal(h.get('#audio').paused, false);
  }
});

test('an older response cannot re-admit a recording after a newer validation result', async () => {
  const h = harness(), song = {id: 'one'}, older = deferred(), newer = deferred(); h.select(song);
  const a = h.library.validateFollows([song], () => older.promise);
  const b = h.library.validateFollows([song], () => newer.promise);
  newer.resolve({songs: []}); await b;
  older.resolve({songs: [accepted]}); await a;
  assert.equal(song.followId, undefined); assert.equal(h.get('#followTab').hidden, true);
});

test('search rendered before validation keeps the canonical recording reference for later clicks', async () => {
  const h = harness(), song = {id: 'one', title: 'Base', albumTitle: '', characters: []};
  const rows = [], source = fs.readFileSync(require.resolve('../web/library.js'), 'utf8');
  const start = source.indexOf('  async function search(q) {'), end = source.indexOf('  function albumSongs', start);
  h.get('#q').value = 'Base';
  for (const selector of ['#panelMusic', '#albumGrid', '#trackPanel', '#searchResults']) {
    h.get(selector).classList.add = () => {}; h.get(selector).classList.remove = () => {};
  }
  const context = {data: {songs: [song]}, searchRequest: 0, $: h.get, credits: {searchTerms: () => []},
    showVersions: () => false, visible: songs => songs, rowList: (_, songs) => rows.push(songs),
    fetch: async () => ({ok: true, json: async () => ({songs: [{id: 'one', lyricSnippet: 'result lyric'}]})})};
  await vm.runInNewContext(source.slice(start, end) + '\nsearch("Base");', context);
  assert.strictEqual(rows[rows.length - 1][0], song);
  h.library.applyFollowAvailability([song], [accepted]);
  assert.equal(rows[rows.length - 1][0].followId, 'one-score');
  assert.equal(song.lyricSnippet, 'result lyric');
});

const warming = () => Object.assign(Error('warming'), {status: 503, warming: true, retryAfterMs: 3000});

test('explicit reader warming retries in the background then admits the current recording', async () => {
  const h = harness(), song = {id: 'one'}; h.select(song);
  h.get('#audio').currentTime = 44; h.get('#audio').paused = false;
  let calls = 0;
  const work = h.library.validateFollows([song], async () => {
    if (++calls === 1) throw warming();
    return {songs: [accepted]};
  });
  await settle();
  assert.equal(calls, 1); assert.equal(h.timerCount(), 1);
  assert.equal(song.followId, undefined); assert.equal(h.get('#followTab').hidden, true);
  h.advance(3000); h.flush(); await work; h.flush();
  assert.equal(calls, 2); assert.equal(song.followId, 'one-score');
  assert.equal(h.get('#audio').currentTime, 44); assert.equal(h.get('#audio').paused, false);
  assert.match(h.get('#followFrame').src, /^\/follow\/unified\/index\.html\?v=[\d-]+&song=one-score$/);
});

test('switching or clearing during reader warming only prepares the latest selection', async () => {
  for (const next of [{id: 'two'}, null]) {
    const h = harness(), first = {id: 'one'}, second = {id: 'two'}; h.select(first);
    let calls = 0;
    const work = h.library.validateFollows([first, second], async () => {
      if (++calls === 1) throw warming();
      return {songs: [accepted]};
    });
    await settle(); h.select(next);
    h.flush(); await work; h.flush();
    assert.equal(calls, 2); assert.equal(first.followId, 'one-score');
    assert.equal(h.get('#followTab').hidden, true); assert.equal(h.get('#followFrame').src, undefined);
  }
});

test('new validation cancels a warming timer and prevents its stale request from running', async () => {
  const h = harness(), song = {id: 'one'}; h.select(song);
  let oldCalls = 0;
  const older = h.library.validateFollows([song], async () => {oldCalls++; throw warming();});
  await settle(); assert.equal(h.timerCount(), 1);
  await h.library.validateFollows([song], async () => ({songs: [accepted]}));
  await older; h.flush();
  assert.equal(oldCalls, 1); assert.equal(song.followId, 'one-score');
});

test('ordinary failures never retry and reader warming stops at the twenty-minute deadline', async () => {
  for (const failure of [Object.assign(Error('503'), {status: 503}),
    Object.assign(Error('500'), {status: 500, warming: true}), Error('network')]) {
    const h = harness(); let calls = 0;
    await h.library.validateFollows([{id: 'one'}], async () => {calls++; throw failure;});
    assert.equal(calls, 1); assert.equal(h.timerCount(), 0);
  }
  const h = harness(); let calls = 0;
  const work = h.library.validateFollows([{id: 'one'}], async () => {calls++; throw warming();});
  await settle();
  h.advance(20 * 60 * 1000); h.flush(); await work;
  assert.equal(calls, 1); assert.equal(h.timerCount(), 0);
});

test('API errors retain only the explicit warming signal with bounded retry delay', async () => {
  const source = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
  const start = source.indexOf('  async function api(path) {'), end = source.indexOf('  function albumTitle', start);
  for (const [header, retry, expected] of [['readers', '3', 3000], ['readers', '0', 1000],
    ['readers', '99', 30000], ['readers', 'bad', 3000], [null, null, 3000]]) {
    const context = {fetch: async () => ({ok: false, status: 503,
      headers: {get: name => name === 'X-Music-Warming' ? header : retry}})};
    await assert.rejects(vm.runInNewContext(source.slice(start, end) + '\napi("/api/songs");', context), error => {
      assert.equal(error.status, 503); assert.equal(error.warming, header === 'readers');
      assert.equal(error.retryAfterMs, expected); return true;
    });
  }
});

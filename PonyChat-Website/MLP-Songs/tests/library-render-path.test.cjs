const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('score matching normalizes each score title once and preserves first matching score semantics', () => {
  const source = fs.readFileSync(require.resolve('../web/library.js'), 'utf8');
  const start = source.indexOf('  function enrich() {'), end = source.indexOf('  function rowList', start);
  let normalized = 0;
  const score = (id, title) => ({id, title: {toLowerCase() {normalized++; return title.toLowerCase();}}});
  const data = {albums: [{id: 'season-one', title: 'Season', cover: '/cover'}],
    scores: [score('first', 'My Great Song R1'), score('later', 'My Great Song R2')],
    songs: [{title: 'My Great Song', albumId: 'season-one'}, {title: 'My Great Song', albumId: 'season-one'},
      {title: 'Short', albumId: 'season-one'}, {title: 'Unmatched', albumId: 'season-one'}]};
  vm.runInNewContext(source.slice(start, end) + '\nenrich();', {data});
  assert.equal(normalized, 2);
  assert.deepEqual(data.songs.map(s => s.scoreId), ['first', 'first', undefined, undefined]);
  assert.equal(data.songs[0].albumTitle, 'Season'); assert.equal(data.songs[0].cover, '/cover');
});

test('Pony Town albums appear after the original catalog in release order', () => {
  const source = fs.readFileSync(require.resolve('../web/library.js'), 'utf8');
  const start = source.indexOf('  function enrich() {'), end = source.indexOf('  function rowList', start);
  const albums = [
    {id: 'soundtracks-pony-town-a', releaseDate: '2025-09-26'},
    {id: 'equestria-girls-2015'},
    {id: 'soundtracks-pony-town-z', releaseDate: '2017-08-28'},
    {id: 'season-01'},
    {id: 'rainbow-roadtrip-2019'},
    {id: 'credits'},
    {id: 'season-09-2019a'},
  ];
  vm.runInNewContext(source.slice(start, end) + '\nenrich();', {data: {albums, songs: [], scores: []}});
  assert.deepEqual(albums.map(album => album.id), [
    'season-01', 'season-09-2019a', 'credits', 'equestria-girls-2015', 'rainbow-roadtrip-2019',
    'soundtracks-pony-town-z', 'soundtracks-pony-town-a',
  ]);
});

test('albums without official tracks remain playable with the versions toggle off', () => {
  const source = fs.readFileSync(require.resolve('../web/library.js'), 'utf8');
  const filterStart = source.indexOf('  function defaultVisible('), filterEnd = source.indexOf('  function audioDownloadName', filterStart);
  const albumStart = source.indexOf('  function albumSongs('), albumEnd = source.indexOf('  function openNow', albumStart);
  let showVersions = false;
  const tracks = [
    {id: 'credit-1', albumId: 'credits', track: 1, releaseKind: 'credits'},
    {id: 'official', albumId: 'season', track: 1, releaseKind: 'official', showByDefault: false},
    {id: 'instrumental', albumId: 'season', track: 2, releaseKind: 'instrumental'},
    {id: 'ai', albumId: 'season', track: 3, releaseKind: 'ai-generated', showByDefault: true},
    {id: 'hidden-ai', albumId: 'season', track: 4, releaseKind: 'ai-generated', showByDefault: false},
    {id: 'string-flag', albumId: 'season', track: 5, releaseKind: 'ai-generated', showByDefault: 'true'},
    {id: 'number-flag', albumId: 'season', track: 6, releaseKind: 'ai-generated', showByDefault: 1},
    {id: 'credit-2', albumId: 'credits', track: 2, releaseKind: 'credits'},
    {id: 'replaced', albumId: 'season', track: 7, releaseKind: 'official', showByDefault: true, supersededBy: 'official'},
    {id: 'credit-old', albumId: 'credits', track: 0, releaseKind: 'credits', supersededBy: 'credit-1'},
    {id: 'only-old', albumId: 'retired-only', track: 1, releaseKind: 'official', supersededBy: 'official'},
    {id: 'different-remix', albumId: 'season', track: 8, releaseKind: 'official', versionKind: 'instrumental'},
    {id: 'empty-marker', albumId: 'season', track: 9, releaseKind: 'official', supersededBy: ''},
  ];
  const scope = {data: {songs: tracks}, $: () => ({getAttribute: () => String(showVersions)})};
  const albumSongs = vm.runInNewContext(source.slice(filterStart, filterEnd) + source.slice(albumStart, albumEnd)
    + '\nalbumSongs;', scope);
  const ids = id => Array.from(albumSongs(id), song => song.id);
  assert.deepEqual(ids('credits'), ['credit-1', 'credit-2']);
  assert.deepEqual(ids('season'), ['official', 'ai', 'different-remix', 'empty-marker']);
  assert.deepEqual(ids('retired-only'), []);
  showVersions = true;
  assert.deepEqual(ids('season'), ['official', 'instrumental', 'ai', 'hidden-ai', 'string-flag', 'number-flag', 'different-remix', 'empty-marker']);
  assert.deepEqual(ids('credits'), ['credit-1', 'credit-2']);
  assert.deepEqual(ids('retired-only'), []);
  delete tracks.find(song => song.id === 'replaced').supersededBy;
  assert(ids('season').includes('replaced'));
});

test('local and API-backed search keep superseded recordings hidden in both version modes', async () => {
  const source = fs.readFileSync(require.resolve('../web/library.js'), 'utf8');
  const filterStart = source.indexOf('  function defaultVisible('), filterEnd = source.indexOf('  function audioDownloadName', filterStart);
  const searchStart = source.indexOf('  async function search(q) {'), searchEnd = source.indexOf('  function albumSongs', searchStart);
  for (const versions of [false, true]) {
    const tracks = [
      {id: 'old', title: 'Song', releaseKind: 'official', showByDefault: true, supersededBy: 'new'},
      {id: 'new', title: 'Song', releaseKind: 'official'},
      {id: 'remix', title: 'Song Remix', releaseKind: 'official'},
      {id: 'demo', title: 'Song Demo', releaseKind: 'other'},
    ];
    const renders = [];
    const node = {value: 'Song', classList: {add() {}, remove() {}}, getAttribute: () => String(versions)};
    const scope = {
      data: {songs: tracks}, searchRequest: 0, $: () => node,
      credits: {searchTerms: () => []}, rowList: (_, rows) => renders.push(Array.from(rows, row => row.id)),
      fetch: async () => ({ok: true, json: async () => ({songs: tracks.map(song => ({id: song.id, lyricSnippet: 'server snippet'}))})}),
    };
    await vm.runInNewContext(source.slice(filterStart, filterEnd) + source.slice(searchStart, searchEnd)
      + '\nsearch("Song");', scope);
    assert.equal(renders.length, 2);
    for (const ids of renders) assert.deepEqual(ids, versions ? ['new', 'remix', 'demo'] : ['new', 'remix']);
    assert.equal(tracks[0].supersededBy, 'new');
    assert.equal(tracks.length, 4);
  }
});

test('opening another album replaces or hides its release date and introduction', () => {
  const source = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
  const start = source.indexOf('  function openAlbum('), end = source.indexOf('  /* ── 侧边栏筛选', start);
  const releaseTime = {}, release = {querySelector: () => releaseTime}, description = {};
  const classList = {add() {}, remove() {}, contains: () => false};
  const tracks = [{id: 'one'}];
  const openAlbum = vm.runInNewContext(source.slice(start, end) + '\nopenAlbum;', {
    state: {albums: [{id: 'new', releaseDate: '2026-09-11', description: '舞厅更新配乐。'}, {id: 'old'}]},
    $: selector => ({'#albumRelease': release, '#albumDescription': description}[selector] ?? {classList}),
    trackPanelTitle: {}, trackPanel: {classList}, albumGrid: {classList}, trackList: {},
    panelMusic: {scrollTop: 100}, albumGridScrollTop: 0, selectSidebarAlbum() {},
    window: {MusicLibrary: {albumSongs: () => tracks, rowList: (_, rows) => assert.equal(rows, tracks)}},
    _closeSidebar() {},
  });
  openAlbum('new', {skipHistory: true});
  assert.deepEqual(releaseTime, {dateTime: '2026-09-11', textContent: '2026-09-11'});
  assert.equal(release.hidden, false);
  assert.deepEqual(description, {textContent: '舞厅更新配乐。', hidden: false});
  openAlbum('old', {skipHistory: true});
  assert.equal(release.hidden, true);
  assert.deepEqual(description, {textContent: '', hidden: true});
});

test('activating scores renders the available index without loading PDF code or changing playback', () => {
  const source = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
  const start = source.indexOf('  function setTab(name) {'), end = source.indexOf('  /* ── 数据加载', start);
  const state = {tab: 'music'}, panels = {classList: {toggle() {}}}; let renders = 0;
  const context = {state, _closeSidebar() {}, updateSidebarSections() {}, $$: () => [],
    panelMusic: panels, panelScores: panels, renderScores() {renders++;}};
  vm.runInNewContext(source.slice(start, end) + '\nsetTab("music");', context);
  assert.equal(renders, 0);
  vm.runInNewContext('setTab("scores");', context);
  assert.equal(renders, 1); assert.equal(state.tab, 'scores');
});

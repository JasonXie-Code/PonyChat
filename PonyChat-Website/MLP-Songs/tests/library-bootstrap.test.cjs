const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const shell = fs.readFileSync(require.resolve('../web/index.html'), 'utf8');
const bootstrap = shell.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
function harness(fetch) {
  const context = {window: {}, fetch, performance: {now: () => 125.5},
    document: {documentElement: {dataset: {}}}};
  vm.runInNewContext(bootstrap, context);
  return context;
}

test('head starts exactly one base catalog request before render-blocking local assets', async () => {
  let calls = 0, release;
  const pending = new Promise(resolve => {release = resolve;});
  const context = harness((url, options) => {
    calls++; assert.equal(url, '/api/library'); assert.equal(options.credentials, 'same-origin'); return pending;
  });
  assert.equal(calls, 1);
  const first = context.window.MusicLibraryBootstrap.load(), second = context.window.MusicLibraryBootstrap.load();
  assert.strictEqual(first, second); assert.equal(calls, 1);
  release({ok: true, json: async () => ({songs: [{id: 'recording'}]})});
  assert.equal((await first).songs[0].id, 'recording');
  assert.equal(context.document.documentElement.dataset.libraryRequestStartMs, '125.50');
  assert.equal(context.document.documentElement.dataset.libraryRequestMs, '0.00');
  const app = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
  const start = app.indexOf('  async function api(path) {'), end = app.indexOf('  function albumTitle', start);
  assert.equal((await vm.runInNewContext(app.slice(start, end) + '\napi("/api/library");', context)).songs[0].id, 'recording');
  assert.equal(calls, 1);
  assert(shell.indexOf('window.MusicLibraryBootstrap') < shell.indexOf('href="/style.css"'));
  assert(app.includes('dataset.appLoadStartMs = performance.now().toFixed(2)'));
});

test('failed early fetch is consumed safely and the later app can retry once', async () => {
  for (const failure of ['network', 'http']) {
    let calls = 0;
    const context = harness(async () => {
      if (++calls === 1) {
        if (failure === 'network') throw Error('offline');
        return {ok: false, status: 503};
      }
      return {ok: true, json: async () => ({songs: []})};
    });
    await new Promise(resolve => setImmediate(resolve));
    const request = context.window.MusicLibraryBootstrap.load();
    assert.strictEqual(request, context.window.MusicLibraryBootstrap.load());
    assert.equal((await request).songs.length, 0); assert.equal(calls, 2);
  }
});

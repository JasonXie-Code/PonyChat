const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const cacheAvailable of [true, false]) {
  test(`retired worker releases control with cache storage available=${cacheAvailable}`, async () => {
    const events = {}, calls = [];
    const self = {
      addEventListener(name, handler) {events[name] = handler;},
      async skipWaiting() {calls.push('skipWaiting');},
      clients: {async claim() {calls.push('claim');}},
      registration: {async unregister() {calls.push('unregister');}},
    };
    const caches = {async delete(name) {
      calls.push(name);
      if (!cacheAvailable) throw new Error('Storage unavailable');
    }};
    vm.runInNewContext(fs.readFileSync(require.resolve('../web/audio-preload-worker.js'), 'utf8'), {self, caches});
    assert.equal(events.fetch, undefined);
    assert.equal(events.message, undefined);
    const run = name => new Promise(resolve => events[name]({waitUntil: resolve}));
    await run('install');
    await run('activate');
    assert.deepEqual(calls, ['skipWaiting', 'claim', 'music-audio-preload-v1', 'unregister']);
  });
}

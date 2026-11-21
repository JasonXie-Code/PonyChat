const test = require('node:test');
const assert = require('node:assert/strict');
const Transition = require('../web/audio-transition.js');

function run(blocks) {
  const transition = new Transition(48000);
  const samples = [];
  for (const {value, open = 1, trailing = 0} of blocks) {
    const input = new Float32Array(128).fill(value, 0, 128 - trailing);
    const left = new Float32Array(128), right = new Float32Array(128);
    transition.process(input, input, left, right, open);
    assert.deepEqual(left, right);
    samples.push(...left);
  }
  return samples;
}

function assertNoStep(samples) {
  for (let i = 1; i < samples.length; i++) {
    assert(Math.abs(samples[i] - samples[i - 1]) <= 0.003, `discontinuity at sample ${i}`);
  }
}

test('the handoff fades the outgoing samples and excludes stale PCM behind a closed gate', () => {
  const old = Array(12).fill({value: 0.8});
  const blocked = Array(3).fill({value: 1, open: 0});
  const next = Array(12).fill({value: -0.7});
  const samples = run([...old, ...blocked, ...next]);
  assertNoStep(samples);
  assert(samples.some(value => value > 0.79));
  assert(samples.at(-1) < -0.69);
  assert(samples.slice(old.length * 128 + 608, (old.length + blocked.length) * 128 + 608).every(value => value === 0));
});

test('a recording can end between render quanta without an abrupt final sample', () => {
  const samples = run([...Array(12).fill({value: 0.5}), {value: 0.5, trailing: 87},
    ...Array(7).fill({value: 0})]);
  assertNoStep(samples);
  assert(samples.includes(0.5));
  assert.equal(samples.at(-1), 0);
});

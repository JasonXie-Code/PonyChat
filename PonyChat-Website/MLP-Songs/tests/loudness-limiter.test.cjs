const assert = require("node:assert/strict");
const test = require("node:test");
const Limiter = require("../web/loudness-limiter.js");

test("lookahead limits transients across blocks and applies equal stereo attenuation", () => {
  const limiter = new Limiter(48000);
  const left = new Float32Array(128).fill(0.02);
  const right = new Float32Array(128).fill(0.01);
  const outLeft = new Float32Array(128);
  const outRight = new Float32Array(128);
  const run = (gain, ceiling) => limiter.process(left, right, outLeft, outRight, gain, ceiling);
  run(5, 0.8);
  assert.equal(Math.max(...outLeft), 0);
  left[0] = 1;
  right[0] = 0.5;
  run(5, 0.8);
  assert(Math.abs(outLeft[0] - 0.1) < 0.005);
  assert(outLeft[127] < outLeft[0]);
  left[0] = 0.02;
  right[0] = 0.01;
  run(5, 0.8);
  assert(Math.max(...outLeft.map(Math.abs)) <= 0.800001);
  assert(Math.abs(outLeft[0] - 2 * outRight[0]) < 1e-6);
  for (let i = 0; i < 100; i++) run(5, 0.8);
  assert(Math.abs(outLeft[0] - 0.1) < 0.003);
});

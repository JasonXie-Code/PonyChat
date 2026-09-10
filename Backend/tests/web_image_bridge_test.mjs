import assert from 'node:assert/strict';
import { apply } from '../chat_modules/harness_plugin/chat-tools.mjs';

let tool;
const admitted = [];
apply({ tools: { register(value) { tool = value; } }, attachments: {
  async saveImages(images) {
    admitted.push(...images);
    return [{ attachmentId: 'sha256:web-image', mediaType: 'image/jpeg' }];
  },
}}, { tools: [{ name: 'read_web_image', parameters: {} }], endpoint: 'http://localhost' });
globalThis.fetch = async () => ({ ok: true, async json() { return { value: { content: [
  { type: 'text', text: 'network image' }, { type: 'image', mimeType: 'image/jpeg', data: 'cGl4ZWxz' },
] }, budget: { remaining: 3 } }; } });
const result = await tool.execute({}, {});
assert.equal(admitted[0].data.toString(), 'pixels');
assert.equal(admitted[0].mediaType, 'image/jpeg');
assert.equal(result.content[1].attachment.attachmentId, 'sha256:web-image');
assert.ok(!JSON.stringify(result).includes('cGl4ZWxz'));
assert.deepEqual(tool.output.render({}, result), result.content);
globalThis.fetch = async () => ({ ok: true, async json() { return { value: { status: 'unavailable' } }; } });
assert.equal((await tool.execute({}, {})).status, 'unavailable');
console.log('Web image admission, byte-free output and unavailable rendering: passed');

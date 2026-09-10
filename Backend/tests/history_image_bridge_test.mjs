import assert from 'node:assert/strict';
import { apply } from '../chat_modules/harness_plugin/chat-tools.mjs';

let registered;
let received;
apply({ tools: { register(tool) { registered = tool; } }, attachments: {
  async saveImages(images) {
    received = images;
    return [{ attachmentId: 'sha256:synthetic', mediaType: 'image/png' }];
  },
}}, { tools: [{ name: 'read_history_image', parameters: {} }], endpoint: 'http://localhost' });
globalThis.fetch = async () => ({ ok: true, async json() { return { value: { content: [
  { type: 'text', text: 'historical image' }, { type: 'image', mimeType: 'image/png', data: 'cGl4ZWxz' },
] } }; } });
const result = await registered.execute({}, {});
assert.equal(received[0].data.toString(), 'pixels');
assert.equal(received[0].mediaType, 'image/png');
assert.equal(result.content[1].attachment.attachmentId, 'sha256:synthetic');
assert.ok(!JSON.stringify(result).includes('cGl4ZWxz'));
assert.deepEqual(registered.output.render({}, result), result.content);
console.log('Native attachment admission and byte-free tool result: passed');

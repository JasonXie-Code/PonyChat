import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { apply } from '../chat_modules/harness_plugin/chat-tools.mjs';

test('real HTTP bridge preserves values, budget guidance and non-retryable errors', async () => {
  const server = http.createServer((request, response) => {
    request.resume();
    const exhausted = request.url === '/exhausted';
    response.writeHead(exhausted ? 409 : 200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify(exhausted
      ? { code: 'tool_budget_exhausted', error: 'Tool call budget exhausted', retryable: false }
      : { value: { staged: true }, budget: { remaining: 0, limit: 20 } }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const tools = {};
    apply({ tools: { register(tool) { tools[tool.name] = tool; } } }, {
      endpoint: `http://127.0.0.1:${server.address().port}`,
      tools: [{ name: 'stage' }, { name: 'exhausted' }],
    });
    const result = await tools.stage.execute({}, {});
    assert.deepEqual(JSON.parse(result.split('\n')[0]), { staged: true });
    assert.match(result, /0 calls remaining/);
    assert.match(result, /Do not call more tools/);
    await assert.rejects(tools.exhausted.execute({}, {}), error => {
      assert.match(error.message, /not provider rate limiting/);
      assert.match(error.message, /Do not retry/);
      assert.doesNotMatch(error.message, /HTTP 429/);
      return true;
    });
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

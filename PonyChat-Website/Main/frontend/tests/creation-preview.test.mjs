import test from 'node:test'
import assert from 'node:assert/strict'
import { creationPreview, deleteCreationMessages } from '../src/views/admin/sections/creationConversationRows.js'

test('preview preserves text, role and incomplete state with selectable IDs and valid dates', () => {
  const data = { id: 'session', username: 'alice', character_name: '角色', version: 3,
    character_avatar: '/avatar.png', messages: [{ id: 'message', sequence: 4, timestamp: 1791043200000,
      role: 'assistant', content: '# 标题\n\n原文', incomplete: true }] }
  const preview = creationPreview(data)
  assert.equal(preview.mode, 'creation')
  assert.equal(preview.id, 'creation:session')
  assert.equal(preview.character_avatar, '/avatar.png')
  assert.equal(preview.messages[0].message_id, 'message')
  assert.equal(preview.messages[0].content, data.messages[0].content)
  assert.equal(preview.messages[0].incomplete, true)
  assert.equal(Date.parse(preview.messages[0].timestamp), data.messages[0].timestamp)
  assert.equal(preview.message_total, 1)
  assert.equal(data.messages[0].timestamp, 1791043200000)
})

test('batch deletion uses each returned version and stops on a conflict', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method })
    return new Response(JSON.stringify(calls.length === 1 ? { version: 6 } : { detail: '已更新' }),
      { status: calls.length === 1 ? 200 : 409 })
  }
  try {
    await assert.rejects(deleteCreationMessages({ creation_session_id: 'session', version: 5 },
      [{ message_id: 'a' }, { message_id: 'b' }, { message_id: 'c' }]), /已更新/)
    assert.equal(calls.length, 2)
    assert.equal(calls[0].method, 'DELETE')
    assert.match(calls[0].url, /a\?version=5$/)
    assert.match(calls[1].url, /b\?version=6$/)
  } finally { globalThis.fetch = originalFetch }
})

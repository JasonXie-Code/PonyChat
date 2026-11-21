import assert from 'node:assert/strict'
import test from 'node:test'
import { logPreview } from '../src/views/admin/sections/logPreview.js'

test('small values remain readable', () => {
  const value = { tool: 'search', arguments: { query: '中文' }, success: true }
  const result = logPreview(value)
  assert.deepEqual(JSON.parse(result.text), value)
  assert.equal(result.truncated, false)
})
test('huge strings and arrays have bounded previews', () => {
  const value = Array.from({ length: 20000 }, () => ({ text: 'a'.repeat(30000) }))
  const result = logPreview(value)
  assert.ok(result.text.length <= 12000)
  assert.equal(result.truncated, true)
  assert.equal(value.length, 20000)
  assert.equal(value[0].text.length, 30000)
})
test('traversal stops before later expensive fields', () => {
  const value = { text: 'a'.repeat(12000), nested: { text: 'b'.repeat(12000), more: 'c'.repeat(12000) } }
  Object.defineProperty(value, 'unvisited', { enumerable: true, get() { throw Error('must not traverse') } })
  assert.equal(logPreview(value).truncated, true)
})
test('depth, cycles and escaped output stay bounded', () => {
  const value = { text: '\n"'.repeat(12000) }
  value.self = value
  const result = logPreview(value)
  assert.equal(result.truncated, true)
  assert.ok(result.text.length <= 12000)
})

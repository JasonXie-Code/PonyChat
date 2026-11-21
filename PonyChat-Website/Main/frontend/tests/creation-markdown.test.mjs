import test from 'node:test'
import assert from 'node:assert/strict'
import { creationMarkdown } from '../src/views/admin/sections/creationMarkdown.js'

test('renders emphasis, headings, lists, code and tables', () => {
  const html = creationMarkdown('# 标题\n\n*动作* **加粗**\n\n- 列表\n\n```js\nconst a = 1\n```\n\n|甲|乙|\n|---|---|\n|1|2|')
  for (const tag of ['h1', 'em', 'strong', 'ul', 'pre', 'table']) assert.match(html, new RegExp(`<${tag}[ >]`))
})

test('escapes raw HTML and rejects active links', () => {
  const html = creationMarkdown('<img src=x onerror=alert(1)>\n\n[危险](javascript:alert%281%29) [安全](https://example.com)')
  assert.doesNotMatch(html, /<img|href="javascript:/)
  assert.match(html, /&lt;img/)
  assert.match(html, /href="https:\/\/example.com\//)
})

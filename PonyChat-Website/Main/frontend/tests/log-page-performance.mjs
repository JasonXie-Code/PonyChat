import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const events = Array.from({ length: 1200 }, (_, index) => ({
    type: 'assistant/message', elapsed_ms: index,
    data: { content: `synthetic-${index}:` + '大日志测试 abcdef\n'.repeat(600) },
  }))
  const data = { events, sdk_events: events, finish_reason: 'completed' }
  const row = { id: 1, requestId: 'synthetic-only', stage: 'AGENT_RUN_RESPONSE', status: 'success', timestamp: new Date().toISOString(), username: 'Synthetic' }
  const detail = { ...row, request: { messages: Array.from({ length: 100 }, (_, i) => ({ role: 'user', content: `${i}:` + 'x'.repeat(6000) })) }, response: data, raw: { data } }
  const body = JSON.stringify(detail)
  await page.route('**/api/admin/**', async route => {
    const url = new URL(route.request().url())
    let result = {}
    if (url.pathname.endsWith('/summary')) result = { days: [] }
    else if (url.pathname.endsWith('/llm-logs')) result = { items: [row], hasMore: false }
    else if (url.pathname.endsWith('/llm-logs/1')) return route.fulfill({ contentType: 'application/json', body })
    await route.fulfill({ json: result })
  })
  await page.addInitScript(() => {
    sessionStorage.setItem('adminUser', JSON.stringify({ username: 'Synthetic' }))
    window.longTasks = []
    new PerformanceObserver(list => window.longTasks.push(...list.getEntries().map(e => e.duration))).observe({ type: 'longtask', buffered: true })
  })
  const start = Date.now()
  await page.goto(process.env.LOG_TEST_URL || 'http://127.0.0.1:5174/tests/log-page-performance.html')
  await page.locator('.agent-log li').first().waitFor()
  assert.equal(await page.locator('.agent-log li').count(), 30)
  assert.equal(await page.locator('.agent-log pre').count(), 0)
  const initial = await page.evaluate(() => ({ domNodes: document.querySelectorAll('*').length, textChars: document.body.textContent.length, longTasks: window.longTasks }))
  await page.getByRole('button', { name: '下一页事件' }).click()
  assert.equal(await page.locator('.agent-log ol').getAttribute('start'), '31')
  await page.locator('.agent-log li summary').first().click()
  await page.locator('.agent-log li pre').first().waitFor()
  assert.ok((await page.locator('.agent-log li pre').first().textContent()).includes('synthetic-30'))
  await page.getByText('SDK 原始事件（1200 条）', { exact: true }).click()
  await page.getByText('原始 JSON', { exact: true }).click()
  await page.getByRole('button', { name: '下一页消息' }).click()
  assert.equal(await page.locator('.message-card').count(), 10)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'JSON', exact: true }).click()
  const download = await downloadPromise
  const exported = JSON.parse(await fs.readFile(await download.path(), 'utf8'))
  assert.equal(exported.data.events.length, 1200)
  assert.equal(exported.data.events[1199].data.content, events[1199].data.content)
  const final = await page.evaluate(() => ({ domNodes: document.querySelectorAll('*').length, textChars: document.body.textContent.length, maxLongTaskMs: Math.max(0, ...window.longTasks) }))
  assert.ok(final.textChars < 150000)
  assert.deepEqual(errors, [])
  const report = { passed: true, syntheticOnly: true, url: page.url(), payloadBytes: Buffer.byteLength(body), elapsedMs: Date.now() - start, initial, final, fullExportVerified: true }
  console.log(JSON.stringify(report, null, 2))
  if (process.env.LOG_TEST_REPORT) await fs.writeFile(process.env.LOG_TEST_REPORT, JSON.stringify(report, null, 2))
} finally { await browser.close() }

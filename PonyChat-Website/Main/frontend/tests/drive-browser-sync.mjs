// Opt-in live browser check; creates and removes only its own uniquely named TXT.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.DRIVE_TEST_URL || 'https://drive.ponychat.org/'
const origin = new URL(base).origin
const apiOrigin = process.env.DRIVE_TEST_API_URL || origin
const output = process.env.DRIVE_TEST_OUTPUT || 'artifacts/drive-txt-sync'
const password = process.env.DRIVE_TEST_PASSWORD
assert.ok(password, 'Set DRIVE_TEST_PASSWORD for this opt-in check')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
let createdPath
let token
let api
const errors = []
try {
  api = await browser.newContext()
  const login = await api.request.post(`${apiOrigin}/api/drive/login`, { data: { password } })
  assert.equal(login.status(), 200)
  token = (await login.json()).token
  const contexts = await Promise.all([browser.newContext({ viewport: { width: 1440, height: 1000 } }),
    browser.newContext({ viewport: { width: 1440, height: 1000 } })])
  let usaApiRequests = 0
  let cnApiRequests = 0
  for (const [index, context] of contexts.entries()) {
    if (index !== 0 || process.env.DRIVE_TEST_LOGIN_UI !== '1') {
      await context.addInitScript((value) => localStorage.setItem('ponychat-drive-token', value), token)
    }
    if (process.env.DRIVE_TEST_BLOCK_USA_API === '1') {
      await context.route(`${origin}/api/drive/**`, (route) => { usaApiRequests += 1; return route.abort() })
    }
    if (process.env.DRIVE_TEST_BLOCK_CN_API === '1') {
      await context.route('https://39.101.74.217/api/drive/**', (route) => { cnApiRequests += 1; return route.abort() })
    }
    context.on('request', (request) => {
      if (request.url().startsWith('https://39.101.74.217/api/drive/')) cnApiRequests += 1
      if (request.url().startsWith(`${origin}/api/drive/`)) usaApiRequests += 1
    })
    if (process.env.DRIVE_TEST_DIST) {
      const dist = process.env.DRIVE_TEST_DIST
      await context.route(`${origin}/`, (route) => route.fulfill({ path: path.join(dist, 'index.html'), contentType: 'text/html' }))
      await context.route(`${origin}/assets/**`, (route) => {
        const relative = new URL(route.request().url()).pathname.slice(1)
        assert.ok(!relative.includes('..'))
        return route.fulfill({ path: path.join(dist, relative) })
      })
    }
  }
  let failList = process.env.DRIVE_TEST_LIST_RECOVERY === '1'
  if (failList) await contexts[1].route(`${apiOrigin}/api/drive/list?**`, (route) => failList
    ? route.fulfill({ status: 503, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': origin }, body: '{"detail":"模拟文件接口暂时不可用"}' })
    : route.continue())
  const [a, b] = await Promise.all(contexts.map((context) => context.newPage()))
  for (const page of [a, b]) page.on('pageerror', (error) => errors.push(error.message))
  await Promise.all([a.goto(base), b.goto(base)])
  let loginMs = null
  if (process.env.DRIVE_TEST_LOGIN_UI === '1') {
    await a.locator('input[type="password"]').fill(password)
    const loginStart = Date.now()
    await a.getByRole('button', { name: '进入 Drive', exact: true }).click()
    await a.getByRole('button', { name: '新建 TXT', exact: true }).waitFor()
    loginMs = Date.now() - loginStart
  }
  let recoveredList = false
  if (failList) {
    await b.getByRole('alert').filter({ hasText: '模拟文件接口暂时不可用' }).waitFor()
    assert.equal(await b.getByText('这个文件夹是空的', { exact: true }).count(), 0)
    failList = false
    await b.getByRole('alert').waitFor({ state: 'hidden', timeout: 15000 })
    recoveredList = true
  }
  const name = `__codex_txt_sync_${Date.now()}`
  createdPath = `/${name}.txt`
  await a.getByRole('button', { name: '新建 TXT', exact: true }).click()
  await a.getByRole('textbox', { name: '名称', exact: true }).fill(name)
  await a.getByRole('button', { name: '确定', exact: true }).click()
  const editorA = a.getByRole('textbox', { name: '文本编辑器', exact: true })
  await editorA.waitFor()
  assert.equal(await editorA.inputValue(), '')
  await b.getByRole('button', { name: '刷新', exact: true }).click()
  await b.getByRole('row').filter({ hasText: `${name}.txt` }).click()
  const editorB = b.getByRole('textbox', { name: '文本编辑器', exact: true })
  await editorB.waitFor()
  const waitForText = (page, value) => page.waitForFunction((text) =>
    document.querySelector('[aria-label="文本编辑器"]')?.value === text, value, { timeout: 15000 })
  const first = 'A 端输入：共享剪贴板\n中文、换行和 emoji 🐴'
  let start = Date.now()
  await editorA.fill(first)
  await waitForText(b, first)
  const forwardMs = Date.now() - start
  const second = 'B 端输入：共享剪贴板\n中文、换行和 emoji 🐴'
  start = Date.now()
  await editorB.fill(second)
  await waitForText(a, second)
  const reverseMs = Date.now() - start
  assert.equal(await editorA.inputValue(), second)
  // The receiver remains in the same selection and is not refreshed/reopened.
  await a.screenshot({ path: path.join(output, 'editor-a.png'), fullPage: true })
  await b.screenshot({ path: path.join(output, 'editor-b.png'), fullPage: true })
  assert.deepEqual(errors, [])
  if (process.env.DRIVE_TEST_BLOCK_USA_API === '1') assert.equal(usaApiRequests, 0)
  if (process.env.DRIVE_TEST_BLOCK_CN_API === '1') assert.equal(cnApiRequests, 0)
  const report = { base, newTxt: true, autoOpened: true, forwardMs, reverseMs, loginMs,
    usaApiRequests, cnApiRequests, recoveredList, pageErrors: errors }
  await writeFile(path.join(output, 'browser-result.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
} finally {
  if (createdPath && token) {
    const headers = { Authorization: `Bearer ${token}` }
    const removed = await api.request.post(`${apiOrigin}/api/drive/delete`, { headers, data: { paths: [createdPath] } })
    if (removed.ok()) {
      const ids = (await removed.json()).items.map((item) => item.trashId)
      if (ids.length) {
        const purged = await api.request.post(`${apiOrigin}/api/drive/permanent-delete`, { headers, data: { ids } })
        assert.equal(purged.status(), 200)
      }
    }
  }
  await browser.close()
}

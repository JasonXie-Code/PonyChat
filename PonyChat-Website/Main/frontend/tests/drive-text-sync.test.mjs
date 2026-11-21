import test from 'node:test'
import assert from 'node:assert/strict'
import { useDriveTextSync, TEXT_SAVE_DELAY_MS } from '../src/views/driveTextSync.js'
import { createDriveRequest } from '../src/views/driveRequest.js'

const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}
const input = (sync, value, isComposing = false) => sync.handleTextEditorInput({ target: { value }, isComposing })
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve() }

test('typing is saved after 350 ms without requiring blur', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const writes = []
  const sync = useDriveTextSync({ request: async (_, { body }) => { writes.push(body); return {} } })
  sync.openText('/共享.txt', '')
  input(sync, '剪贴板内容')
  t.mock.timers.tick(TEXT_SAVE_DELAY_MS - 1)
  assert.equal(writes.length, 0)
  t.mock.timers.tick(1)
  await flush()
  assert.deepEqual(writes, [{ path: '/共享.txt', content: '剪贴板内容' }])
  assert.equal(sync.textDirty.value, false)
  sync.resetTextEditorState()
})

test('continuous typing reaches the maximum wait, Chinese composition waits until finished', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let time = 0
  const writes = []
  const sync = useDriveTextSync({ now: () => time, request: async (_, { body }) => { writes.push(body.content); return {} } })
  sync.openText('/a.txt', '')
  for (let i = 0; i < 5; i += 1) {
    input(sync, `typing ${i}`)
    time += 300
    t.mock.timers.tick(300)
    await flush()
  }
  assert.ok(writes.length >= 1)
  sync.resetTextEditorState()
  sync.openText('/a.txt', '')
  input(sync, '拼', true)
  t.mock.timers.tick(2000)
  await sync.saveTextPreviewIfNeeded()
  assert.equal(sync.textDirty.value, true)
  const count = writes.length
  sync.finishTextComposition()
  t.mock.timers.tick(350)
  await flush()
  assert.equal(writes.length, count + 1)
  sync.resetTextEditorState()
})

test('two editors synchronize same-size text both ways without reselecting the file', async () => {
  let remote = 'aaaa'
  const request = async (url, options) => {
    if (url === '/text') { remote = options.body.content; return {} }
    assert.equal(options.cache, 'no-store')
    return new Blob([remote])
  }
  const a = useDriveTextSync({ request })
  const b = useDriveTextSync({ request })
  a.openText('/a.txt', remote)
  b.openText('/a.txt', remote)
  input(a, 'bbbb')
  await a.saveTextPreviewIfNeeded()
  await b.refreshTextPreview()
  assert.equal(b.textPreview.value, 'bbbb')
  input(b, 'cccc')
  await b.saveTextPreviewIfNeeded()
  await a.refreshTextPreview()
  assert.equal(a.textPreview.value, 'cccc')
  a.resetTextEditorState(); b.resetTextEditorState()
})

test('an in-flight download cannot overwrite typing that has since been saved', async () => {
  const read = deferred()
  const sync = useDriveTextSync({ request: async (url) => url === '/text' ? {} : read.promise })
  sync.openText('/a.txt', 'old')
  const pending = sync.refreshTextPreview()
  input(sync, 'new')
  await sync.saveTextPreviewIfNeeded()
  read.resolve(new Blob(['old']))
  await pending
  assert.equal(sync.textPreview.value, 'new')
  assert.equal(sync.textDirty.value, false)
  sync.resetTextEditorState()
})

test('edits during a slow save are queued and save completions cannot affect a different file', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const first = deferred()
  const writes = []
  const sync = useDriveTextSync({ request: async (_, { body }) => {
    writes.push(body.content)
    return writes.length === 1 ? first.promise : {}
  } })
  sync.openText('/a.txt', '')
  input(sync, 'first')
  const pending = sync.saveTextPreviewIfNeeded()
  input(sync, 'second')
  first.resolve({})
  await pending
  t.mock.timers.tick(350)
  await flush()
  assert.deepEqual(writes, ['first', 'second'])
  assert.equal(sync.textDirty.value, false)
  sync.resetTextEditorState()

  const late = deferred()
  const other = useDriveTextSync({ request: () => late.promise })
  other.openText('/a.txt', '')
  input(other, 'pending')
  const oldSave = other.saveTextPreviewIfNeeded()
  other.openText('/b.txt', 'keep me')
  late.resolve({})
  await oldSave
  assert.equal(other.textPreview.value, 'keep me')
  assert.equal(other.textSavedAt.value, '')
  other.resetTextEditorState()
})

test('failed saves retain drafts and retry; dirty text is never replaced by a poll', async () => {
  let offline = true
  const sync = useDriveTextSync({ request: async () => {
    if (offline) throw new Error('offline')
    return {}
  } })
  sync.openText('/a.txt', '')
  input(sync, 'draft')
  assert.equal(await sync.saveTextPreviewIfNeeded(), false)
  assert.equal(sync.textDirty.value, true)
  await sync.refreshTextPreview()
  assert.equal(sync.textPreview.value, 'draft')
  offline = false
  assert.equal(await sync.saveTextPreviewIfNeeded(), true)
  assert.equal(sync.textSaveError.value, '')
  sync.resetTextEditorState()
})

test('a stalled login times out instead of waiting indefinitely', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  t.mock.method(globalThis, 'fetch', (_, options) => new Promise((_, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  }))
  const request = createDriveRequest(() => '', () => {})
  const pending = assert.rejects(request('/login', { method: 'POST', body: { password: 'test' } }), /请求超时/)
  t.mock.timers.tick(15000)
  await pending
})

test('completed requests clear their timeout and authenticated errors expire the session', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let signal
  let unauthorized = 0
  t.mock.method(globalThis, 'fetch', async (_, options) => {
    signal = options.signal
    assert.equal(options.headers.get('Authorization'), 'Bearer test-token')
    return new Response('{"status":"success"}')
  })
  const request = createDriveRequest(() => 'test-token', () => { unauthorized += 1 })
  assert.deepEqual(await request('/list'), { status: 'success' })
  t.mock.timers.tick(15000)
  assert.equal(signal.aborted, false)
  globalThis.fetch.mock.mockImplementation(async () => new Response('{}', { status: 401 }))
  await assert.rejects(request('/list'), /登录已过期/)
  assert.equal(unauthorized, 1)
})

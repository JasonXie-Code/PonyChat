import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { useDriveDataLoader } from '../src/views/driveDataLoader.js'
import { driveApiUrl } from '../src/views/driveRequest.js'

function setup(overrides = {}) {
  const messages = []
  const loading = ref(false)
  const loader = useDriveDataLoader({ isAuthed: () => true, loading,
    loadTree: async () => {}, loadFiles: async () => {},
    setStatus: (message) => messages.push(message), ...overrides })
  return { ...loader, loading, messages }
}

test('Drive uses its same-origin standalone API for login, downloads and uploads', () => {
  assert.equal(driveApiUrl('/login'), '/api/drive/login')
  assert.equal(driveApiUrl('/download?path=%2Fa.txt'), '/api/drive/download?path=%2Fa.txt')
  assert.equal(driveApiUrl('/upload'), '/api/drive/upload')
})

test('file list errors have an explicit error state and later retries clear it', async () => {
  let failing = true
  const loader = setup({ loadFiles: async () => { if (failing) throw new Error('timeout') } })
  assert.equal(await loader.loadDrive(), false)
  assert.equal(loader.dataLoaded.value, false)
  assert.equal(loader.loadError.value, 'timeout')
  assert.equal(loader.loading.value, false)
  assert.match(loader.messages.at(-1), /自动重试/)
  failing = false
  assert.equal(await loader.loadDrive({ silent: true }), true)
  assert.equal(loader.dataLoaded.value, true)
  assert.equal(loader.loadError.value, '')
})

test('tree failure does not block a successful list, and refreshes do not pile up', async () => {
  let release
  let calls = 0
  const wait = new Promise((resolve) => { release = resolve })
  const loader = setup({ loadTree: async () => { throw new Error('tree unavailable') },
    loadFiles: async () => { calls += 1; await wait } })
  const first = loader.loadDrive()
  const second = loader.loadDrive()
  assert.equal(first, second)
  release()
  assert.equal(await first, true)
  assert.equal(calls, 1)
  assert.equal(loader.dataLoaded.value, true)
  assert.match(loader.messages.at(-1), /目录树暂不可用/)
})

test('logout invalidates an old load and successful silent refresh preserves save status', async () => {
  let release
  const loader = setup({ loadFiles: () => new Promise((resolve) => { release = resolve }) })
  const pending = loader.loadDrive()
  await Promise.resolve()
  loader.resetLoadState()
  assert.equal(loader.loading.value, false)
  release()
  await pending
  assert.equal(loader.dataLoaded.value, false)
  const healthy = setup()
  await healthy.loadDrive()
  const before = healthy.messages.length
  await healthy.loadDrive({ silent: true })
  assert.equal(healthy.messages.length, before)
})

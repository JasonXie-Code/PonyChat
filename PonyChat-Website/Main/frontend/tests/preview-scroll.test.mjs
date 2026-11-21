import test from 'node:test'
import assert from 'node:assert/strict'
import { capturePreviewPosition, restorePreviewPosition } from '../src/views/admin/sections/previewScroll.js'

function viewport() {
  const wrap = { scrollTop: 100, clientHeight: 200, rows: [['a', 80], ['b', 200]],
    getBoundingClientRect: () => ({ top: 0 }),
    querySelectorAll() {
      return this.rows.map(([key, y]) => ({ dataset: { messageKey: key },
        getBoundingClientRect: () => ({ top: y - this.scrollTop, bottom: y + 100 - this.scrollTop }) }))
    } }
  return wrap
}
const setTop = (wrap, top) => { wrap.scrollTop = top }

test('appending messages does not drag the reader down', () => {
  const wrap = viewport()
  const position = capturePreviewPosition(wrap)
  wrap.rows.push(['c', 400])
  restorePreviewPosition(wrap, position, setTop)
  assert.equal(wrap.scrollTop, 100)
})

test('prepending and trimming preserve the visible message offset', () => {
  for (const shift of [300, -80]) {
    const wrap = viewport()
    const position = capturePreviewPosition(wrap)
    wrap.rows = wrap.rows.map(([key, y]) => [key, y + shift])
    restorePreviewPosition(wrap, position, setTop)
    assert.equal(wrap.scrollTop, 100 + shift)
  }
})

test('uses the reader position after scrolling during a network wait', () => {
  const wrap = viewport()
  wrap.scrollTop = 180
  const position = capturePreviewPosition(wrap)
  wrap.rows.push(['c', 400])
  restorePreviewPosition(wrap, position, setTop)
  assert.equal(wrap.scrollTop, 180)
})

test('browser scroll anchoring is not applied twice', () => {
  const wrap = viewport()
  const position = capturePreviewPosition(wrap)
  wrap.rows = wrap.rows.map(([key, y]) => [key, y + 300])
  wrap.scrollTop += 300
  restorePreviewPosition(wrap, position, () => assert.fail('already anchored'))
})

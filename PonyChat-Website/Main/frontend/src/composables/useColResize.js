import { reactive, onBeforeUnmount } from 'vue'

/**
 * 管理后台列宽拖拽调整。
 *
 * - 带 columnOrder 的表格默认为 push 模式：仅改变被拖拽列的宽度，
 *   左侧列保持不动，右侧列整体平移。
 * - 网格列表通过 cssVarByKey 调整单条 CSS grid 轨道。
 *
 * 传入 resizeMode: 'pair' 可恢复旧行为：与紧邻右侧列互换宽度。
 * （与右侧相邻列成对伸缩。）
 */
export function useColResize(initialWidths, opts = {}) {
  const min = opts.min ?? 48
  const minByKey = opts.minByKey ?? {}
  const columnOrder = opts.columnOrder ?? null
  const cssVarByKey = opts.cssVarByKey ?? null
  const resizeMode = opts.resizeMode ?? 'push'

  const widths = reactive({ ...initialWidths })
  const dragLive = reactive({})
  let drag = null
  let rafId = null

  const _minFor = (k) => minByKey[k] ?? min

  function scheduleFlush() {
    if (rafId != null) return
    rafId = requestAnimationFrame(() => {
      rafId = null
      if (!drag || drag._pending == null) return
      if (drag.mode === 'pair') {
        dragLive[drag.leftKey] = drag._pending[drag.leftKey]
        dragLive[drag.rightKey] = drag._pending[drag.rightKey]
      } else if (drag.mode === 'push') {
        for (const k of drag.keys) dragLive[k] = drag._pending[k]
        if (drag.table) drag.table.style.width = `${drag._pendingTableWidth}px`
      } else {
        dragLive[drag.key] = drag._pending
      }
    })
  }

  /**
   * @param {string} key 列键
   * @param {MouseEvent} e 鼠标事件
   * @param {HTMLElement | undefined} el 可选布局宿主元素
   */
  function startResize(key, e, el) {
    e.preventDefault()
    e.stopPropagation()
    const handleEl = e.currentTarget

    if (cssVarByKey && Object.prototype.hasOwnProperty.call(cssVarByKey, key)) {
      const cssVar = cssVarByKey[key]
      const styleHost =
        el?.closest?.('.char-list-viewport') ?? handleEl?.closest?.('.char-list-viewport') ?? null
      if (!styleHost) return

      const measureEl = el ?? handleEl.parentElement
      const w0 = widths[key] ?? measureEl?.offsetWidth ?? 120

      dragLive[key] = w0
      drag = { mode: 'single', key, x0: e.clientX, w0, cssVar, styleHost, _pending: w0 }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
      return
    }

    if (columnOrder != null) {
      const leftTh = handleEl.closest('th')
      const tr = leftTh?.closest('tr')
      if (!leftTh || !tr) return
      const allThs = [...tr.querySelectorAll('th')]
      const leftIdx = allThs.indexOf(leftTh)
      const leftKey = columnOrder[leftIdx]
      if (leftKey == null || leftKey !== key) return

      if (resizeMode !== 'pair') {
        const keys = []
        const baseWidths = {}
        allThs.forEach((th, idx) => {
          const k = columnOrder[idx]
          if (k == null) return
          keys.push(k)
          baseWidths[k] = th.offsetWidth || widths[k] || 120
          dragLive[k] = baseWidths[k]
        })

        const table = leftTh.closest('table')
        const tableWidth = keys.reduce((sum, k) => sum + baseWidths[k], 0)
        if (table) table.style.width = `${tableWidth}px`

        drag = {
          mode: 'push',
          key,
          keys,
          x0: e.clientX,
          w0: baseWidths[key] ?? leftTh.offsetWidth ?? 120,
          minW: _minFor(key),
          baseWidths,
          table,
          _pending: { ...baseWidths },
          _pendingTableWidth: tableWidth,
        }
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
        return
      }

      const rightTh = allThs[leftIdx + 1]
      if (!rightTh) return

      const rightKey = columnOrder[leftIdx + 1]
      if (rightKey == null) return

      let w0L = widths[leftKey]
      let w0R = widths[rightKey]
      if (w0L == null) w0L = leftTh.offsetWidth
      if (w0R == null) w0R = rightTh.offsetWidth
      const sum = w0L + w0R
      const minL = _minFor(leftKey)
      const minR = _minFor(rightKey)
      if (sum < minL + minR) return

      dragLive[leftKey] = w0L
      dragLive[rightKey] = w0R
      drag = {
        mode: 'pair',
        leftKey,
        rightKey,
        x0: e.clientX,
        w0Left: w0L,
        w0Right: w0R,
        sum,
        minL,
        minR,
        _pending: { [leftKey]: w0L, [rightKey]: w0R },
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
      return
    }

    const th = el?.closest?.('th') ?? handleEl?.closest?.('th') ?? null
    const measureEl = el ?? th ?? handleEl.parentElement
    const w0 = widths[key] ?? measureEl?.offsetWidth ?? 120
    dragLive[key] = w0
    drag = { mode: 'single', key, x0: e.clientX, w0, cssVar: null, styleHost: null, _pending: w0 }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  function onMove(e) {
    if (!drag) return
    if (drag.mode === 'pair') {
      const delta = e.clientX - drag.x0
      const rawLeft = drag.w0Left + delta
      const newLeft = Math.max(drag.minL, Math.min(drag.sum - drag.minR, rawLeft))
      const newRight = drag.sum - newLeft
      drag._pending = { [drag.leftKey]: newLeft, [drag.rightKey]: newRight }
      scheduleFlush()
      return
    }
    if (drag.mode === 'push') {
      const nw = Math.max(drag.minW, drag.w0 + (e.clientX - drag.x0))
      drag._pending = { ...drag.baseWidths, [drag.key]: nw }
      drag._pendingTableWidth = drag.keys.reduce((sum, k) => sum + drag._pending[k], 0)
      scheduleFlush()
      return
    }
    const nw = Math.max(min, Math.min(drag.maxW ?? Infinity, drag.w0 + (e.clientX - drag.x0)))
    drag._pending = nw
    scheduleFlush()
  }

  function onUp() {
    if (rafId != null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
    if (!drag) return

    if (drag.mode === 'pair') {
      const pl = drag._pending?.[drag.leftKey]
      const pr = drag._pending?.[drag.rightKey]
      if (pl != null) widths[drag.leftKey] = pl
      if (pr != null) widths[drag.rightKey] = pr
      delete dragLive[drag.leftKey]
      delete dragLive[drag.rightKey]
    } else if (drag.mode === 'push') {
      for (const k of drag.keys) {
        const w = drag._pending?.[k]
        if (w != null) widths[k] = w
        delete dragLive[k]
      }
      if (drag.table) drag.table.style.width = `${drag._pendingTableWidth}px`
    } else {
      const nw = Math.max(min, drag._pending ?? dragLive[drag.key] ?? min)
      widths[drag.key] = nw
      delete dragLive[drag.key]
    }

    drag = null
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }

  onBeforeUnmount(onUp)

  function thStyle(key) {
    const live = dragLive[key]
    if (live != null) return { width: `${live}px` }
    const w = widths[key]
    return w != null ? { width: `${w}px` } : {}
  }

  function gridVars(varMap) {
    const s = {}
    for (const [cssVar, k] of Object.entries(varMap)) {
      const w = dragLive[k] ?? widths[k]
      if (w != null) s[cssVar] = `${w}px`
    }
    return s
  }

  return { widths, startResize, thStyle, gridVars }
}

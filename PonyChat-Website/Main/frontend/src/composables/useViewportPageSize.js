import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

/**
 * 根据容器可视高度估算每页行数（管理后台列表/表格分页）。
 * @param {import('vue').Ref<HTMLElement | null | undefined>} containerRef 包住表体区域或列表行的容器（需参与 flex 撑满高度）
 * @param {object} [options] 可选配置
 * @param {number} [options.rowHeight=48] 单行近似高度（px）
 * @param {number} [options.headHeight=44] 表头或列表头占用高度（px）
 * @param {number} [options.minRows=4] 最少行数
 * @param {number} [options.maxRows=200] 最多行数
 * @param {number} [options.slackPx=16] 从可用高度扣除的像素（表头边框、行分割线、亚像素误差等），略少算一行避免末行裁切
 */
export function useViewportPageSize(containerRef, options = {}) {
  const {
    rowHeight = 48,
    headHeight = 44,
    minRows = 4,
    maxRows = 200,
    slackPx = 16,
  } = options

  const pageSize = ref(Math.max(minRows, 8))

  function measure() {
    const el = containerRef?.value
    if (!el || typeof el.clientHeight !== 'number') return
    const h = el.clientHeight
    if (h < 28) return
    const avail = Math.max(0, h - headHeight - slackPx)
    const n = Math.floor(avail / rowHeight)
    const v = Math.min(maxRows, Math.max(minRows, n > 0 ? n : minRows))
    if (pageSize.value !== v) pageSize.value = v
  }

  let ro = null

  function bindResizeObserver(el) {
    if (!el || typeof ResizeObserver === 'undefined') return
    if (!ro) ro = new ResizeObserver(() => measure())
    ro.observe(el)
  }

  function unbindResizeObserver(el) {
    if (ro && el) {
      try {
        ro.unobserve(el)
      } catch {
        /* 忽略 */
      }
    }
  }

  onMounted(() => {
    nextTick(() => {
      measure()
      if (containerRef.value) bindResizeObserver(containerRef.value)
    })
  })

  watch(
    () => containerRef.value,
    (el, prev) => {
      unbindResizeObserver(prev)
      nextTick(() => {
        measure()
        if (el) bindResizeObserver(el)
      })
    },
  )

  function onWinResize() {
    measure()
  }
  window.addEventListener('resize', onWinResize)

  onUnmounted(() => {
    window.removeEventListener('resize', onWinResize)
    if (ro) {
      ro.disconnect()
      ro = null
    }
  })

  return { pageSize, measure }
}

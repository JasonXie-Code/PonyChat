import { computed, ref, unref, watch } from 'vue'

/**
 * 管理后台列表分页（终端页不使用）。
 * @param {import('vue').Ref<any[]>} itemsRef 待分页列表数据
 * @param {number | import('vue').Ref<number> | import('vue').ComputedRef<number>} pageSizeInput 固定数字或由 useViewportPageSize 提供的 ref
 */
export function useAdminPagination(itemsRef, pageSizeInput = 20) {
  const page = ref(1)

  const pageSize = computed(() => {
    const v = unref(pageSizeInput)
    const n = typeof v === 'number' ? v : parseInt(String(v), 10)
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 20
  })

  const total = computed(() => itemsRef.value?.length ?? 0)
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const pagedItems = computed(() => {
    const arr = itemsRef.value ?? []
    const sz = pageSize.value
    const start = (page.value - 1) * sz
    return arr.slice(start, start + sz)
  })

  watch([total, totalPages, pageSize], () => {
    if (page.value > totalPages.value) page.value = totalPages.value
    if (page.value < 1) page.value = 1
  })

  function next() {
    if (page.value < totalPages.value) page.value += 1
  }
  function prev() {
    if (page.value > 1) page.value -= 1
  }
  function resetPage() {
    page.value = 1
  }

  return {
    page,
    totalPages,
    total,
    pagedItems,
    pageSize,
    next,
    prev,
    resetPage,
  }
}

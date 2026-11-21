/**
 * 全局确认弹窗：AdminLayout 挂载 ConfirmDialog 后，调用 confirmAsync() 返回 Promise<boolean>
 */
import { reactive } from 'vue'

const state = reactive({
  open: false,
  title: '',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: false,
  _resolve: null,
})

export function useConfirmState() {
  return state
}

/**
 * @param {{ title?: string, message: string, confirmText?: string, cancelText?: string, danger?: boolean }} opts 弹窗选项
 * @returns {Promise<boolean>} 用户是否确认
 */
export function confirmAsync(opts) {
  return new Promise((resolve) => {
    if (state.open && state._resolve) {
      state._resolve(false)
    }
    state.title = opts.title || '确认'
    state.message = opts.message || ''
    state.confirmText = opts.confirmText || '确定'
    state.cancelText = opts.cancelText || '取消'
    state.danger = !!opts.danger
    state._resolve = resolve
    state.open = true
  })
}

export function resolveConfirm(ok) {
  state.open = false
  const fn = state._resolve
  state._resolve = null
  if (fn) fn(!!ok)
}

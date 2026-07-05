/**
 * 全局 Toast：在 AdminLayout 挂载 ToastContainer 后生效。
 */
import { reactive } from 'vue'

const state = reactive({
  items: [],
})

let _id = 0

function push(type, message, duration = 4000) {
  const id = ++_id
  state.items.push({ id, type, message })
  if (duration > 0) {
    setTimeout(() => remove(id), duration)
  }
  return id
}

function remove(id) {
  const i = state.items.findIndex((x) => x.id === id)
  if (i >= 0) state.items.splice(i, 1)
}

export function useToast() {
  return {
    items: state.items,
    success: (msg, d) => push('success', msg, d),
    error: (msg, d) => push('error', msg, d),
    info: (msg, d) => push('info', msg, d),
    remove,
  }
}

export const toast = {
  success: (msg, d) => push('success', msg, d),
  error: (msg, d) => push('error', msg, d),
  info: (msg, d) => push('info', msg, d),
}

import { ref } from 'vue'

/**
 * 点击遮罩关闭弹窗时，仅在「按下」也落在遮罩本体上时才关闭。
 * 避免从弹窗内拖动（如 textarea 调整高度）指针移到遮罩上松开后，误触发遮罩 click 而关闭。
 */
export function useModalBackdropDismiss(onClose) {
  const mouseDownOnBackdrop = ref(false)

  function onBackdropMouseDown(e) {
    mouseDownOnBackdrop.value = e.target === e.currentTarget
  }

  function onBackdropClickSelf() {
    if (!mouseDownOnBackdrop.value) return
    mouseDownOnBackdrop.value = false
    onClose()
  }

  return { onBackdropMouseDown, onBackdropClickSelf }
}

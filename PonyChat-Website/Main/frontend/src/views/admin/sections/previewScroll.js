// Capture immediately before updating the DOM, after any network wait.
export function capturePreviewPosition(wrap) {
  if (!wrap) return null
  const top = wrap.getBoundingClientRect().top
  const anchors = Array.from(wrap.querySelectorAll('[data-message-key]'))
    .map(el => ({ key: el.dataset.messageKey, offset: el.getBoundingClientRect().top - top,
      bottom: el.getBoundingClientRect().bottom - top }))
    .filter(anchor => anchor.bottom > 0 && anchor.offset < wrap.clientHeight)
  return { top: wrap.scrollTop, anchors }
}

export function restorePreviewPosition(wrap, position, setScrollTop) {
  if (!wrap || !position) return
  const elements = Array.from(wrap.querySelectorAll('[data-message-key]'))
  for (const anchor of position.anchors) {
    const el = elements.find(el => el.dataset.messageKey === anchor.key)
    if (!el) continue
    const offset = el.getBoundingClientRect().top - wrap.getBoundingClientRect().top
    const delta = offset - anchor.offset
    if (Math.abs(delta) > 0.5) setScrollTop(wrap, wrap.scrollTop + delta)
    return
  }
  if (Math.abs(wrap.scrollTop - position.top) > 0.5) setScrollTop(wrap, position.top)
}

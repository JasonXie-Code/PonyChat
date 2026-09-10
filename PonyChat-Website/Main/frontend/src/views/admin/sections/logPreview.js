// Bound traversal as well as output: slicing JSON.stringify still walks the entire log.
export function logPreview(value, { maxChars = 12000, maxNodes = 250, maxDepth = 8 } = {}) {
  let remaining = maxChars
  let nodes = 0
  let truncated = false
  const seen = new WeakSet()
  function visit(item, depth) {
    if (++nodes > maxNodes || remaining <= 0 || depth > maxDepth) {
      truncated = true
      return '…'
    }
    if (typeof item === 'string') {
      const limit = Math.min(remaining, 4000)
      remaining -= Math.min(item.length, limit)
      if (item.length > limit) { truncated = true; return item.slice(0, limit) + '…' }
      return item
    }
    if (item == null || typeof item !== 'object') { remaining -= 16; return item }
    if (seen.has(item)) { truncated = true; return '[重复引用]' }
    seen.add(item)
    const result = Array.isArray(item) ? [] : {}
    let count = 0
    for (const key in item) {
      if (!Object.hasOwn(item, key)) continue
      if (nodes >= maxNodes || remaining <= 0 || count >= 50) {
        truncated = true
        if (Array.isArray(result)) result.push('…')
        else result['…'] = '更多字段'
        break
      }
      remaining -= key.length + 8
      result[key] = visit(item[key], depth + 1)
      count++
    }
    return result
  }
  const preview = visit(value, 0)
  const text = typeof preview === 'string' ? preview : JSON.stringify(preview ?? null, null, 2)
  return { text: text.slice(0, maxChars), truncated: truncated || text.length > maxChars }
}

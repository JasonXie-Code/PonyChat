import { ref } from 'vue'

/**
 * 管理后台表格列排序状态（表头点击切换 asc/desc）。
 * @param {string} defaultKey 默认排序列
 * @param {'asc'|'desc'} defaultDir 默认方向
 * @param {(key: string) => ('asc'|'desc')|undefined} [initialDirForKey] 切换到新列时的初始方向；未返回则用 asc
 */
export function useAdminTableSort(defaultKey, defaultDir = 'asc', initialDirForKey) {
  const sortKey = ref(defaultKey)
  const sortDir = ref(defaultDir)

  function toggleSort(key) {
    if (sortKey.value === key) {
      sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey.value = key
      const d = initialDirForKey?.(key)
      sortDir.value = d === 'desc' || d === 'asc' ? d : 'asc'
    }
  }

  function sortIcon(key) {
    if (sortKey.value !== key) return '⇅'
    return sortDir.value === 'asc' ? '↑' : '↓'
  }

  return { sortKey, sortDir, toggleSort, sortIcon }
}

export const ADMIN_TIME_ZONE = 'Asia/Shanghai'

function partsForBeijing(date) {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: ADMIN_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const out = {}
  for (const p of parts) {
    if (p.type !== 'literal') out[p.type] = p.value
  }
  return out
}

export function adminTimeMs(val) {
  if (val == null || val === '') return '—'
  const n = Number(val)
  if (Number.isFinite(n) && n > 0) {
    const ms = n > 1e12 ? n : n * 1000
    return Number.isFinite(ms) ? ms : NaN
  }
  const s = String(val).trim()
  if (!s) return NaN
  const normalized = s.replace(' ', 'T')
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized)
  if (hasTimezone) return new Date(normalized).getTime()

  const match = normalized.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?$/,
  )
  if (match) {
    const [, yy, mo, dd, hh = '00', mi = '00', ss = '00', frac = '0'] = match
    const msPart = Number(String(frac).slice(0, 3).padEnd(3, '0')) || 0
    const y = Number(yy)
    const m = Number(mo) - 1
    const d = Number(dd)
    const h = Number(hh)
    const min = Number(mi)
    const sec = Number(ss)
    const sourceLooksLikePythonIso = s.includes('T')
    const utcMs = Date.UTC(y, m, d, h, min, sec, msPart)
    return sourceLooksLikePythonIso ? utcMs - 8 * 60 * 60 * 1000 : utcMs
  }

  return new Date(`${normalized}Z`).getTime()
}

/**
 * 统一格式化 ISO 串或 Unix 时间戳（ms/s）为北京时间 `YYYY-MM-DD HH:mm`。
 * 后端 SQLite `CURRENT_TIMESTAMP` 无时区字符串按 UTC 解释，再转北京时间。
 * @param {unknown} val 待格式化的日期/时间戳
 * @returns {string} 格式化后的字符串
 */
export function fmtDt(val) {
  const ms = adminTimeMs(val)
  if (!Number.isFinite(ms)) return '—'
  const p = partsForBeijing(new Date(ms))
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`
}

export function fmtDtSeconds(val) {
  const ms = adminTimeMs(val)
  if (!Number.isFinite(ms)) return ''
  const p = partsForBeijing(new Date(ms))
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`
}

export function fmtDateOnly(val) {
  const ms = adminTimeMs(val)
  if (!Number.isFinite(ms)) return ''
  const p = partsForBeijing(new Date(ms))
  return `${p.year}-${p.month}-${p.day}`
}

export function beijingDateValue(val) {
  const ms = adminTimeMs(val)
  if (!Number.isFinite(ms)) return ''
  const p = partsForBeijing(new Date(ms))
  return `${p.year}-${p.month}-${p.day}`
}

export function beijingDateStartMs(value) {
  const parts = String(value || '').split('-').map((x) => Number(x))
  if (parts.length !== 3 || parts.some((x) => !Number.isFinite(x))) return NaN
  return Date.UTC(parts[0], parts[1] - 1, parts[2], 0, 0, 0, 0) - 8 * 60 * 60 * 1000
}

export function beijingDateEndMs(value) {
  const parts = String(value || '').split('-').map((x) => Number(x))
  if (parts.length !== 3 || parts.some((x) => !Number.isFinite(x))) return NaN
  return Date.UTC(parts[0], parts[1] - 1, parts[2], 23, 59, 59, 999) - 8 * 60 * 60 * 1000
}

/** 中英文 locale 字符串比较，dir 为 1 表示 asc */
export function cmpLocale(a, b, dir) {
  const c = String(a ?? '').localeCompare(String(b ?? ''), 'zh-CN')
  if (c < 0) return -dir
  if (c > 0) return dir
  return 0
}

/** 数值比较，dir 为 1 表示 asc */
export function cmpNum(a, b, dir) {
  const x = Number(a)
  const y = Number(b)
  const na = Number.isFinite(x) ? x : 0
  const nb = Number.isFinite(y) ? y : 0
  if (na < nb) return -dir
  if (na > nb) return dir
  return 0
}

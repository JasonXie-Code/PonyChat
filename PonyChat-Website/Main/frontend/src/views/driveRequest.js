import { parseDriveError } from './driveViewModel.js'

// The public Drive host serves both the page and its independent Server-USA API.
export function driveApiUrl(endpoint) {
  return `/api/drive${endpoint}`
}

export function createDriveRequest(getToken, onUnauthorized) {
  return async function driveRequest(endpoint, options = {}) {
    const headers = new Headers(options.headers || {})
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    let body = options.body
    if (body && !(body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(body)
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs || (options.blob ? 120000 : 15000))
    try {
      const response = await fetch(driveApiUrl(endpoint), {
        method: options.method || 'GET', headers, body,
        signal: controller.signal, cache: options.cache,
      })
      if (response.status === 401 && endpoint !== '/login') {
        onUnauthorized()
        throw new Error('Drive 登录已过期')
      }
      if (!response.ok) throw new Error(parseDriveError(response.status, await response.text()))
      if (options.blob) return await response.blob()
      const text = await response.text()
      return text ? JSON.parse(text) : {}
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error('请求超时，请检查网络后重试')
      throw error
    } finally {
      clearTimeout(timeout)
    }
  }
}

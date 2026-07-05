/**
 * 管理后台 /api/admin/* 请求封装（与旧版 js/admin/*.js 行为对齐）。
 */

const BASE = '/api/admin'

function _stringFromApiValue(value) {
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    return value.map(_stringFromApiValue).filter(Boolean).join('；')
  }
  if (value && typeof value === 'object') {
    for (const key of ['detail', 'message', 'error', 'reason']) {
      const text = _stringFromApiValue(value[key])
      if (text) return text
    }
    if (typeof value.msg === 'string') return value.msg.trim()
  }
  return ''
}

function _apiErrorMessage(data, fallback = '') {
  return _stringFromApiValue(data) || fallback || '请求失败'
}

function _throwApiPayloadError(data, fallback = '') {
  if (!data || typeof data !== 'object') return data
  const status = String(data.status || '').toLowerCase()
  const success = data.success
  if (success === false || status === 'error' || status === 'failed') {
    const err = new Error(_apiErrorMessage(data, fallback))
    err.data = data
    throw err
  }
  return data
}

async function _json(res) {
  const text = await res.text()
  let data
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    const err = new Error(_apiErrorMessage(data, res.statusText || `HTTP ${res.status}`))
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export async function adminLogin(username, password) {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return _json(res)
}

export async function fetchStats() {
  const res = await fetch(`${BASE}/stats`)
  return _json(res)
}

export async function fetchSystemStatus() {
  const res = await fetch(`${BASE}/system-status?_=${Date.now()}`, { cache: 'no-store' })
  return _json(res)
}

export async function fetchUptimeHeatmap(days = 30, mode = 'month') {
  const res = await fetch(`${BASE}/uptime-heatmap?days=${encodeURIComponent(days)}&mode=${encodeURIComponent(mode)}&_=${Date.now()}`, {
    cache: 'no-store',
  })
  return _json(res)
}

export async function fetchUsers() {
  const res = await fetch(`${BASE}/users`)
  return _json(res)
}

export async function disableUser(username) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/disable`, { method: 'POST' })
  return _json(res)
}

export async function enableUser(username) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/enable`, { method: 'POST' })
  return _json(res)
}

export async function deleteUser(username) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}`, { method: 'DELETE' })
  return _json(res)
}

export async function editUser(payload) {
  const res = await fetch(`${BASE}/users/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function fetchUserMembership(username) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/membership`)
  return _json(res)
}

export async function updateUserMembership(username, body) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/membership`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return _json(res)
}

export async function resetMembershipUsage(username) {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/membership/reset-usage`, {
    method: 'POST',
  })
  return _json(res)
}

export async function resetAllMembershipUsage() {
  const res = await fetch(`${BASE}/users/reset-all-usage`, {
    method: 'POST',
  })
  return _json(res)
}

export async function fetchAdminCharacters(username) {
  const q = username ? `?username=${encodeURIComponent(username)}` : ''
  const res = await fetch(`${BASE}/characters${q}`)
  return _json(res)
}

export async function editCharacter(payload) {
  const res = await fetch(`${BASE}/characters/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

/** 管理后台：新建角色，归属用户名为 System */
export async function createCharacter(payload) {
  const res = await fetch(`${BASE}/characters/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function designCharacterVoice(payload) {
  const res = await fetch(`${BASE}/characters/voice/design`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
  return _throwApiPayloadError(await _json(res), '音色设计失败')
}

export async function uploadCharacterVoiceReferenceAudio({ file, transcript = '', characterId = '', voiceProfileId = '', voiceName = '' }) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('transcript', transcript)
  fd.append('character_id', characterId)
  fd.append('voice_profile_id', voiceProfileId)
  fd.append('voice_name', voiceName)
  const res = await fetch(`${BASE}/characters/voice/reference-audio`, {
    method: 'POST',
    body: fd,
  })
  try {
    return _throwApiPayloadError(await _json(res), '参考音频上传失败')
  } catch (err) {
    if (err?.status === 413) {
      const sizeMb = file?.size ? `当前文件约 ${(file.size / 1024 / 1024).toFixed(1)}MB，` : ''
      throw new Error(`${sizeMb}服务器拒绝了本次上传（HTTP 413）。参考音频上限为 25MB，请压缩后重试`)
    }
    throw err
  }
}

/** @param {File} file 头像文件 */
export async function uploadCharacterAvatar(characterId, file) {
  const fd = new FormData()
  fd.append('character_id', characterId)
  fd.append('file', file)
  const res = await fetch(`${BASE}/characters/upload-avatar`, {
    method: 'POST',
    body: fd,
  })
  return _json(res)
}

/** @param {File} file 角色主页封面 / 相册图片 */
export async function uploadCharacterProfileImage(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}/characters/upload-profile-image`, {
    method: 'POST',
    body: fd,
  })
  return _json(res)
}

export async function deleteCharacter(characterId, username) {
  const q = username ? `?username=${encodeURIComponent(username)}` : ''
  const res = await fetch(`${BASE}/characters/${encodeURIComponent(characterId)}${q}`, {
    method: 'DELETE',
  })
  return _json(res)
}

export async function deleteCharacterReference(sourceId, referenceId) {
  const res = await fetch(
    `${BASE}/characters/${encodeURIComponent(sourceId)}/references/${encodeURIComponent(referenceId)}`,
    { method: 'DELETE' },
  )
  return _json(res)
}

export async function fetchWebCharacterIds() {
  const res = await fetch(`${BASE}/web-characters`)
  return _json(res)
}

export async function saveWebCharacterIds(characterIds) {
  const res = await fetch(`${BASE}/web-characters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_ids: characterIds }),
  })
  return _json(res)
}

export async function fetchConversations() {
  const res = await fetch(`${BASE}/conversations`)
  return _json(res)
}

export async function fetchConversationRecovery(onlyHidden = false) {
  const res = await fetch(`${BASE}/conversation-recovery?only_hidden=${onlyHidden ? 'true' : 'false'}`)
  return _json(res)
}

export async function restoreConversation(conversationId) {
  const res = await fetch(`${BASE}/conversation-recovery/${encodeURIComponent(conversationId)}/restore`, {
    method: 'POST',
  })
  return _json(res)
}

export async function restoreConversationMessage(conversationId, messageId) {
  const res = await fetch(
    `${BASE}/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/restore`,
    { method: 'POST' },
  )
  return _json(res)
}

export async function softDeleteConversationMessage(conversationId, messageId) {
  const res = await fetch(
    `${BASE}/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/soft-delete`,
    { method: 'POST' },
  )
  return _json(res)
}

export async function fetchConversationDetail(conversationId, options = {}) {
  const params = new URLSearchParams()
  params.set('include_deleted', options.includeDeleted === false ? 'false' : 'true')
  if (Number.isFinite(options.limit)) params.set('limit', String(options.limit))
  if (Number.isFinite(options.offset)) params.set('offset', String(options.offset))
  if (options.fromLatest) params.set('from_latest', 'true')
  const qs = params.toString()
  const res = await fetch(
    `${BASE}/conversations/${encodeURIComponent(conversationId)}${qs ? `?${qs}` : ''}`,
  )
  return _json(res)
}

export async function resetConversation(conversationId) {
  const res = await fetch(`${BASE}/conversations/${encodeURIComponent(conversationId)}/reset`, {
    method: 'POST',
  })
  return _json(res)
}

export async function purgeSoftDeleted(body) {
  const res = await fetch(`${BASE}/retention/purge-soft-deleted`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  return _json(res)
}

export async function fetchDeletionAudits(params) {
  const q = new URLSearchParams(params || {})
  const res = await fetch(`${BASE}/deletion-audits?${q.toString()}`)
  return _json(res)
}

export async function fetchModelsConfig() {
  const res = await fetch(`${BASE}/models/config`)
  return _json(res)
}

export async function saveModelsConfig(payload) {
  const res = await fetch(`${BASE}/models/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function testModel(payload) {
  const res = await fetch(`${BASE}/models/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function changeAdminPassword(currentPassword, newPassword) {
  const res = await fetch(`${BASE}/change-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  return _json(res)
}

export async function backupDatabase() {
  const res = await fetch(`${BASE}/backup`, { method: 'POST' })
  return _json(res)
}

export async function listBackups() {
  const res = await fetch(`${BASE}/backups`)
  return _json(res)
}

export async function restoreDatabase(payload) {
  const res = await fetch(`${BASE}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function fetchInviteCodes(adminPassword) {
  const res = await fetch(
    `${'/api/admin/invite-codes'}?admin_password=${encodeURIComponent(adminPassword)}`,
  )
  return _json(res)
}

export async function generateInviteCodes(adminPassword, count, note) {
  const res = await fetch(
    `${'/api/admin/invite-codes/generate'}?admin_password=${encodeURIComponent(adminPassword)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count, note }),
    },
  )
  return _json(res)
}

export async function deleteInviteCode(adminPassword, code) {
  const res = await fetch(
    `${'/api/admin/invite-codes'}/${encodeURIComponent(code)}?admin_password=${encodeURIComponent(adminPassword)}`,
    { method: 'DELETE' },
  )
  return _json(res)
}

// ── 素材管理 ──────────────────────────────────────────────────────────────────

const ASSETS_BASE = `${BASE}/assets`

export async function fetchAssets(params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${ASSETS_BASE}${qs}`)
  return _json(res)
}

export async function fetchAssetCategories() {
  const res = await fetch(`${ASSETS_BASE}/categories`)
  return _json(res)
}

export async function suggestAssets(params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${ASSETS_BASE}/suggest${qs}`)
  return _json(res)
}

/** @param {FormData} formData 资源上传表单 */
export async function uploadAsset(formData) {
  const res = await fetch(`${ASSETS_BASE}/upload`, { method: 'POST', body: formData })
  return _json(res)
}

export async function updateAsset(id, payload) {
  const res = await fetch(`${ASSETS_BASE}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return _json(res)
}

export async function deleteAsset(id) {
  const res = await fetch(`${ASSETS_BASE}/${encodeURIComponent(id)}`, { method: 'DELETE' })
  return _json(res)
}

// ── 对话日志 (LLM Call Logs) ──────────────────────────────────────────────────

const LOGS_BASE = `${BASE}/llm-logs`

/** 获取按日期/小时维度的日志统计摘要 */
export async function fetchLlmLogSummary(params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${LOGS_BASE}/summary${qs}`)
  return _json(res)
}

/**
 * 查询日志列表（分页 / cursor）
 * @param {Object} params - 筛选 & 分页参数
 * @returns {Promise<{items: Array, nextCursor: string|null, hasMore: boolean}>}
 */
export async function fetchLlmLogs(params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${LOGS_BASE}${qs}`)
  return _json(res)
}

/** 获取单条日志完整详情（含 request / response / raw） */
export async function fetchLlmLogDetail(id) {
  const res = await fetch(`${LOGS_BASE}/${encodeURIComponent(id)}`)
  return _json(res)
}

/** 触发重建日志索引（仅超级管理员） */
export async function reindexLlmLogs() {
  const res = await fetch(`${LOGS_BASE}/reindex`, { method: 'POST' })
  return _json(res)
}

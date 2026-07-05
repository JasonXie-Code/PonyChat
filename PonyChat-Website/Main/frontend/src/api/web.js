/** 公开网页 API */

export async function fetchPublicWebCharacters() {
  const res = await fetch('/api/web-characters')
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function guestLogin(deviceId) {
  const res = await fetch('/api/auth/guest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

export async function exportLogin(username, password) {
  const res = await fetch('/api/export/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

export async function fetchExportOptions(token) {
  const res = await fetch('/api/export/options', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

export async function downloadExportText(token, { characterIds, modes }) {
  const res = await fetch('/api/export/download', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ character_ids: characterIds, modes }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="([^"]+)"/)
  return {
    blob,
    filename: match?.[1] || `ponychat-export-${new Date().toISOString().slice(0, 10)}.txt`,
  }
}

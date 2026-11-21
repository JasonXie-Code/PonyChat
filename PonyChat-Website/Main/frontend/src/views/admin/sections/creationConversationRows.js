import { creationAdmin } from '../../../api/admin.js'

// Creative sessions share the same searchable, sortable conversation table.
export async function fetchCreationConversationRows() {
  const rows = []
  let page = 1
  let total = 0
  do {
    const data = await creationAdmin(`?page=${page++}&limit=100`)
    total = data.total
    rows.push(...data.sessions.map((s) => ({
      id: `creation:${s.id}`, creation_session_id: s.id, mode: 'creation',
      title: s.title, user: s.username, character: s.character_name,
      character_id: s.character_id, character_avatar: s.character_avatar, messages: s.message_count,
      updated_at: new Date(s.updated_ms).toISOString(),
      created_at: s.created_ms ? new Date(s.created_ms).toISOString() : '',
      user_visible: true, last_message: s.last_message || '',
    })))
    if (!data.sessions.length) break
  } while (rows.length < total)
  return rows
}

export function creationPreview(data) {
  return {
    ...data, id: `creation:${data.id}`, creation_session_id: data.id, mode: 'creation',
    user: data.username, character: data.character_name,
    messages: data.messages.map((m) => ({ ...m, message_id: m.id, sequence_number: m.sequence,
      timestamp: new Date(m.timestamp).toISOString() })),
    message_offset: 0, message_total: data.messages.length, has_older: false, has_newer: false,
  }
}

export async function deleteCreationMessages(detail, messages) {
  const sid = encodeURIComponent(detail.creation_session_id)
  let version = detail.version
  for (const m of messages) {
    const data = await creationAdmin(`/${sid}/messages/${encodeURIComponent(m.message_id)}?version=${version}`, 'DELETE')
    version = data.version
  }
}

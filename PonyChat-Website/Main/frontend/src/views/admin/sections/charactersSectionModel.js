export const MBTI_OPTIONS = [
  { code: 'INTJ', name: '建筑师', desc: '冷静规划，擅长长期布局' },
  { code: 'INTP', name: '逻辑学家', desc: '好奇理性，喜欢拆解问题' },
  { code: 'ENTJ', name: '指挥官', desc: '目标明确，行动和掌控力强' },
  { code: 'ENTP', name: '辩论家', desc: '灵活机敏，享受新点子碰撞' },
  { code: 'INFJ', name: '提倡者', desc: '温柔坚定，重视深层意义' },
  { code: 'INFP', name: '调停者', desc: '理想主义，情感细腻真诚' },
  { code: 'ENFJ', name: '主人公', desc: '善于鼓舞，天然照顾他人' },
  { code: 'ENFP', name: '竞选者', desc: '热情自由，充满感染力' },
  { code: 'ISTJ', name: '物流师', desc: '可靠守序，重视责任和细节' },
  { code: 'ISFJ', name: '守卫者', desc: '体贴稳定，默默守护身边人' },
  { code: 'ESTJ', name: '总经理', desc: '务实果断，擅长组织执行' },
  { code: 'ESFJ', name: '执政官', desc: '亲切合群，重视关系和氛围' },
  { code: 'ISTP', name: '鉴赏家', desc: '冷静独立，擅长临场解决' },
  { code: 'ISFP', name: '探险家', desc: '柔和敏锐，追求真实体验' },
  { code: 'ESTP', name: '企业家', desc: '大胆直接，享受即时行动' },
  { code: 'ESFP', name: '表演者', desc: '活泼外放，喜欢带动气氛' },
]

export const VOICE_POLICY_OPTIONS = [
  { value: 'director', short: 'AI', label: '由导演决定', desc: '根据对话内容自动选择文本或语音' },
  { value: 'always_voice_when_available', short: 'ON', label: '可用时总是语音', desc: '语音服务可用时优先生成语音消息' },
  { value: 'off', short: 'OFF', label: '关闭', desc: '该角色不自动生成语音消息' },
]

export function createEditCharacterForm() {
  return {
    id: '', newId: '', name: '', signature: '', tags: '', persona: '', avatar: '',
    profileCover: '', profilePhotos: [], profileSpecies: '', profileGender: '', profileAge: '',
    profilePersonality: '', profileInterests: '', profileIntro: '', profileMbti: '',
    voiceEnabled: false, voiceId: '', voiceDecisionPolicy: 'director', voiceSourceMode: 'voice_id',
    voiceInstruct: '', voiceProfileId: '', voiceReferenceAudioUrl: '', voiceReferenceText: '',
    voiceCloneStatus: '', isUserVisible: true, isPublic: false, isWebVisible: false,
  }
}

export function createNewCharacterForm() {
  const form = createEditCharacterForm()
  delete form.newId
  delete form.avatar
  return form
}

function referencedSourceIdFromLocalId(character, sourceIds) {
  const id = String(character?.id || '')
  const separator = '__u_'
  if (!id.includes(separator)) return ''
  const sourceId = id.split(separator, 1)[0]
  return sourceId && sourceIds.has(sourceId) ? sourceId : ''
}

export function groupCharacters(characters, compareLocale) {
  const groups = new Map()
  const sourceIds = new Set(characters.map((character) => String(character.id || '')).filter(Boolean))
  for (const character of characters) {
    const localSourceId = referencedSourceIdFromLocalId(character, sourceIds)
    const key = character.isOfficialReference && character.officialSourceId
      ? character.officialSourceId
      : character.isHallReference && (character.hallSourceId || character.sourceId)
        ? character.hallSourceId || character.sourceId
        : localSourceId || character.id
    if (!groups.has(key)) groups.set(key, { source: null, refs: [] })
    const group = groups.get(key)
    const isReference = (character.isOfficialReference && character.officialSourceId)
      || (character.isHallReference && character.sourceId) || Boolean(localSourceId)
    if (isReference) group.refs.push(character)
    else group.source = character
  }
  return Array.from(groups.entries()).map(([key, group]) => {
    const source = group.source || group.refs[0]
    const sourceOwner = String(source.owner || source.creator || '').trim().toLowerCase()
    const refs = group.refs.slice().filter((reference) => {
      if (!group.source || !sourceOwner) return true
      return String(reference.owner || reference.creator || '').trim().toLowerCase() !== sourceOwner
    }).sort((a, b) => compareLocale(a.owner || a.id, b.owner || b.id, 1))
    const sourceOwnerRow = group.source
      ? { ...group.source, owner: group.source.owner || group.source.creator || '', isSourceOwner: true }
      : null
    const referenceRows = sourceOwnerRow ? [sourceOwnerRow, ...refs] : refs
    return {
      ...source, id: source.id || key, referenceRows, referenceCount: refs.length,
      referenceOwners: refs.map((reference) => reference.owner).filter(Boolean),
      isReferenceRepresentative: !group.source && refs.length > 0,
    }
  })
}

export function characterSignature(character) {
  return String(character?.signature || character?.preview || character?.bio || character?.description || '')
}

export function signaturePreview(character) {
  const text = characterSignature(character)
  return `${text.slice(0, 80)}${text.length > 80 ? '…' : ''}`
}

export function isVoiceEnabled(character) {
  return character?.voiceEnabled === true || character?.voice_enabled === true
}

export function filterAndSortCharacters(characters, options) {
  const { query, visibility, sortKey, sortDir, compareLocale, compareNumber } = options
  const normalizedQuery = query.trim().toLowerCase()
  const result = characters.filter((character) => {
    if (visibility === 'visible' && !character.isUserVisible) return false
    if (visibility === 'hidden' && character.isUserVisible) return false
    if (!normalizedQuery) return true
    const tags = Array.isArray(character.tags) ? character.tags.join(' ') : String(character.tags || '')
    const references = (character.referenceRows || [])
      .map((reference) => `${reference.id || ''} ${reference.owner || ''} ${reference.creator || ''}`).join(' ')
    return [character.name, character.id, character.creator, character.owner, references,
      characterSignature(character), tags].some((value) => String(value || '').toLowerCase().includes(normalizedQuery))
  })
  const direction = sortDir === 'asc' ? 1 : -1
  result.sort((a, b) => {
    if (sortKey === 'name') return compareLocale(a.name, b.name, direction)
    if (sortKey === 'creator') return compareLocale(a.creator, b.creator, direction)
    if (sortKey === 'id') return compareLocale(a.id, b.id, direction)
    if (sortKey === 'pub') return compareNumber(a.isPublic ? 1 : 0, b.isPublic ? 1 : 0, direction)
    if (sortKey === 'web') return compareNumber(a.isWebVisible ? 1 : 0, b.isWebVisible ? 1 : 0, direction)
    if (sortKey === 'voice') return compareNumber(isVoiceEnabled(a) ? 1 : 0, isVoiceEnabled(b) ? 1 : 0, direction)
    if (sortKey === 'bio') return compareLocale(characterSignature(a), characterSignature(b), direction)
    return 0
  })
  return result
}

export function mbtiLabel(code) {
  const item = MBTI_OPTIONS.find((option) => option.code === code)
  return item ? `${item.code} · ${item.name}` : '不展示'
}

export function voicePolicyLabel(value) {
  return VOICE_POLICY_OPTIONS.find((option) => option.value === value)?.label || '由导演决定'
}

export function playAudioTransfer(transfer) {
  const base64 = transfer?.data_base64 || transfer?.dataBase64
  if (!base64) return false
  const raw = atob(base64)
  const bytes = new Uint8Array(raw.length)
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index)
  const url = URL.createObjectURL(new Blob([bytes], { type: transfer.mime || 'audio/mpeg' }))
  const audio = new Audio(url)
  audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
  audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
  audio.play().catch(() => {})
  return true
}

export function formatVoiceDuration(seconds) {
  return seconds.toFixed(1).replace(/\.0$/, '')
}

export function probeLocalAudioDuration(file) {
  return new Promise((resolve) => {
    if (!file || typeof Audio === 'undefined' || typeof URL === 'undefined') return resolve(null)
    const audio = new Audio()
    const url = URL.createObjectURL(file)
    const finish = (value) => {
      clearTimeout(timer)
      audio.removeAttribute('src')
      URL.revokeObjectURL(url)
      resolve(value)
    }
    const timer = setTimeout(() => finish(null), 2500)
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      const duration = Number(audio.duration)
      finish(Number.isFinite(duration) && duration > 0 ? duration : null)
    }
    audio.onerror = () => finish(null)
    audio.src = url
  })
}

export function avatarUrl(avatar) {
  if (!avatar || typeof avatar !== 'string') return ''
  const value = avatar.trim()
  if (value.startsWith('http') || value.startsWith('data:') || value.startsWith('/')) return value
  return `/${value.replace(/^\/+/, '')}`
}

export function formatTagsForForm(tags) {
  if (!tags) return ''
  return Array.isArray(tags) ? tags.filter(Boolean).join(', ') : String(tags)
}

export function normalizeVoiceSource(value, character = {}) {
  const mode = String(value || '').trim().toLowerCase()
  if (['instruct', 'instruction', 'prompt'].includes(mode)) return 'instruct'
  if (['clone', 'reference', 'reference_audio'].includes(mode)) return 'clone'
  if (character.voiceReferenceAudioUrl || character.voice_reference_audio_url) return 'clone'
  if (character.voiceInstruct || character.voice_instruct) return 'instruct'
  return 'voice_id'
}

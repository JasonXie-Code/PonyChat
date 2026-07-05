<template>
  <div class="wc-root">
    <div v-if="phase === 'loading'" class="splash">
      <div class="spin" />
      <p class="splash-text">正在连接...</p>
    </div>

    <div v-else-if="phase === 'pick'" class="pick-screen">
      <header class="pick-hd">
        <RouterLink to="/" class="pick-brand">
          <img :src="logoSrc" alt="" width="30" height="30" />
          <span>PonyChat</span>
        </RouterLink>
        <span class="pick-badge">网页体验版</span>
      </header>

      <main class="pick-body">
        <h1 class="pick-title">选择角色，开始对话</h1>
        <p class="pick-sub">
          {{ characters.length ? '选一位角色，无需注册即可开始纯文本聊天' : loadErr ? '' : '正在加载...' }}
        </p>

        <div v-if="loadErr" class="notice notice-err">{{ loadErr }}</div>
        <div v-else-if="!characters.length" class="notice notice-empty">
          暂无可用网页角色。请管理员在后台“网页角色”处勾选并保存。
        </div>

        <div class="char-grid">
          <button
            v-for="c in characters"
            :key="c.id"
            class="char-card"
            type="button"
            @click="selectChar(c)"
          >
            <div class="cc-av-wrap">
              <img v-if="c.avatar" :src="avatarUrl(c.avatar)" class="cc-av" alt="" />
              <div v-else class="cc-av cc-av-ph">{{ firstChar(c.name) }}</div>
            </div>
            <div class="cc-meta">
              <span class="cc-name">{{ c.name }}</span>
              <span class="cc-bio">{{ excerpt(characterSignature(c) || '还没有留下签名。', 72) }}</span>
            </div>
            <svg class="cc-arr" viewBox="0 0 24 24" fill="none" width="16" height="16" aria-hidden="true">
              <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </main>

      <footer class="pick-foot">
        <a href="https://ponychat.org" class="pick-foot-link">完整体验请下载 App 或访问主站</a>
      </footer>
    </div>

    <div v-else class="chat-room">
      <header class="chat-hd">
        <div class="chat-hd-inner">
          <button class="btn-back" type="button" @click="backPick">
            <svg viewBox="0 0 24 24" fill="none" width="17" height="17" aria-hidden="true">
              <path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            返回
          </button>

          <div class="hd-char">
            <div class="hd-av-wrap">
              <img v-if="activeChar?.avatar" :src="avatarUrl(activeChar.avatar)" class="hd-av" alt="" />
              <div v-else class="hd-av hd-av-ph">{{ firstChar(activeChar?.name) }}</div>
              <span class="hd-dot" />
            </div>
            <div class="hd-meta">
              <span class="hd-name">{{ activeChar?.name }}</span>
              <span class="hd-bio">{{ excerpt(characterSignature(activeChar), 48) }}</span>
            </div>
          </div>

        </div>
      </header>

      <div ref="msgsEl" class="msgs">
        <div v-if="messages.length === 0 && !sending" class="welcome">
          <div class="wc-av-wrap">
            <img v-if="activeChar?.avatar" :src="avatarUrl(activeChar.avatar)" class="wc-av" alt="" />
            <div v-else class="wc-av wc-av-ph">{{ firstChar(activeChar?.name) }}</div>
          </div>
          <p class="wc-name">{{ activeChar?.name }}</p>
          <p class="wc-hint">{{ characterSignature(activeChar) || '发送一条消息，开始对话。' }}</p>
          <p class="wc-tip">纯文本体验，不支持图片发送；刷新后本页记录会清空</p>
        </div>

        <div
          v-for="m in messages"
          :key="m.id"
          class="msg-row"
          :class="m.role"
        >
          <div class="msg-shell">
            <div class="msg-head" :class="m.role">
              <span class="msg-name">{{ m.role === 'user' ? '我' : activeChar?.name }}</span>
              <span class="msg-time">{{ formatTime(m.timestamp) }}</span>
            </div>
            <div class="msg-line" :class="m.role">
              <div v-if="m.role === 'assistant'" class="msg-av-wrap">
                <img v-if="activeChar?.avatar" :src="avatarUrl(activeChar.avatar)" class="msg-av" alt="" />
                <div v-else class="msg-av msg-av-ph">{{ firstChar(activeChar?.name) }}</div>
              </div>
              <div class="bubble" :class="[m.role, { error: m.isError }]">{{ m.text }}</div>
              <div v-if="m.role === 'user'" class="msg-av-wrap">
                <img :src="logoSrc" class="msg-av user-av" alt="我" />
              </div>
            </div>
          </div>
        </div>

        <div v-if="replyPending" class="msg-row assistant pending-row">
          <div class="msg-shell">
            <div class="msg-head assistant">
              <span class="msg-name">{{ activeChar?.name }}</span>
              <span class="msg-time">正在思考</span>
            </div>
            <div class="msg-line assistant">
              <div class="msg-av-wrap">
                <img v-if="activeChar?.avatar" :src="avatarUrl(activeChar.avatar)" class="msg-av" alt="" />
                <div v-else class="msg-av msg-av-ph">{{ firstChar(activeChar?.name) }}</div>
              </div>
              <div class="bubble assistant pending-bubble">
                <span class="typing-dots">
                  <span /><span /><span />
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="composer-wrap">
        <div class="composer-inner">
          <p v-if="err" class="err-bar">{{ err }}</p>
          <form class="composer" @submit.prevent="send">
            <textarea
              ref="inputEl"
              v-model="input"
              class="c-inp"
              :placeholder="sending ? '等待角色回复中......' : '输入消息...'"
              rows="1"
              :disabled="sending"
              @keydown="onKey"
              @input="autoResize"
              @paste="onPaste"
              @drop.prevent
              @dragover.prevent
            />
            <button
              type="submit"
              class="c-send"
              :disabled="sending || !input.trim()"
              title="发送"
            >
              <svg viewBox="0 0 24 24" fill="none" width="20" height="20" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </form>
          <p class="composer-tip">Enter 发送&nbsp;·&nbsp;Shift+Enter 换行</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { usePublicUrl } from '../composables/usePublicUrl'
import { fetchPublicWebCharacters, guestLogin } from '../api/web'

const pub = usePublicUrl()
const logoSrc = pub('logo/logoBK512.png')

const phase = ref('loading')
const characters = ref([])
const activeChar = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const replyPending = ref(false)
const err = ref('')
const loadErr = ref('')
const msgsEl = ref(null)
const inputEl = ref(null)

let auth = { username: '', token: '' }
let clientId = ''
let conversationId = ''
let replyRunId = 0

const QUOTA_DISPLAY_MESSAGE = '试用结束，请下载App继续体验更多功能~'
const QUICK_QUOTA_COMMAND = '（额度）'

function quotaDisplayError() {
  const e = new Error(QUOTA_DISPLAY_MESSAGE)
  e.isQuotaDisplay = true
  return e
}

function isQuotaDisplayError(e) {
  return !!e?.isQuotaDisplay
}

function deviceId() {
  const k = 'ponychat_web_device_id'
  let id = localStorage.getItem(k)
  if (!id) {
    id = `web_${crypto.randomUUID?.() ?? String(Date.now())}`
    localStorage.setItem(k, id)
  }
  return id
}

function firstChar(text) {
  return (text || '?').trim().charAt(0) || '?'
}

function excerpt(text, max) {
  const s = (text || '').trim()
  return s.length > max ? `${s.slice(0, max)}...` : s
}

function characterSignature(character) {
  return String(character?.signature || character?.preview || '').trim()
}

function avatarUrl(avatar) {
  if (!avatar) return ''
  if (avatar.startsWith('http') || avatar.startsWith('data:')) return avatar
  return avatar.startsWith('/') ? avatar : `/${avatar}`
}

function scrollBottom() {
  nextTick(() => {
    const el = msgsEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

function formatTime(ts) {
  const date = new Date(ts || Date.now())
  const diff = Date.now() - date.getTime()
  if (diff >= 0 && diff < 60_000) return '刚刚'
  if (diff >= 0 && diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

function newMessage(role, text, extra = {}) {
  return {
    id: extra.id || `web_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    timestamp: extra.timestamp || Date.now(),
    messageId: extra.messageId || extra.id || null,
    sequenceNumber: extra.sequenceNumber ?? null,
    isError: !!extra.isError,
  }
}

function noteConversationId(value) {
  if (typeof value === 'string' && value.trim()) conversationId = value.trim()
}

function splitFallbackAssistantText(text) {
  return (text || '')
    .split(/\n{2,}/)
    .map(s => s.trim())
    .filter(Boolean)
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function clampDelay(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function nextBubbleDelayMs(previousText) {
  const base = clampDelay((String(previousText || '').length / 50) * 5000, 1000, 12000)
  const jitter = 0.85 + Math.random() * 0.3
  return Math.round(base * jitter)
}

function eventDisplayDelayMs(event, previousText) {
  const explicit = Number(event?.display_delay_ms ?? 0)
  if (Number.isFinite(explicit) && explicit > 0) return clampDelay(explicit, 300, 12000)
  const seconds = Number(event?.display_delay_seconds ?? 0)
  if (Number.isFinite(seconds) && seconds > 0) return clampDelay(seconds * 1000, 300, 12000)
  return nextBubbleDelayMs(previousText)
}

async function ensureAuth() {
  clientId = deviceId()
  const raw = sessionStorage.getItem('ponychat_web_auth')
  if (raw) {
    try {
      const parsed = JSON.parse(raw)
      if (parsed.username && parsed.token) {
        auth = parsed
        return
      }
    } catch { /* ignore */ }
  }
  const g = await guestLogin(clientId)
  auth = { username: g.username, token: g.token }
  sessionStorage.setItem('ponychat_web_auth', JSON.stringify(auth))
}

onMounted(async () => {
  try {
    await ensureAuth()
    const data = await fetchPublicWebCharacters()
    characters.value = data.characters || []
  } catch (e) {
    loadErr.value = e.message || String(e)
  } finally {
    phase.value = 'pick'
  }
})

function selectChar(c) {
  activeChar.value = c
  conversationId = ''
  messages.value = []
  err.value = ''
  phase.value = 'chat'
  nextTick(() => {
    autoResize()
    scrollBottom()
  })
}

function backPick() {
  replyRunId += 1
  phase.value = 'pick'
  activeChar.value = null
  messages.value = []
  conversationId = ''
  err.value = ''
  input.value = ''
  sending.value = false
  replyPending.value = false
}

function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function onPaste(e) {
  const items = Array.from(e.clipboardData?.items || [])
  if (items.some(item => item.kind === 'file')) {
    e.preventDefault()
    err.value = '网页体验版仅支持纯文本对话，不能发送图片。'
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || !activeChar.value || sending.value) return

  if (text === QUICK_QUOTA_COMMAND) {
    err.value = QUOTA_DISPLAY_MESSAGE
    input.value = ''
    nextTick(autoResize)
    return
  }

  err.value = ''
  const runId = ++replyRunId

  messages.value.push(newMessage('user', text))
  input.value = ''
  nextTick(() => {
    autoResize()
    scrollBottom()
  })

  sending.value = true
  replyPending.value = true

  const payload = buildMessages()
  const assistantStartIndex = messages.value.length
  let accumulated = ''
  let assistantCount = 0
  let serverAssistantIds = []
  let lastAssistantText = ''

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream, application/json',
        'X-Client-Id': clientId,
        'X-Chat-Auth': auth.token,
      },
      body: JSON.stringify({
        messages: payload,
        username: auth.username || '朋友',
        character_id: activeChar.value.id,
        stream: false,
        mode: 'normal',
        memory_enabled: false,
        crisis_hotline_enabled: true,
        conversation_id: conversationId || null,
        model_id: 'doubao-2-0-mini',
        enable_thinking: false,
        voice_enabled: false,
        enable_voice: false,
      }),
    })

    if (res.status === 429) {
      await res.json().catch(() => ({}))
      throw quotaDisplayError()
    }
    if (!res.ok) {
      throw new Error((await res.text()) || `HTTP ${res.status}`)
    }

    const ctype = res.headers.get('content-type') || ''
    if (ctype.includes('application/json')) {
      const json = await res.json()
      if (json.conversation_id) noteConversationId(json.conversation_id)
      if (json.job_id) throw new Error('当前模型为 Job 模式，网页体验版暂不支持，请联系管理员切换模型。')
      if (Array.isArray(json.events)) {
        for (const event of json.events) {
          await handleChatEvent(event, { respectEventDelay: true, runId })
        }
      } else {
        const fallback = json.content ?? json.message?.content ?? json.message?.rawContent ?? ''
        if (typeof fallback === 'string') accumulated += fallback
      }
    } else {
      await readSse(res, event => handleChatEvent(event, { respectEventDelay: false, runId }))
    }

    if (assistantCount === 0 && accumulated.trim()) {
      const parts = splitFallbackAssistantText(accumulated)
      const list = parts.length ? parts : [accumulated.trim()]
      for (const [idx, part] of list.entries()) {
        if (runId !== replyRunId) return
        if (idx > 0) await sleep(nextBubbleDelayMs(list[idx - 1]))
        if (runId !== replyRunId) return
        pushAssistantMessage(part, {
          id: serverAssistantIds[idx],
          messageId: serverAssistantIds[idx],
          timestamp: Date.now() + idx,
        })
      }
    }
  } catch (e) {
    if (runId !== replyRunId) return
    const quotaError = isQuotaDisplayError(e)
    err.value = quotaError ? QUOTA_DISPLAY_MESSAGE : (e.message || String(e))
    if (!quotaError && assistantCount === 0 && !accumulated.trim()) {
      replyPending.value = false
      messages.value.push(newMessage('assistant', err.value, { isError: true }))
    }
  } finally {
    if (runId === replyRunId) {
      sending.value = false
      replyPending.value = false
      scrollBottom()
    }
  }

  async function handleChatEvent(d, options = {}) {
    if (!d || typeof d !== 'object') return
    if (options.runId && options.runId !== replyRunId) return
    noteConversationId(d.conversation_id)
    noteConversationId(d.metadata?.conversation_id)

    if (d.type === 'assistant_paragraph') {
      const content = String(d.content || '').trim()
      if (!content) return
      if (options.respectEventDelay && assistantCount > 0) {
        await sleep(eventDisplayDelayMs(d, lastAssistantText))
      }
      if (options.runId && options.runId !== replyRunId) return
      pushAssistantMessage(content, {
        id: d.id || null,
        messageId: d.id || null,
        timestamp: d.timestamp || Date.now() + assistantCount,
        sequenceNumber: d.sequence_number ?? d.index ?? null,
      })
      return
    }

    if (d.type === 'save_status') {
      if (Array.isArray(d.assistant_message_ids)) {
        serverAssistantIds = d.assistant_message_ids.filter(Boolean)
        applyServerAssistantIds(assistantStartIndex, serverAssistantIds)
      } else if (d.assistant_message_id) {
        serverAssistantIds = [d.assistant_message_id]
        applyServerAssistantIds(assistantStartIndex, serverAssistantIds)
      }
      return
    }

    if (d.type === 'accepted' || d.type === 'metadata') return

    if (d.type === 'no_reply') {
      replyPending.value = false
      return
    }

    if (d.type === 'quota_exceeded') {
      throw quotaDisplayError()
    }

    if (d.type === 'cancelled') {
      throw new Error('本轮回复已被新的消息取代。')
    }

    if (d.type === 'error') {
      throw new Error(d.message || '生成失败')
    }

    if (d.type === 'done' || d.type === 'crisis_triggered') return

    const delta = d.text ?? d.choices?.[0]?.delta?.content
    if (delta && assistantCount === 0) {
      accumulated += delta
    }

    if (d.error) throw new Error(d.error)
  }

  function pushAssistantMessage(content, extra = {}) {
    replyPending.value = false
    messages.value.push(newMessage('assistant', content, extra))
    assistantCount += 1
    lastAssistantText = content
    scrollBottom()
  }
}

async function readSse(res, onEvent) {
  const reader = res.body?.getReader()
  if (!reader) {
    const text = await res.text().catch(() => '')
    if (text) throw new Error(text)
    return
  }

  const decoder = new TextDecoder()
  let lineBuf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    lineBuf += decoder.decode(value, { stream: true })
    const lines = lineBuf.split(/\r?\n/)
    lineBuf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      const str = line.slice(5).trim()
      if (!str || str === '[DONE]') continue
      let event
      try {
        event = JSON.parse(str)
      } catch {
        continue
      }
      await onEvent(event)
    }
  }
}

function applyServerAssistantIds(startIndex, ids) {
  if (!ids.length) return
  const assistants = messages.value
    .map((m, idx) => ({ m, idx }))
    .filter(({ m, idx }) => idx >= startIndex && m.role === 'assistant' && !m.isError)
  assistants.forEach(({ m }, idx) => {
    if (ids[idx]) {
      m.id = ids[idx]
      m.messageId = ids[idx]
    }
  })
}

function buildMessages() {
  return messages.value
    .filter(m => (m.role === 'user' || m.role === 'assistant') && !m.isError)
    .map((m, i) => ({
      role: m.role,
      content: m.text,
      message_id: m.messageId || m.id,
      sequence_number: i,
      timestamp: m.timestamp,
    }))
}
</script>

<style scoped>
.wc-root {
  min-height: 100dvh;
  background: #0f172a;
  color: #e2e8f0;
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  display: flex;
  flex-direction: column;
}

.splash {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
}
.splash-text { color: #94a3b8; font-size: 0.9rem; }
.spin {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 3px solid #1e293b;
  border-top-color: var(--accent-from, #9f86d6);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.pick-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(159, 134, 214, 0.12), transparent 70%), #0f172a;
}
.pick-hd {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.9rem 1.5rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.pick-brand {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  text-decoration: none;
  color: #e2e8f0;
  font-weight: 700;
  font-size: 1rem;
}
.pick-brand img { border-radius: 8px; }
.pick-badge {
  margin-left: auto;
  font-size: 0.7rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: rgba(159, 134, 214, 0.12);
  color: var(--accent-from, #9f86d6);
  border: 1px solid rgba(159, 134, 214, 0.22);
}
.pick-body {
  flex: 1;
  padding: 2.5rem 1.5rem 2rem;
  max-width: 780px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}
.pick-title {
  font-size: clamp(1.4rem, 4vw, 2rem);
  font-weight: 700;
  margin: 0 0 0.5rem;
  color: #e2e8f0;
}
.pick-sub {
  color: #64748b;
  font-size: 0.9rem;
  margin: 0 0 1.75rem;
}
.notice {
  padding: 0.85rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.88rem;
  margin-bottom: 1.25rem;
}
.notice-err {
  background: rgba(248,113,113,0.1);
  border: 1px solid rgba(248,113,113,0.3);
  color: #e8a0a0;
}
.notice-empty {
  background: rgba(148,163,184,0.06);
  border: 1px dashed #334155;
  color: #64748b;
}
.char-grid {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.char-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  text-align: left;
  padding: 0.9rem 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(255,255,255,0.07);
  background: rgba(255,255,255,0.03);
  color: inherit;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, transform 0.15s;
}
.char-card:hover {
  border-color: rgba(159, 134, 214, 0.42);
  background: rgba(159, 134, 214, 0.06);
  transform: translateY(-1px);
}
.cc-av-wrap { flex-shrink: 0; }
.cc-av {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  object-fit: cover;
  display: block;
}
.cc-av-ph,
.hd-av-ph,
.wc-av-ph,
.msg-av-ph {
  background: var(--cta-gradient, linear-gradient(135deg, #6652c4, #7549d4));
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #fff;
}
.cc-av-ph { font-size: 1.4rem; }
.cc-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.cc-name { font-weight: 600; color: #e2e8f0; }
.cc-bio {
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.4;
}
.cc-arr {
  flex-shrink: 0;
  color: #475569;
  transition: color 0.2s, transform 0.2s;
}
.char-card:hover .cc-arr {
  color: var(--accent-from, #9f86d6);
  transform: translateX(3px);
}
.pick-foot {
  text-align: center;
  padding: 1.2rem;
  border-top: 1px solid rgba(255,255,255,0.05);
}
.pick-foot-link {
  color: #475569;
  font-size: 0.78rem;
  text-decoration: none;
}
.pick-foot-link:hover { color: #94a3b8; }

.chat-room {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100dvh;
  max-height: 100dvh;
  background: #0f172a;
}
.chat-hd {
  padding: 0.6rem 1rem;
  background: rgba(15,23,42,0.95);
  border-bottom: 1px solid rgba(255,255,255,0.07);
  backdrop-filter: blur(12px);
  flex-shrink: 0;
  z-index: 10;
}
.chat-hd-inner {
  width: min(100%, 800px);
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.btn-back {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 0.82rem;
  padding: 0.35rem 0.55rem;
  border-radius: 0.5rem;
  white-space: nowrap;
}
.btn-back:hover { color: #a78bfa; background: rgba(159, 134, 214, 0.08); }
.hd-char {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex: 1;
  min-width: 0;
}
.hd-av-wrap { position: relative; flex-shrink: 0; }
.hd-av {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  object-fit: cover;
  display: block;
}
.hd-av-ph { width: 36px; height: 36px; border-radius: 10px; font-size: 1rem; }
.hd-dot {
  position: absolute;
  bottom: -1px;
  right: -1px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent-to, #4ebfcf);
  border: 2px solid #0f172a;
}
.hd-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}
.hd-name {
  font-weight: 600;
  font-size: 0.92rem;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hd-bio {
  font-size: 0.72rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.msgs {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  scroll-behavior: smooth;
}
.msgs::-webkit-scrollbar { width: 4px; }
.msgs::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }
.welcome {
  width: min(100%, 800px);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  flex: 1;
  padding: 2rem 1rem;
  text-align: center;
}
.wc-av {
  width: 80px;
  height: 80px;
  border-radius: 22px;
  object-fit: cover;
  box-shadow: 0 0 0 3px rgba(159, 134, 214, 0.2), 0 8px 32px rgba(0,0,0,0.4);
}
.wc-av-ph { width: 80px; height: 80px; border-radius: 22px; font-size: 2rem; }
.wc-name { font-size: 1.2rem; font-weight: 700; color: #e2e8f0; margin: 0; }
.wc-hint { font-size: 0.88rem; color: #64748b; margin: 0; max-width: 320px; line-height: 1.5; }
.wc-tip {
  font-size: 0.72rem;
  color: #475569;
  margin-top: 0.5rem;
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.05);
  background: rgba(255,255,255,0.02);
}

.msg-row {
  width: min(100%, 800px);
  margin: 0 auto;
  display: flex;
  max-width: 100%;
  animation: msgIn 0.28s cubic-bezier(0.2, 0, 0.2, 1);
}
.msg-row.user {
  justify-content: flex-end;
  animation-name: msgInUser;
}
.msg-row.assistant {
  justify-content: flex-start;
  animation-name: msgInAssistant;
}
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } }
@keyframes msgInAssistant { from { opacity: 0; transform: translateX(-28px); } }
@keyframes msgInUser { from { opacity: 0; transform: translateX(22px); } }
.msg-shell {
  width: min(94%, 760px);
}
.msg-row.user .msg-shell { margin-left: auto; }
.msg-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
  color: #94a3b8;
  font-size: 0.72rem;
}
.msg-head.user {
  justify-content: flex-end;
  padding-right: 48px;
}
.msg-head.assistant {
  justify-content: flex-start;
  padding-left: 48px;
}
.msg-name { font-weight: 600; color: #94a3b8; }
.msg-time { color: #64748b; }
.msg-line {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}
.msg-line.user { justify-content: flex-end; padding-left: 48px; }
.msg-line.assistant { justify-content: flex-start; padding-right: 48px; }
.msg-av-wrap { flex-shrink: 0; }
.msg-av {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
}
.user-av {
  background: #1e293b;
  border: none;
  padding: 0;
  object-fit: cover;
}
.bubble {
  max-width: min(560px, 72vw);
  padding: 0.62rem 0.88rem;
  font-size: 0.92rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  letter-spacing: 0;
}
.bubble.user {
  border-radius: 16px 4px 16px 16px;
  background: linear-gradient(135deg, #6763f2, #5147e7);
  color: #fff;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.18);
}
.bubble.assistant {
  border-radius: 4px 16px 16px 16px;
  background: #202b3d;
  color: #e2e8f0;
  border: 1px solid rgba(255,255,255,0.055);
  box-shadow: 0 1px 2px rgba(0,0,0,0.14);
}
.bubble.error {
  color: #fecaca;
  border-color: rgba(248,113,113,0.28);
  background: rgba(127,29,29,0.32);
}
.pending-row .msg-head { opacity: 0.82; }
.pending-bubble { opacity: 0.95; min-width: 54px; }
.typing-dots {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  height: 1.2em;
}
.typing-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  animation: dot 1.2s infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot {
  0%, 80%, 100% { transform: scale(0.75); opacity: 0.35; }
  40% { transform: scale(1); opacity: 1; }
}

.composer-wrap {
  flex-shrink: 0;
  padding: 0.55rem 0.85rem 0.65rem;
  background: rgba(15,23,42,0.97);
  border-top: 1px solid rgba(255,255,255,0.06);
  backdrop-filter: blur(12px);
}
.composer-inner {
  width: min(100%, 800px);
  margin: 0 auto;
}
.err-bar {
  margin: 0 0 0.45rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.7rem;
  background: rgba(248,113,113,0.12);
  border: 1px solid rgba(248,113,113,0.25);
  color: #fecaca;
  font-size: 0.82rem;
}
.composer {
  display: flex;
  align-items: flex-end;
  gap: 0.55rem;
}
.c-inp {
  flex: 1;
  min-height: 42px;
  max-height: 132px;
  resize: none;
  border: none;
  border-radius: 22px;
  background: rgba(255,255,255,0.08);
  color: #e2e8f0;
  font: inherit;
  font-size: 0.92rem;
  line-height: 21px;
  padding: 10.5px 16px;
  outline: none;
  overflow-y: auto;
  box-sizing: border-box;
}
.c-inp:focus {
  box-shadow: 0 0 0 2px rgba(159,134,214,0.23);
}
.c-inp::placeholder { color: rgba(148,163,184,0.55); }
.c-send {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: none;
  background: #6366f1;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.2s, transform 0.15s, background 0.2s;
}
.c-send:hover:not(:disabled) {
  background: #4f46e5;
  transform: translateY(-1px);
}
.c-send:disabled {
  opacity: 0.38;
  cursor: not-allowed;
  background: #334155;
  color: #94a3b8;
}
.composer-tip {
  margin: 0.35rem 0 0;
  font-size: 0.68rem;
  color: #475569;
  text-align: center;
}

@media (max-width: 560px) {
  .pick-body { padding: 1.75rem 1rem 1.5rem; }
  .cc-av { width: 48px; height: 48px; border-radius: 12px; }
  .msgs { padding: 0.75rem 0.75rem 0.25rem; }
  .msg-shell { width: 100%; }
  .msg-line.user { padding-left: 28px; }
  .msg-line.assistant { padding-right: 28px; }
  .msg-head.user { padding-right: 48px; }
  .msg-head.assistant { padding-left: 48px; }
  .bubble { max-width: calc(100vw - 116px); }
}
</style>

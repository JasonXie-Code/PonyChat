<template>
  <div class="terminal-view">
    <div class="term-toolbar">
      <button type="button" class="btn btn-sm" @click="clearTerm">清屏</button>
      <button type="button" class="btn btn-sm" @click="togglePause">{{ paused ? '继续' : '暂停' }}</button>
      <button type="button" class="btn btn-sm" @click="copySelection">复制选中</button>
      <span class="term-hint">Ctrl+C 复制选中 / 取消行 · Ctrl+V 粘贴 · 选中自动复制 · help 查看命令</span>
    </div>
    <div ref="termEl" class="term-wrap" />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import '../../styles/admin-shell.css'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const termEl = ref(null)
const paused = ref(false)
let term
let fitAddon
let ws
let ro
let reconnectTimer
let intentionalClose = false
const pendingWhilePaused = []

// 本地行缓冲（用于本地回显，不依赖后端 echo）
let lineBuf = ''

function _token() {
  try {
    const raw = sessionStorage.getItem('adminUser')
    if (raw) {
      const u = JSON.parse(raw)
      if (u && u.token) return u.token
    }
  } catch {
    /* 忽略 */
  }
  return (
    (typeof localStorage !== 'undefined' && localStorage.getItem('admin_token')) ||
    new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '').get('token') ||
    'admin_token_placeholder'
  )
}

function _wsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = encodeURIComponent(_token())
  return `${proto}//${window.location.host}/ws/admin/console?token=${token}`
}

function flushPaused() {
  if (!term || pendingWhilePaused.length === 0) return
  for (const chunk of pendingWhilePaused) {
    term.write(chunk)
  }
  pendingWhilePaused.length = 0
}

function togglePause() {
  paused.value = !paused.value
  if (!paused.value) flushPaused()
}

function clearTerm() {
  try { term?.clear() } catch { /* ignore */ }
}

function copySelection() {
  const sel = term?.getSelection()
  if (sel) {
    navigator.clipboard.writeText(sel).catch(() => {})
  }
}

function writeToTerm(chunk) {
  if (!term) return
  if (paused.value) {
    pendingWhilePaused.push(chunk)
  } else {
    term.write(chunk)
  }
}

function attachWsHandlers(socket) {
  socket.onopen = () => {
    term.writeln('\x1b[32m已连接 PonyChat 后端控制台。\x1b[0m')
  }
  socket.onmessage = (ev) => {
    try {
      const j = JSON.parse(ev.data)
      if (j.type === 'pty' && typeof j.data === 'string') {
        writeToTerm(j.data)
      } else if (j.type === 'log' && typeof j.line === 'string') {
        writeToTerm(`\x1b[33m${j.line}\x1b[0m\r\n`)
      }
    } catch { /* ignore */ }
  }
  socket.onerror = () => term.writeln('\x1b[31mWebSocket 错误\x1b[0m')
  socket.onclose = () => {
    if (intentionalClose) {
      term.writeln('\x1b[31m连接已关闭\x1b[0m')
      return
    }
    term.writeln('\x1b[33m连接断开，3 秒后自动重连…\x1b[0m')
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      tryConnect()
    }, 3000)
  }
}

function tryConnect() {
  if (intentionalClose) return
  try { ws?.close() } catch { /* ignore */ }
  ws = new WebSocket(_wsUrl())
  ws.binaryType = 'arraybuffer'
  attachWsHandlers(ws)
}

function handleInput(data) {
  for (const ch of data) {
    const code = ch.charCodeAt(0)
    if (ch === '\r' || ch === '\n') {
      term.write('\r\n')
      const cmd = lineBuf.trim()
      lineBuf = ''
      if (cmd && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'stdin', data: cmd + '\n' }))
      }
    } else if (ch === '\u007f' || ch === '\b') {
      if (lineBuf.length > 0) {
        lineBuf = lineBuf.slice(0, -1)
        term.write('\b \b')
      }
    } else if (ch === '\u0003') {
      if (lineBuf.length > 0) {
        term.write('^C\r\n')
        lineBuf = ''
      }
    } else if (code >= 0x20 || ch === '\t') {
      lineBuf += ch
      term.write(ch)
    }
  }
}

onMounted(() => {
  intentionalClose = false
  lineBuf = ''

  term = new Terminal({
    cursorBlink: true,
    convertEol: true,
    copyOnSelect: true,   // 选中即复制，绕过浏览器快捷键限制
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 13,
    theme: { background: '#0f172a', foreground: '#e0f2fe' },
    scrollback: 5000,
  })
  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.open(termEl.value)
  fitAddon.fit()

  term.onData(handleInput)

  term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown') return true

    // Ctrl+C：有选区则复制；无选区则让 xterm 传 \u0003 → handleInput → 取消当前行
    if (e.ctrlKey && !e.shiftKey && e.key === 'c') {
      const sel = term.getSelection()
      if (sel) {
        navigator.clipboard.writeText(sel).catch(() => {})
        return false   // 阻止 xterm 发送 \u0003
      }
      return true      // 无选区：放行给 handleInput 处理（取消行）
    }

    // Ctrl+V：粘贴
    if (e.ctrlKey && !e.shiftKey && e.key === 'v') {
      navigator.clipboard.readText().then((text) => {
        if (text) handleInput(text)
      }).catch(() => {})
      return false
    }

    return true
  })

  tryConnect()

  ro = new ResizeObserver(() => {
    try { fitAddon.fit() } catch { /* ignore */ }
  })
  ro.observe(termEl.value)
})

onUnmounted(() => {
  intentionalClose = true
  lineBuf = ''
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ro && termEl.value) ro.unobserve(termEl.value)
  ro = null
  try { ws && ws.close() } catch { /* ignore */ }
  ws = null
  try { term && term.dispose() } catch { /* ignore */ }
  term = null
})
</script>

<style scoped>
.terminal-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: #0f172a;
}
.term-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.75rem;
  background: rgba(30, 41, 59, 0.8);
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  flex-shrink: 0;
}
.term-hint {
  opacity: 0.55;
  font-size: 0.72rem;
  color: #e0f2fe;
  flex: 1;
}
.term-wrap {
  flex: 1;
  min-height: 0;
  padding: 0.25rem 0.5rem;
  position: relative;
}
.term-wrap :deep(.xterm) {
  height: 100%;
}
.term-wrap :deep(.xterm-viewport) {
  overflow-y: auto !important;
  left: auto !important;
  width: 18px;
  z-index: 4;
  background: rgba(15, 23, 42, 0.45) !important;
  pointer-events: auto;
}
.term-wrap :deep(.xterm-screen) {
  z-index: 1;
}
</style>

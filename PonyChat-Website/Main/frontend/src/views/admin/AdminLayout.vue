<template>
  <div class="layout admin-shell">
    <aside class="sidebar">
      <div class="side-head">
        <img :src="logo" alt="" class="side-logo" />
        <div class="side-title">管理控制台</div>
      </div>
      <nav class="nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          active-class="active"
        >
          <ion-icon :name="item.ion" class="nav-ion" aria-hidden="true" />
          <span class="nav-label">{{ item.label }}</span>
          <span class="nav-kbd">{{ item.kbd }}</span>
        </RouterLink>
        <RouterLink to="/admin/terminal" class="nav-item nav-terminal" active-class="active">
          <ion-icon name="terminal-outline" class="nav-ion" aria-hidden="true" />
          <span class="nav-label">后端控制台</span>
          <span class="nav-kbd">T</span>
        </RouterLink>
        <RouterLink to="/admin/conversation-logs" class="nav-item" active-class="active">
          <ion-icon name="document-text-outline" class="nav-ion" aria-hidden="true" />
          <span class="nav-label">对话日志</span>
          <span class="nav-kbd">Y</span>
        </RouterLink>
      </nav>
      <div class="side-foot">
        <button type="button" class="btn btn-danger-outline btn-block" @click="onLogout">退出登录</button>
        <p class="muted ver">PonyChat Admin</p>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <h2>{{ title }}</h2>
        <div class="topbar-right">
          <button type="button" class="btn cmd-open-btn" title="命令面板 (Ctrl+K)" @click="paletteOpen = true">
            <ion-icon name="search-outline" aria-hidden="true" />
            <span>搜索</span>
          </button>
          <span class="status-dot-wrap" title="服务连接">
            <span class="status-dot" />
            <span class="status-txt">运行中</span>
          </span>
          <time class="server-clock" :datetime="clockIso">{{ clockText }}</time>
          <span class="who">{{ adminStore.username }}</span>
        </div>
      </header>
      <div class="content" :class="{ 'content-terminal': isTerminal, 'content-scroll': !isTerminal }">
        <RouterView />
      </div>
    </div>

    <ToastContainer />
    <ConfirmDialog />
    <CommandPalette v-model="paletteOpen" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAdminStore } from '../../stores/adminStore'
import ToastContainer from '../../components/admin/ToastContainer.vue'
import ConfirmDialog from '../../components/admin/ConfirmDialog.vue'
import CommandPalette from '../../components/admin/CommandPalette.vue'
import { ADMIN_TIME_ZONE } from '../../composables/useAdminTableSort'
import { usePublicUrl } from '../../composables/usePublicUrl'
import '../../styles/admin-shell.css'

const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()
const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

const paletteOpen = ref(false)
const clockText = ref('')
const clockIso = ref('')

const navItems = [
  { to: '/admin/overview', label: '数据概览', ion: 'bar-chart-outline', kbd: '1' },
  { to: '/admin/users', label: '用户管理', ion: 'people-outline', kbd: '2' },
  { to: '/admin/conversations', label: '对话记录', ion: 'chatbubble-ellipses-outline', kbd: '3' },
  { to: '/admin/characters', label: '角色管理', ion: 'planet-outline', kbd: '4' },
  { to: '/admin/assets', label: '素材管理', ion: 'albums-outline', kbd: '5' },
  { to: '/admin/invites', label: '邀请码', ion: 'pricetags-outline', kbd: '6' },
  { to: '/admin/models', label: '模型配置', ion: 'hardware-chip-outline', kbd: '7' },
  { to: '/admin/recovery', label: '数据恢复', ion: 'construct-outline', kbd: '8' },
  { to: '/admin/system', label: '系统设置', ion: 'settings-outline', kbd: '9' },
]

const digitRoutes = [
  '/admin/overview',
  '/admin/users',
  '/admin/conversations',
  '/admin/characters',
  '/admin/assets',
  '/admin/invites',
  '/admin/models',
  '/admin/recovery',
  '/admin/system',
]

function tickClock() {
  const d = new Date()
  clockIso.value = d.toISOString()
  clockText.value = d.toLocaleString('zh-CN', {
    timeZone: ADMIN_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function onKeyDown(e) {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
    return
  }
  if (paletteOpen.value && e.key === 'Escape') {
    e.preventDefault()
    paletteOpen.value = false
    return
  }
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return

  const k = e.key
  if (k >= '1' && k <= '9') {
    const i = parseInt(k, 10) - 1
    if (digitRoutes[i]) {
      e.preventDefault()
      router.push(digitRoutes[i])
    }
    return
  }
  if (k === 't' || k === 'T') {
    e.preventDefault()
    router.push('/admin/terminal')
  }
  if (k === 'y' || k === 'Y') {
    e.preventDefault()
    router.push('/admin/conversation-logs')
  }
}

const isTerminal = computed(() => route.path.startsWith('/admin/terminal'))

const isLogs = computed(() => route.path.startsWith('/admin/conversation-logs'))

const title = computed(() => {
  const m = navItems.find((n) => n.to === route.path)
  if (m) return m.label
  if (isTerminal.value) return '后端控制台'
  if (isLogs.value) return '对话日志'
  return '管理控制台'
})

function onLogout() {
  adminStore.logout()
  router.replace('/admin/login')
}

let clockTimer
function lockBodyScroll() {
  document.documentElement.style.overflow = 'hidden'
  document.documentElement.style.height = '100%'
  document.body.style.overflow = 'hidden'
  document.body.style.height = '100%'
  const app = document.getElementById('app')
  if (app) {
    app.style.height = '100%'
    app.style.overflow = 'hidden'
  }
}
function unlockBodyScroll() {
  document.documentElement.style.overflow = ''
  document.documentElement.style.height = ''
  document.body.style.overflow = ''
  document.body.style.height = ''
  const app = document.getElementById('app')
  if (app) {
    app.style.height = ''
    app.style.overflow = ''
  }
}

function onWebCharsUpdated() {}

onMounted(() => {
  lockBodyScroll()
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('ponychat-admin-webchars-updated', onWebCharsUpdated)
})
watch(
  () => route.path,
  (_p) => {
    // 路由变化时的钩子（保留扩展点）
  },
)
onUnmounted(() => {
  unlockBodyScroll()
  if (clockTimer) clearInterval(clockTimer)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('ponychat-admin-webchars-updated', onWebCharsUpdated)
})
</script>

<style scoped>
.layout {
  display: flex;
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  min-width: 1280px;
}
.sidebar {
  width: var(--sidebar-width);
  background: var(--bg-elevated);
  border-right: 1px solid var(--stroke);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.side-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-bottom: 1px solid var(--stroke);
  min-height: var(--topbar-h);
}
.side-logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.side-title {
  font-weight: 700;
  font-size: 0.95rem;
  font-family: var(--font-display);
  flex: 1;
  color: var(--text);
}
.nav {
  flex: 1;
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-sm);
  color: var(--text);
  text-decoration: none;
  font-size: 0.875rem;
}
.nav-item:hover {
  background: var(--surface-hover);
}
.nav-item.active {
  background: linear-gradient(90deg, rgba(159, 134, 214, 0.18), transparent);
  border-left: 3px solid var(--accent-from);
  padding-left: calc(0.65rem - 3px);
}
.nav-ion {
  font-size: 1.15rem;
  width: 1.25rem;
  height: 1.25rem;
  color: var(--accent-mid);
}
.nav-item.active .nav-ion {
  color: var(--accent-to);
}
.nav-label {
  flex: 1;
}
.nav-count {
  font-size: 0.65rem;
  font-weight: 700;
  min-width: 1.1rem;
  padding: 0.08rem 0.32rem;
  border-radius: 999px;
  background: rgba(117, 73, 212, 0.32);
  color: #ddd6f5;
  line-height: 1.2;
}
.nav-kbd {
  font-size: 0.7rem;
  color: var(--text-dim);
  background: var(--bg-deep);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
}
.nav-terminal {
  margin-top: 0.5rem;
  border-top: 1px dashed var(--stroke);
  padding-top: 0.75rem;
}
.side-foot {
  padding: 0.75rem;
  border-top: 1px solid var(--stroke);
}
.btn-block {
  width: 100%;
  justify-content: center;
}
.ver {
  text-align: center;
  margin: 0.5rem 0 0;
  font-size: 0.7rem;
}
.main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 1.25rem;
  min-height: var(--topbar-h);
  border-bottom: 1px solid var(--stroke);
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(8px);
}
.topbar h2 {
  margin: 0;
  font-size: 1.1rem;
  font-family: var(--font-display);
  font-weight: 600;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
.cmd-open-btn span {
  font-size: 0.8rem;
}
.status-dot-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 8px var(--ok);
}
.status-txt {
  font-size: 0.75rem;
}
.server-clock {
  font-variant-numeric: tabular-nums;
  font-size: 0.85rem;
  color: var(--text-muted);
}
.who {
  font-size: 0.85rem;
  color: var(--text-muted);
}
.content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* .content-scroll 布局见 admin-shell.css（满高 flex + 子页滚动策略） */
.content-terminal {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>

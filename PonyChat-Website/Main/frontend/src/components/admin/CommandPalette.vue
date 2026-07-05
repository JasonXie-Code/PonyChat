<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="cmd-mask admin-shell"
      @mousedown="onBackdropMouseDown"
      @click.self="onBackdropClickSelf"
    >
      <div class="cmd-box card" role="dialog" aria-modal="true" aria-label="命令面板">
        <div class="cmd-head">
          <ion-icon name="search-outline" class="cmd-ion" aria-hidden="true" />
          <input
            ref="inputRef"
            v-model="q"
            type="text"
            class="cmd-input"
            placeholder="搜索页面或输入关键词…"
            autocomplete="off"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="goActive"
            @keydown.escape="close"
          />
          <button
            v-show="q.length > 0"
            type="button"
            class="cmd-clear"
            aria-label="清空"
            @click="clearQuery"
          >
            <ion-icon name="close-outline" class="cmd-clear-ion" aria-hidden="true" />
          </button>
        </div>
        <ul class="cmd-list" role="listbox">
          <template v-for="(item, i) in filteredRows" :key="item.key">
            <li v-if="item.type === 'group'" class="cmd-group-label">{{ item.label }}</li>
            <li
              v-else
              class="cmd-item"
              :class="{ active: i === active }"
              role="option"
              :aria-selected="i === active"
              @click="pick(item)"
              @mouseenter="active = i"
            >
              <ion-icon :name="item.ion" class="cmd-item-ion" aria-hidden="true" />
              <span class="cmd-label">{{ item.label }}</span>
              <span v-if="item.sub" class="cmd-sub muted">{{ item.sub }}</span>
              <span v-else class="cmd-path muted">{{ item.path }}</span>
            </li>
          </template>
          <li v-if="emptyMessage === 'loading'" class="cmd-empty muted">加载中…</li>
          <li v-else-if="emptyMessage === 'empty'" class="cmd-empty muted">无匹配项</li>
        </ul>
        <p class="cmd-hint muted">↑↓ 选择 · Enter 跳转 · Esc 关闭</p>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchUsers, fetchAdminCharacters } from '../../api/admin'
import { useModalBackdropDismiss } from '../../composables/useModalBackdropDismiss'
import '../../styles/admin-shell.css'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const router = useRouter()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const q = ref('')
const active = ref(0)
const inputRef = ref(null)

/** @type {import('vue').Ref<any[]|null>} */
const usersCache = ref(null)
/** @type {import('vue').Ref<any[]|null>} */
const charsCache = ref(null)
const cacheLoading = ref(false)

const NAV = [
  { to: '/admin/overview', label: '数据概览', ion: 'bar-chart-outline' },
  { to: '/admin/users', label: '用户管理', ion: 'people-outline' },
  { to: '/admin/conversations', label: '对话记录', ion: 'chatbubbles-outline' },
  { to: '/admin/characters', label: '角色管理', ion: 'planet-outline' },
  { to: '/admin/assets', label: '素材管理', ion: 'albums-outline' },
  { to: '/admin/invites', label: '邀请码', ion: 'pricetags-outline' },
  { to: '/admin/models', label: '模型配置', ion: 'hardware-chip-outline' },
  { to: '/admin/recovery', label: '数据恢复', ion: 'construct-outline' },
  { to: '/admin/system', label: '系统设置', ion: 'settings-outline' },
  { to: '/admin/terminal', label: '后端控制台', ion: 'terminal-outline' },
  { to: '/admin/conversation-logs', label: '对话日志', ion: 'document-text-outline' },
]

function userSub(u) {
  const mem = u.membership_label || u.membership_type || ''
  const st = u.disabled ? '已禁用' : '正常'
  return [mem, st].filter(Boolean).join(' · ')
}

async function ensureCache() {
  if (usersCache.value !== null && charsCache.value !== null) return
  cacheLoading.value = true
  try {
    const [u, ch] = await Promise.all([fetchUsers(), fetchAdminCharacters()])
    usersCache.value = Array.isArray(u) ? u : u?.users ?? []
    charsCache.value = Array.isArray(ch) ? ch : ch?.characters ?? []
  } catch {
    if (usersCache.value === null) usersCache.value = []
    if (charsCache.value === null) charsCache.value = []
  } finally {
    cacheLoading.value = false
  }
}

const filteredRows = computed(() => {
  const s = q.value.trim().toLowerCase()
  const rows = []

  const navFiltered = !s
    ? NAV.map((x) => ({
        type: 'nav',
        key: `nav:${x.to}`,
        to: x.to,
        path: x.to,
        label: x.label,
        ion: x.ion,
      }))
    : NAV.filter(
        (x) =>
          x.label.toLowerCase().includes(s) ||
          x.to.toLowerCase().includes(s),
      ).map((x) => ({
        type: 'nav',
        key: `nav:${x.to}`,
        to: x.to,
        path: x.to,
        label: x.label,
        ion: x.ion,
      }))

  navFiltered.forEach((x) => rows.push(x))

  if (!s) {
    return rows
  }

  const users = usersCache.value ?? []
  const chars = charsCache.value ?? []

  const userMatches = users
    .filter((u) => (u.username || '').toLowerCase().includes(s))
    .slice(0, 8)
  const charMatches = chars
    .filter(
      (c) =>
        (c.name || '').toLowerCase().includes(s) ||
        (c.id || '').toLowerCase().includes(s) ||
        (c.owner || '').toLowerCase().includes(s),
    )
    .slice(0, 8)

  if (userMatches.length) {
    rows.push({ type: 'group', key: 'g:users', label: '用户' })
    userMatches.forEach((u) => {
      rows.push({
        type: 'user',
        key: `user:${u.username}`,
        ion: 'person-outline',
        label: u.username,
        sub: userSub(u),
        username: u.username,
      })
    })
  }

  if (charMatches.length) {
    rows.push({ type: 'group', key: 'g:chars', label: '角色' })
    charMatches.forEach((c) => {
      rows.push({
        type: 'character',
        key: `char:${c.id}`,
        ion: 'planet-outline',
        label: c.name || c.id,
        sub: c.owner ? `拥有者 ${c.owner}` : c.id,
        id: c.id,
      })
    })
  }

  return rows
})

/** 无列表行时的提示：加载索引 vs 真无匹配 */
const emptyMessage = computed(() => {
  if (filteredRows.value.length > 0) return null
  const hasQ = q.value.trim().length > 0
  if (hasQ && cacheLoading.value && usersCache.value === null) return 'loading'
  if (hasQ) return 'empty'
  return null
})

function isSelectable(item) {
  return item && item.type !== 'group'
}

function firstSelectableIndex() {
  const rows = filteredRows.value
  for (let i = 0; i < rows.length; i++) {
    if (isSelectable(rows[i])) return i
  }
  return 0
}

watch(
  () => props.modelValue,
  async (v) => {
    if (v) {
      q.value = ''
      active.value = 0
      ensureCache()
      await nextTick()
      inputRef.value?.focus()
    }
  },
)

watch(filteredRows, () => {
  const rows = filteredRows.value
  if (!rows.length) {
    active.value = 0
    return
  }
  if (!isSelectable(rows[active.value])) {
    active.value = firstSelectableIndex()
    return
  }
  if (active.value >= rows.length) active.value = firstSelectableIndex()
})

watch(q, () => {
  active.value = firstSelectableIndex()
})

function close() {
  open.value = false
}

const { onBackdropMouseDown, onBackdropClickSelf } = useModalBackdropDismiss(close)

function clearQuery() {
  q.value = ''
  nextTick(() => inputRef.value?.focus())
}

function move(d) {
  const rows = filteredRows.value
  const n = rows.length
  if (!n) return
  let i = active.value
  for (let step = 0; step < n; step++) {
    i = (i + d + n) % n
    if (isSelectable(rows[i])) {
      active.value = i
      return
    }
  }
}

function goActive() {
  const rows = filteredRows.value
  const item = rows[active.value]
  if (item && isSelectable(item)) pick(item)
}

function pick(item) {
  if (!item || item.type === 'group') return
  if (item.type === 'nav') {
    router.push(item.to)
  } else if (item.type === 'user') {
    router.push({ path: '/admin/users', query: { highlight: item.username } })
  } else if (item.type === 'character') {
    router.push({ path: '/admin/characters', query: { highlight: item.id } })
  }
  close()
}

defineExpose({ open: () => { open.value = true } })
</script>

<style scoped>
.cmd-mask {
  position: fixed;
  inset: 0;
  z-index: 9997;
  background: rgba(15, 23, 42, 0.65);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  padding-left: 1rem;
  padding-right: 1rem;
}
.cmd-box {
  width: min(520px, 100%);
  padding: 0;
  margin: 0;
  overflow: hidden;
}
.cmd-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--stroke, #334155);
}
.cmd-ion {
  font-size: 1.25rem;
  color: var(--accent-mid, #bbb0ea);
}
.cmd-clear {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.15rem;
  margin: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--accent-mid, #bbb0ea);
}
.cmd-clear:hover {
  color: var(--accent-to, #4ebfcf);
}
.cmd-clear-ion {
  font-size: 1.25rem;
  pointer-events: none;
}
.cmd-input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text, #e2e8f0);
  font-size: 0.95rem;
  outline: none;
}
.cmd-list {
  list-style: none;
  margin: 0;
  padding: 0.35rem;
  max-height: 320px;
  overflow-y: auto;
}
.cmd-group-label {
  list-style: none;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-dim, #64748b);
  padding: 0.4rem 0.85rem 0.15rem;
  user-select: none;
  pointer-events: none;
}
.cmd-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.65rem;
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
  font-size: 0.875rem;
}
.cmd-item:hover,
.cmd-item.active {
  background: var(--surface-hover, rgba(51, 65, 85, 0.5));
}
.cmd-item-ion {
  font-size: 1.1rem;
  color: var(--accent-mid, #bbb0ea);
  flex-shrink: 0;
}
.cmd-label {
  flex: 1;
  min-width: 0;
}
.cmd-path {
  font-size: 0.72rem;
  flex-shrink: 0;
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-sub {
  font-size: 0.72rem;
  flex-shrink: 0;
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-empty {
  padding: 1rem;
  text-align: center;
  font-size: 0.85rem;
}
.cmd-hint {
  margin: 0;
  padding: 0.4rem 0.85rem 0.65rem;
  font-size: 0.72rem;
  border-top: 1px solid var(--stroke, #334155);
}
</style>

<template>
  <div class="section-root">
    <p class="card muted">
      勾选允许在
      <strong>官网 /app 网页聊天</strong>
      中出现的角色。保存后写入服务器 <code>data/web_chars.json</code>。
      <strong>已启用</strong>角色的上下顺序即为官网展示顺序；拖动左侧 <span class="hint-handle">⠿</span> 可调整顺序。
    </p>
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <input
          v-model="searchQuery"
          type="search"
          class="search-inp"
          placeholder="搜索角色名或所有者…"
          @input="onSearchInput"
        />
        <span class="toolbar-stats muted">已启用 {{ enabledCount }} / 共 {{ list.length }}</span>
        <button
          v-if="sortKey !== 'webOrder'"
          type="button"
          class="btn btn-sm"
          title="恢复为：已启用优先且顺序与拖拽一致"
          @click="resetWebOrderSort"
        >
          恢复展示顺序
        </button>
        <span class="toolbar-spacer" />
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存网页可见列表' }}
        </button>
        <button type="button" class="btn" @click="load">刷新</button>
      </div>
      <div ref="tableViewportRef" class="table-wrap table-viewport">
        <table class="webchar-table admin-data-table">
          <thead>
            <tr>
              <th class="th-drag" />
              <th class="th-on th-sortable" @click="toggleSort('on')">展示 {{ sortIcon('on') }}</th>
              <th class="th-avatar">头像</th>
              <th :style="thStyle('name')" class="col-name th-sortable th-resizable" @click="toggleSort('name')">
                角色名 {{ sortIcon('name') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('name', e)" @click.stop />
              </th>
              <th :style="thStyle('bio')" class="col-bio th-sortable th-resizable" @click="toggleSort('bio')">
                简介 {{ sortIcon('bio') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('bio', e)" @click.stop />
              </th>
              <th :style="thStyle('owner')" class="col-owner th-sortable" @click="toggleSort('owner')">
                所有者 {{ sortIcon('owner') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in pagedItems"
              :key="c.id"
              :class="{ 'row-enabled': isEnabled(c.id) }"
              @dragover.prevent="isEnabled(c.id) ? onDragOver($event) : undefined"
              @drop.prevent="isEnabled(c.id) ? onDrop($event, c.id) : undefined"
            >
              <td class="td-drag">
                <span
                  v-if="isEnabled(c.id)"
                  class="drag-handle"
                  draggable="true"
                  title="拖动调整展示顺序"
                  @dragstart="onDragStart($event, c.id)"
                  @dragend="dragSourceId = null"
                >
                  ⠿
                </span>
              </td>
              <td>
                <PonyCheckbox
                  :checked="isEnabled(c.id)"
                  @change="(checked) => toggle(c.id, checked)"
                />
              </td>
              <td class="td-avatar">
                <img
                  v-if="c.avatar && !avatarFailed[c.id]"
                  :src="avatarUrl(c.avatar)"
                  alt=""
                  class="avatar-img"
                  @error="avatarFailed[c.id] = true"
                />
                <span v-else class="avatar-ph">{{ (c.name || '?')[0] }}</span>
              </td>
              <td class="col-name">{{ c.name || '—' }}</td>
              <td class="bio-cell col-bio">
                <span :title="c.bio || ''">{{ bioPreview(c.bio) }}</span>
              </td>
              <td class="col-owner">{{ c.owner || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AdminPager
        :page="page"
        :total-pages="totalPages"
        :total="total"
        :page-size="pageSize"
        @prev="prev"
        @next="next"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { fetchAdminCharacters, fetchWebCharacterIds, saveWebCharacterIds } from '../../../api/admin'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { useAdminTableSort, cmpLocale, cmpNum } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import AdminPager from '../../../components/admin/AdminPager.vue'
import PonyCheckbox from '../../../components/PonyCheckbox.vue'
import '../../../styles/admin-shell.css'

const list = ref([])
/** @type {import('vue').Ref<string[]>} 已启用 ID 顺序（与官网展示顺序一致） */
const selectedIds = ref([])
const error = ref('')
const saving = ref(false)
const searchQuery = ref('')
const dragSourceId = ref(null)
const avatarFailed = reactive({})

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('webOrder', 'asc')

const { startResize, thStyle } = useColResize(
  { name: null, bio: null, owner: 110 },
  { min: 56, columnOrder: [null, null, null, 'name', 'bio', 'owner'] },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 52,
  headHeight: 48,
  minRows: 4,
  maxRows: 200,
  slackPx: 20,
})

function searchFilteredChars() {
  const q = searchQuery.value.trim().toLowerCase()
  const match = (c) => {
    if (!q) return true
    const name = (c.name || '').toLowerCase()
    const owner = (c.owner || '').toLowerCase()
    return name.includes(q) || owner.includes(q)
  }
  return list.value.filter(match)
}

/** 已启用优先 + 拖拽顺序 + 未启用按名称 */
function buildWebOrderList(filtered) {
  const byId = Object.fromEntries(filtered.map((c) => [c.id, c]))
  const enabledRows = selectedIds.value.filter((id) => byId[id]).map((id) => byId[id])
  const sel = new Set(selectedIds.value)
  const rest = filtered
    .filter((c) => !sel.has(c.id))
    .sort((a, b) => (a.name || '').localeCompare(b.name || '', 'zh-CN'))
  return [...enabledRows, ...rest]
}

const paginationSource = computed(() => {
  const filtered = searchFilteredChars()
  if (sortKey.value === 'webOrder') {
    return buildWebOrderList(filtered)
  }
  const arr = filtered.slice()
  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'on') {
      const va = selectedIds.value.includes(a.id) ? 1 : 0
      const vb = selectedIds.value.includes(b.id) ? 1 : 0
      return cmpNum(vb, va, dir)
    }
    if (sk === 'name') return cmpLocale(a.name, b.name, dir)
    if (sk === 'bio') return cmpLocale(a.bio, b.bio, dir)
    if (sk === 'owner') return cmpLocale(a.owner, b.owner, dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } = useAdminPagination(
  paginationSource,
  viewportRows,
)

watch([sortKey, sortDir], () => {
  resetPage()
})

function resetWebOrderSort() {
  sortKey.value = 'webOrder'
  sortDir.value = 'asc'
  resetPage()
}

const enabledCount = computed(() => selectedIds.value.length)

function isEnabled(id) {
  return selectedIds.value.includes(id)
}

function onSearchInput() {
  resetPage()
}

function avatarUrl(avatar) {
  if (!avatar || typeof avatar !== 'string') return ''
  const a = avatar.trim()
  if (a.startsWith('http') || a.startsWith('data:')) return a
  if (a.startsWith('/')) return a
  return `/${a.replace(/^\/+/, '')}`
}

function bioPreview(bio) {
  if (!bio || typeof bio !== 'string') return '—'
  const t = bio.trim()
  if (t.length <= 48) return t
  return `${t.slice(0, 48)}…`
}

function toggle(id, on) {
  const s = [...selectedIds.value]
  const ix = s.indexOf(id)
  if (on) {
    if (ix < 0) s.push(id)
  } else if (ix >= 0) {
    s.splice(ix, 1)
  }
  selectedIds.value = s
}

function onDragStart(e, id) {
  if (!isEnabled(id)) {
    e.preventDefault()
    return
  }
  dragSourceId.value = id
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', id)
}

function onDragOver(e) {
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onDrop(e, targetId) {
  const sourceId = dragSourceId.value || e.dataTransfer?.getData('text/plain')
  dragSourceId.value = null
  if (!sourceId || sourceId === targetId) return
  if (!isEnabled(sourceId) || !isEnabled(targetId)) return
  reorderSelected(sourceId, targetId)
}

function reorderSelected(sourceId, targetId) {
  const arr = [...selectedIds.value]
  const si = arr.indexOf(sourceId)
  const ti = arr.indexOf(targetId)
  if (si < 0 || ti < 0) return
  arr.splice(si, 1)
  const tiNew = arr.indexOf(targetId)
  arr.splice(tiNew, 0, sourceId)
  selectedIds.value = arr
}

async function load() {
  error.value = ''
  try {
    const [chars, web] = await Promise.all([fetchAdminCharacters(), fetchWebCharacterIds()])
    list.value = Array.isArray(chars) ? chars : []
    const ids = web.character_ids || []
    selectedIds.value = [...ids]
    resetPage()
    Object.keys(avatarFailed).forEach((k) => delete avatarFailed[k])
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    await saveWebCharacterIds([...selectedIds.value])
    await load()
    try {
      window.dispatchEvent(new CustomEvent('ponychat-admin-webchars-updated'))
    } catch {
      /* 忽略 */
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.section-root {
  min-height: 0;
}
.card-fill {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.search-inp {
  min-width: 200px;
  max-width: 320px;
  flex: 1;
}
.toolbar-stats {
  font-size: 0.8rem;
  white-space: nowrap;
}
.toolbar-spacer {
  flex: 1;
  min-width: 0;
}
.hint-handle {
  font-weight: 700;
  color: var(--accent-mid, #bbb0ea);
}
.th-drag {
  width: 2rem;
}
.th-on {
  width: 3rem;
}
.th-avatar {
  width: 3.5rem;
}
.col-bio {
  min-width: 0;
}
.td-drag {
  text-align: center;
  vertical-align: middle;
}
.drag-handle {
  cursor: grab;
  user-select: none;
  color: var(--text-muted);
  font-size: 1rem;
  line-height: 1;
  padding: 0.2rem;
}
.drag-handle:active {
  cursor: grabbing;
}
.row-enabled {
  box-shadow: inset 3px 0 0 0 rgba(117, 73, 212, 0.65);
  background: rgba(117, 73, 212, 0.06);
}
.td-avatar {
  width: 3.5rem;
}
.avatar-img {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  vertical-align: middle;
  border: 1px solid var(--stroke);
}
.avatar-ph {
  display: inline-flex;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  background: var(--bg-deep);
  border: 1px solid var(--stroke);
  color: var(--text-muted);
}
.bio-cell {
  font-size: 0.78rem;
  color: var(--text-muted);
  word-break: break-word;
}
</style>

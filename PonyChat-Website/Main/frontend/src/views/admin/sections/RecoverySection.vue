<template>
  <div class="recovery section-root section-scrollable">
    <p v-if="error" class="card card--error">{{ error }}</p>

    <template v-else>
      <div class="recovery-summary">
        <div class="summary-item">
          <div class="summary-value">{{ filtered.length }}</div>
          <div class="summary-label">当前匹配</div>
        </div>
        <div class="summary-item">
          <div class="summary-value">{{ stats.hidden }}</div>
          <div class="summary-label">隐藏对话</div>
        </div>
        <div class="summary-item">
          <div class="summary-value">{{ stats.deletedMessages }}</div>
          <div class="summary-label">可恢复消息</div>
        </div>
        <div class="summary-item">
          <div class="summary-value">{{ stats.totalMessages }}</div>
          <div class="summary-label">涉及消息</div>
        </div>
      </div>

      <div class="card recovery-workbench">
        <div class="toolbar">
          <div class="toolbar-left">
            <span class="muted">从隐藏/软删除状态中恢复对话，恢复前先看用户、角色、时间和消息预览。</span>
          </div>
          <div class="toolbar-right">
            <input v-model="search" class="search-input" placeholder="搜索标题 / 用户 / 角色 / 内容 / ID…" />
            <label class="toggle-line">
              <input v-model="onlyHidden" type="checkbox" @change="load" />
              <span>仅隐藏</span>
            </label>
            <button type="button" class="btn" @click="load">刷新</button>
          </div>
        </div>

        <div class="recovery-layout">
          <div class="list-pane">
            <div ref="tableViewportRef" class="table-wrap table-viewport">
              <table class="recovery-table admin-data-table">
                <thead>
                  <tr>
                    <th :style="thStyle('title')" class="col-title th-sortable th-resizable" @click="toggleSort('title')">
                      对话 {{ sortIcon('title') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('title', e)" @click.stop />
                    </th>
                    <th :style="thStyle('user')" class="col-user th-sortable th-resizable" @click="toggleSort('user')">
                      用户 {{ sortIcon('user') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('user', e)" @click.stop />
                    </th>
                    <th :style="thStyle('char')" class="col-char th-sortable th-resizable" @click="toggleSort('char')">
                      角色 {{ sortIcon('char') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('char', e)" @click.stop />
                    </th>
                    <th :style="thStyle('n')" class="col-n th-sortable th-resizable" @click="toggleSort('n')">
                      消息 {{ sortIcon('n') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('n', e)" @click.stop />
                    </th>
                    <th :style="thStyle('prev')" class="col-prev th-sortable th-resizable" @click="toggleSort('prev')">
                      最近内容 {{ sortIcon('prev') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('prev', e)" @click.stop />
                    </th>
                    <th :style="thStyle('time')" class="col-time th-sortable th-resizable" @click="toggleSort('time')">
                      删除/更新时间 {{ sortIcon('time') }}
                      <span class="col-resizer" @mousedown.stop="(e) => startResize('time', e)" @click.stop />
                    </th>
                    <th :style="thStyle('op')" class="col-op">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="c in pagedItems"
                    :key="c.conversation_id"
                    class="recover-row"
                    :class="{ selected: selectedId === c.conversation_id }"
                    @click="selectConversation(c)"
                  >
                    <td class="col-title">
                      <div class="title-line">
                        <span class="status-dot" :class="{ hot: c.is_hidden }" />
                        <span class="t">{{ c.title || '未命名对话' }}</span>
                      </div>
                      <div class="muted tiny mono">{{ c.conversation_id }}</div>
                    </td>
                    <td class="col-user">{{ c.username || '—' }}</td>
                    <td class="col-char">{{ c.character_name || c.character_id || '—' }}</td>
                    <td class="col-n">
                      <strong>{{ c.total_message_count ?? 0 }}</strong>
                      <span v-if="c.deleted_message_count" class="danger-text">+{{ c.deleted_message_count }}</span>
                    </td>
                    <td class="col-prev">
                      <div class="ellipsis" :title="previewText(c)">{{ previewText(c) || '—' }}</div>
                      <div v-if="c.hidden_reason" class="muted tiny">{{ reasonLabel(c.hidden_reason) }}</div>
                    </td>
                    <td class="col-time nowrap">{{ fmtDt(recoveryTime(c)) }}</td>
                    <td class="col-op" @click.stop>
                      <button type="button" class="btn btn-sm" @click="selectConversation(c)">预览</button>
                      <button type="button" class="btn btn-sm btn-primary" @click="restore(c.conversation_id)">恢复</button>
                    </td>
                  </tr>
                  <tr v-if="!pagedItems.length">
                    <td colspan="7" class="empty-cell">没有匹配的可恢复内容</td>
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

          <aside class="detail-pane">
            <div v-if="!selected" class="detail-empty">
              <div class="detail-empty-title">选择一条记录</div>
              <div class="muted">右侧会显示完整归属、恢复原因、最后内容和消息上下文。</div>
            </div>

            <template v-else>
              <div class="detail-head">
                <div>
                  <h3>{{ selected.title || '未命名对话' }}</h3>
                  <p class="muted mono">{{ selected.conversation_id }}</p>
                </div>
                <button type="button" class="btn btn-primary" @click="restore(selected.conversation_id)">恢复对话</button>
              </div>

              <div class="meta-grid">
                <div>
                  <span class="muted">用户</span>
                  <strong>{{ selected.username || '—' }}</strong>
                </div>
                <div>
                  <span class="muted">角色</span>
                  <strong>{{ selected.character_name || selected.character_id || '—' }}</strong>
                </div>
                <div>
                  <span class="muted">隐藏时间</span>
                  <strong>{{ fmtDt(selected.hidden_at || selected.updated_at) }}</strong>
                </div>
                <div>
                  <span class="muted">消息</span>
                  <strong>{{ selected.total_message_count || 0 }} 条</strong>
                </div>
              </div>

              <div class="reason-box">
                <span class="muted">恢复线索</span>
                <strong>{{ reasonLabel(selected.hidden_reason) }}</strong>
                <p>{{ selected.last_deleted_message || selected.last_message || '暂无消息预览' }}</p>
              </div>

              <div class="detail-actions">
                <button type="button" class="btn" @click="copyId(selected.conversation_id)">复制对话 ID</button>
                <button type="button" class="btn" @click="loadDetail(selected.conversation_id)">重新加载详情</button>
              </div>

              <div class="message-head">
                <h4>消息上下文</h4>
                <span v-if="detailLoading" class="muted">加载中…</span>
                <span v-else class="muted">{{ detailMessages.length }} 条</span>
              </div>
              <div class="message-list">
                <div
                  v-for="m in detailMessages"
                  :key="m.message_id || `${m.sequence_number}-${m.timestamp}`"
                  class="msg"
                  :class="{ deleted: isRecoverableMessage(m) }"
                >
                  <div class="msg-top">
                    <span class="role-pill">{{ roleLabel(m.role) }}</span>
                    <span class="muted">#{{ m.sequence_number ?? '—' }}</span>
                    <span class="muted">{{ fmtDt(m.deleted_at || m.hidden_at || m.timestamp) }}</span>
                    <button
                      v-if="isRecoverableMessage(m) && m.message_id"
                      type="button"
                      class="btn btn-xs btn-primary"
                      @click="restoreMessage(selected.conversation_id, m.message_id)"
                    >
                      恢复消息
                    </button>
                  </div>
                  <p>{{ m.content || m.image_url || '空消息' }}</p>
                  <div v-if="m.delete_reason || m.hidden_reason" class="muted tiny">
                    {{ reasonLabel(m.delete_reason || m.hidden_reason) }}
                  </div>
                </div>
              </div>
            </template>
          </aside>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchConversationDetail,
  fetchConversationRecovery,
  restoreConversation,
  restoreConversationMessage,
} from '../../../api/admin'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { useAdminTableSort, cmpLocale, cmpNum, fmtDt } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import '../../../styles/admin-shell.css'

const rows = ref([])
const error = ref('')
const search = ref('')
const onlyHidden = ref(true)
const selectedId = ref('')
const detail = ref(null)
const detailLoading = ref(false)

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('time', 'desc')

const { startResize, thStyle } = useColResize(
  { title: 210, user: 110, char: 130, n: 74, prev: null, time: 132, op: 128 },
  {
    min: 48,
    columnOrder: ['title', 'user', 'char', 'n', 'prev', 'time', 'op'],
    minByKey: { op: 104, n: 64 },
  },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 64,
  headHeight: 48,
  minRows: 4,
  maxRows: 200,
})

const selected = computed(() => rows.value.find((x) => x.conversation_id === selectedId.value) || null)
const detailMessages = computed(() => detail.value?.messages || [])

const stats = computed(() => {
  const base = filtered.value
  return {
    hidden: base.filter((x) => x.is_hidden).length,
    deletedMessages: base.reduce((sum, x) => sum + Number(x.deleted_message_count || 0), 0),
    totalMessages: base.reduce((sum, x) => sum + Number(x.total_message_count || 0), 0),
  }
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let arr = !q
    ? rows.value.slice()
    : rows.value.filter((c) => {
        const hay = [
          c.title,
          c.conversation_id,
          c.username,
          c.character_name,
          c.character_id,
          c.hidden_reason,
          c.last_message,
          c.last_deleted_message,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        return hay.includes(q)
      })

  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'title') return cmpLocale(a.title || a.conversation_id, b.title || b.conversation_id, dir)
    if (sk === 'user') return cmpLocale(a.username, b.username, dir)
    if (sk === 'char') return cmpLocale(a.character_name || a.character_id, b.character_name || b.character_id, dir)
    if (sk === 'n') return cmpNum(a.total_message_count, b.total_message_count, dir)
    if (sk === 'prev') return cmpLocale(previewText(a), previewText(b), dir)
    if (sk === 'time') return cmpNum(timeSort(a), timeSort(b), dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(filtered, viewportRows)

watch([search, sortKey, sortDir], () => {
  resetPage()
})

function timeSort(c) {
  const t = recoveryTime(c)
  if (t == null) return 0
  const n = Number(t)
  if (Number.isFinite(n)) return n > 1e12 ? n : n * 1000
  const d = Date.parse(String(t))
  return Number.isFinite(d) ? d : 0
}

function recoveryTime(c) {
  return c.hidden_at || c.last_message_at || c.updated_at || c.timestamp
}

function previewText(c) {
  return c.last_deleted_message || c.last_message || ''
}

function reasonLabel(reason) {
  const r = String(reason || '').trim()
  if (!r) return '无记录原因'
  const map = {
    admin_restore_conversation: '管理员恢复对话',
    admin_restore_message: '管理员恢复消息',
    admin_hard_delete_conversation: '管理员硬删除对话',
    admin_hard_delete_message: '管理员硬删除消息',
    admin_hide_from_user_list: '管理员从用户列表隐藏',
    merged_by_admin: '管理员合并后隐藏旧对话',
  }
  return map[r] || r
}

function roleLabel(role) {
  if (role === 'assistant') return '角色'
  if (role === 'user') return '用户'
  if (role === 'system') return '系统'
  return role || '未知'
}

function isRecoverableMessage(m) {
  return Boolean(m?.is_deleted || m?.is_hidden || m?.deleted_at || m?.hidden_at)
}

async function load() {
  error.value = ''
  try {
    const data = await fetchConversationRecovery(onlyHidden.value)
    rows.value = data.items || data.conversations || (Array.isArray(data) ? data : [])
    if (!rows.value.some((x) => x.conversation_id === selectedId.value)) {
      selectedId.value = rows.value[0]?.conversation_id || ''
      detail.value = null
      if (selectedId.value) await loadDetail(selectedId.value)
    }
    resetPage()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function selectConversation(c) {
  selectedId.value = c.conversation_id
  await loadDetail(c.conversation_id)
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  try {
    detail.value = await fetchConversationDetail(id)
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    detailLoading.value = false
  }
}

async function restore(id) {
  const row = rows.value.find((x) => x.conversation_id === id)
  const name = row?.title || id
  const ok = await confirmAsync({
    title: '恢复对话',
    message: `恢复「${name}」并重新显示到用户对话列表？`,
  })
  if (!ok) return
  try {
    await restoreConversation(id)
    toast.success('对话已恢复')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function restoreMessage(conversationId, messageId) {
  try {
    await restoreConversationMessage(conversationId, messageId)
    toast.success('消息已恢复')
    await loadDetail(conversationId)
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function copyId(id) {
  try {
    await navigator.clipboard.writeText(id)
    toast.success('已复制')
  } catch {
    toast.error('复制失败')
  }
}

onMounted(load)
</script>

<style scoped>
.section-root {
  min-height: 0;
}
:global(.admin-shell .content.content-scroll > .recovery.section-root.section-scrollable) {
  overflow: hidden;
}
.recovery-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.75rem;
  margin-bottom: 0.9rem;
  flex-shrink: 0;
}
.summary-item {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.34);
  border-radius: 8px;
  padding: 0.85rem 1rem;
}
.summary-value {
  font-size: 1.45rem;
  font-weight: 700;
  line-height: 1.2;
}
.summary-label {
  color: var(--text-muted, #94a3b8);
  font-size: 0.78rem;
  margin-top: 0.2rem;
}
.recovery-workbench {
  flex: 1;
  min-height: 0;
  margin-bottom: 0;
  display: flex;
  flex-direction: column;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
}
.toolbar-left {
  min-width: 220px;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.search-input {
  width: min(360px, 36vw);
  padding: 0.35rem 0.65rem;
}
.toggle-line {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.82rem;
  white-space: nowrap;
}
.recovery-layout {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 28vw);
  gap: 0.9rem;
  min-height: 0;
}
.list-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.detail-pane {
  min-height: 0;
  height: 100%;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.24);
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
}
.recover-row {
  cursor: pointer;
}
.recover-row.selected {
  background: rgba(124, 92, 255, 0.12);
}
.title-line {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}
.status-dot {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: #42c49a;
  flex: 0 0 auto;
}
.status-dot.hot {
  background: #d9a441;
}
.t {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tiny {
  font-size: 0.7rem;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.col-title,
.col-prev {
  min-width: 0;
}
.col-n {
  white-space: nowrap;
}
.col-op {
  min-width: 104px;
  white-space: nowrap;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8rem;
}
.nowrap {
  white-space: nowrap;
  font-size: 0.78rem;
}
.danger-text {
  color: #e58a8a;
  margin-left: 0.25rem;
  font-size: 0.75rem;
}
.btn-sm {
  padding: 0.25rem 0.42rem;
  font-size: 0.74rem;
}
.btn-xs {
  padding: 0.16rem 0.34rem;
  font-size: 0.68rem;
}
.empty-cell {
  text-align: center;
  color: var(--text-muted, #94a3b8);
  padding: 2rem 0;
}
.detail-empty {
  flex: 1;
  min-height: 0;
  display: grid;
  align-content: center;
  gap: 0.35rem;
  text-align: center;
}
.detail-empty-title {
  font-weight: 700;
  font-size: 1rem;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.detail-head h3 {
  margin: 0;
  font-size: 1rem;
}
.detail-head p {
  margin: 0.25rem 0 0;
  font-size: 0.7rem;
  word-break: break-all;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
  margin-bottom: 0.75rem;
}
.meta-grid > div,
.reason-box {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  padding: 0.58rem 0.65rem;
  background: rgba(2, 6, 23, 0.18);
}
.meta-grid span,
.reason-box span {
  display: block;
  font-size: 0.7rem;
  margin-bottom: 0.18rem;
}
.meta-grid strong,
.reason-box strong {
  font-size: 0.82rem;
}
.reason-box p {
  margin: 0.45rem 0 0;
  color: var(--text-muted, #94a3b8);
  font-size: 0.8rem;
  line-height: 1.55;
}
.detail-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin: 0.75rem 0;
}
.message-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 0.9rem 0 0.5rem;
  flex-shrink: 0;
}
.message-head h4 {
  margin: 0;
  font-size: 0.9rem;
}
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 0.2rem;
  display: grid;
  align-content: start;
  gap: 0.55rem;
}
.msg {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  padding: 0.65rem;
  background: rgba(15, 23, 42, 0.34);
}
.msg.deleted {
  border-color: rgba(229, 138, 138, 0.38);
  background: rgba(127, 29, 29, 0.14);
}
.msg-top {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.role-pill {
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 999px;
  padding: 0.1rem 0.42rem;
  font-size: 0.68rem;
  color: #dbeafe;
}
.msg p {
  margin: 0;
  line-height: 1.55;
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
}
@media (max-width: 1180px) {
  :global(.admin-shell .content.content-scroll > .recovery.section-root.section-scrollable) {
    overflow-y: auto;
  }
  .recovery-workbench {
    flex: 0 0 auto;
  }
  .recovery-layout {
    grid-template-columns: 1fr;
  }
  .detail-pane {
    height: auto;
    max-height: none;
    overflow: visible;
  }
  .message-list {
    overflow: visible;
  }
}
@media (max-width: 760px) {
  .recovery-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .toolbar-right {
    justify-content: flex-start;
  }
  .search-input {
    width: 100%;
  }
}
</style>

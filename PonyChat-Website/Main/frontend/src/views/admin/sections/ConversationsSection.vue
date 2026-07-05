<template>
  <div class="section-root">
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <span class="muted">共 {{ filtered.length }} 条对话</span>
        <div class="toolbar-right">
          <input v-model="search" class="search-input" placeholder="搜索模式 / 用户 / 角色 / 标题…" />
        </div>
      </div>

      <div class="conversations-workbench">
        <div class="list-pane">
          <div ref="tableViewportRef" class="table-wrap table-viewport">
            <table class="conv-table admin-data-table">
              <thead>
                <tr>
                  <th :style="thStyle('mode')" class="col-mode th-sortable th-resizable" @click="toggleSort('mode')">
                    模式 {{ sortIcon('mode') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('mode', e)" @click.stop />
                  </th>
                  <th :style="thStyle('title')" class="col-title th-sortable th-resizable" @click="toggleSort('title')">
                    标题 / ID {{ sortIcon('title') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('title', e)" @click.stop />
                  </th>
                  <th :style="thStyle('updated')" class="col-updated th-sortable th-resizable" @click="toggleSort('updated')">
                    更新时间 {{ sortIcon('updated') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('updated', e)" @click.stop />
                  </th>
                  <th :style="thStyle('created')" class="col-created th-sortable th-resizable" @click="toggleSort('created')">
                    创建时间 {{ sortIcon('created') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('created', e)" @click.stop />
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
                    消息数 {{ sortIcon('n') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('n', e)" @click.stop />
                  </th>
                  <th :style="thStyle('visible')" class="col-visible th-sortable th-resizable" @click="toggleSort('visible')">
                    用户可见 {{ sortIcon('visible') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('visible', e)" @click.stop />
                  </th>
                  <th :style="thStyle('prev')" class="col-prev th-sortable th-resizable" @click="toggleSort('prev')">
                    最后消息 {{ sortIcon('prev') }}
                    <span class="col-resizer" @mousedown.stop="(e) => startResize('prev', e)" @click.stop />
                  </th>
                  <th :style="thStyle('op')" class="col-op">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="c in pagedItems"
                  :key="c.id"
                  class="conv-row"
                  :class="{ selected: selectedId === c.id }"
                  @click="selectConversation(c)"
                >
                  <td class="col-mode">
                    <span class="mode-badge" :class="modeClass(c)">{{ modeLabel(c) }}</span>
                  </td>
                  <td class="col-title">
                    <div class="t">{{ c.title || c.id }}</div>
                    <div class="muted tiny mono">{{ c.id }}</div>
                  </td>
                  <td class="col-updated nowrap">{{ fmtDt(c.updated_at || c.timestamp) }}</td>
                  <td class="col-created nowrap">{{ fmtDt(c.created_at || c.timestamp) }}</td>
                  <td class="col-user">{{ c.user || c.username || '—' }}</td>
                  <td class="col-char">{{ c.character || c.character_name || c.character_id || '—' }}</td>
                  <td class="col-n">{{ c.messages ?? '—' }}</td>
                  <td class="col-visible">
                    <span :class="isUserVisible(c) ? 'badge-on' : 'badge-off'">
                      {{ isUserVisible(c) ? '是' : '否' }}
                    </span>
                  </td>
                  <td class="col-prev ellipsis" :title="c.last_message">{{ c.last_message || '—' }}</td>
                  <td class="col-op" @click.stop>
                    <button type="button" class="btn btn-sm btn-danger" :disabled="resettingId === c.id" @click="resetConversationRow(c)">
                      {{ resettingId === c.id ? '重置中' : '重置' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="!pagedItems.length">
                  <td colspan="10" class="empty-cell">没有匹配的对话</td>
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

        <aside class="preview-pane">
          <div class="phone-preview">
            <div class="phone-head">
              <div class="avatar">
                <img
                  v-if="phoneAvatarSrc && !phoneAvatarFailed"
                  :src="phoneAvatarSrc"
                  alt=""
                  @error="phoneAvatarFailed = true"
                />
                <span v-else>{{ firstChar(selectedDetail?.character || selectedRow?.character || selectedRow?.character_name) }}</span>
              </div>
              <div class="phone-meta">
                <strong>{{ selectedDetail?.character || selectedRow?.character || selectedRow?.character_name || '未选择对话' }}</strong>
                <span>{{ selectedSummary || selectedDetail?.user || selectedRow?.user || selectedRow?.username || '请选择左侧对话' }}</span>
                <span v-if="selectedId" class="phone-mode-pill" :class="modeClass(selectedDetail || selectedRow)">
                  {{ selectedModeLabel }}
                </span>
              </div>
              <button
                type="button"
                class="btn btn-sm btn-danger phone-action"
                :disabled="!canSoftDeleteSelected || softDeleting"
                @click="softDeleteSelected"
              >
                {{ softDeleting ? '处理中' : '软删除' }}
              </button>
            </div>

            <div v-if="selectedId" class="selection-bar">
              <div class="date-picker-wrap">
                <button type="button" class="date-input-btn" @click="toggleDatePicker('start')">
                  <span>{{ formatRangeDate(rangeStart) || '开始日期' }}</span>
                  <span class="calendar-icon">▦</span>
                </button>
                <div v-if="openDatePicker === 'start'" class="pony-calendar" @click.stop>
                  <div class="calendar-head">
                    <button type="button" class="icon-btn" @click="shiftCalendarMonth(-1)">‹</button>
                    <strong>{{ calendarTitle }}</strong>
                    <button type="button" class="icon-btn" @click="shiftCalendarMonth(1)">›</button>
                  </div>
                  <div class="calendar-week">
                    <span v-for="d in calendarWeekdays" :key="d">{{ d }}</span>
                  </div>
                  <div class="calendar-grid">
                    <button
                      v-for="day in calendarDays"
                      :key="day.key"
                      type="button"
                      class="calendar-day"
                      :class="{ muted: !day.inMonth, selected: day.value === rangeStart, inRange: isDateInSelectedRange(day.value) }"
                      @click="pickDate('start', day.value)"
                    >
                      {{ day.day }}
                    </button>
                  </div>
                </div>
              </div>
              <div class="date-picker-wrap">
                <button type="button" class="date-input-btn" @click="toggleDatePicker('end')">
                  <span>{{ formatRangeDate(rangeEnd) || '结束日期' }}</span>
                  <span class="calendar-icon">▦</span>
                </button>
                <div v-if="openDatePicker === 'end'" class="pony-calendar calendar-right" @click.stop>
                  <div class="calendar-head">
                    <button type="button" class="icon-btn" @click="shiftCalendarMonth(-1)">‹</button>
                    <strong>{{ calendarTitle }}</strong>
                    <button type="button" class="icon-btn" @click="shiftCalendarMonth(1)">›</button>
                  </div>
                  <div class="calendar-week">
                    <span v-for="d in calendarWeekdays" :key="d">{{ d }}</span>
                  </div>
                  <div class="calendar-grid">
                    <button
                      v-for="day in calendarDays"
                      :key="day.key"
                      type="button"
                      class="calendar-day"
                      :class="{ muted: !day.inMonth, selected: day.value === rangeEnd, inRange: isDateInSelectedRange(day.value) }"
                      @click="pickDate('end', day.value)"
                    >
                      {{ day.day }}
                    </button>
                  </div>
                </div>
              </div>
              <button type="button" class="btn btn-sm" @click="selectByTimeRange">选时间段</button>
              <button type="button" class="btn btn-sm" :disabled="!selectableMessages.length" @click="selectAdjacentMessage(-1)">上一条</button>
              <button type="button" class="btn btn-sm" :disabled="!selectableMessages.length" @click="selectAdjacentMessage(1)">下一条</button>
              <button type="button" class="btn btn-sm" :disabled="!selectedMessages.length" @click="copySelectedMessageIds">复制ID</button>
              <button type="button" class="btn btn-sm" :disabled="!selectedMessages.length" @click="clearSelectedMessages">清除</button>
            </div>

            <div v-if="isGalgameSelected" class="game-state-strip">
              <span class="game-state-chip">{{ selectedModeLabel }}</span>
              <span v-if="selectedGameStatus" class="game-state-chip">状态 {{ selectedGameStatus }}</span>
              <span v-if="selectedGameScore !== ''" class="game-state-chip">分数 {{ selectedGameScore }}</span>
              <span v-for="item in lockStateItems(selectedDetail)" :key="item.label" class="game-state-chip">{{ item.label }} {{ item.value }}</span>
            </div>

            <div ref="previewMessagesRef" class="phone-messages" @scroll="handlePreviewScroll" @click="handlePreviewBlankClick">
              <div v-if="detailLoading" class="preview-state">
                <span class="spin" />
                <span>加载中…</span>
              </div>
              <div v-else-if="detailError" class="preview-state error-text">{{ detailError }}</div>
              <div v-else-if="!selectedId" class="preview-state">选择一条对话后开始预览</div>
              <div v-else-if="!visibleDetailMessages.length" class="preview-state">暂无消息</div>
              <div v-else-if="detailPaging.loadingOlder" class="load-more-state">
                <span class="spin" />
                <span>加载更早消息…</span>
              </div>

              <div
                v-for="m in visibleDetailMessages"
                :key="m.message_id || `${m.sequence_number}-${m.timestamp}`"
                :data-message-key="messageKey(m)"
                class="message-row"
                :class="[messageSide(m), { selected: isSelectedMessage(m) }]"
              >
                <div class="message-bubble" :class="messageBubbleClass(m)" @click.stop="toggleMessageSelection(m)">
                  <img v-if="m.image_url" class="message-image" :src="m.image_url" alt="" />
                  <template v-if="isGalgameAssistantMessage(m)">
                    <div v-if="galgameScene(m)" class="galgame-scene">
                      <div v-if="galTags(galgameScene(m)).length" class="gal-tags">
                        <span
                          v-for="tag in galTags(galgameScene(m))"
                          :key="`${messageKey(m)}-${tag.label}`"
                          class="gal-tag"
                          :class="tag.type"
                        >
                          <b>{{ tag.label }}</b>{{ tag.value }}
                        </span>
                      </div>
                      <div v-if="galgameScene(m).score_delta_reason" class="gal-score-reason">
                        <span v-html="markdownTextHtml(galgameScene(m).score_delta_reason)" />
                      </div>
                      <section v-for="block in galSceneBlocks(galgameScene(m))" :key="block.key" class="gal-section" :class="block.key">
                        <span class="gal-section-title">{{ block.title }}</span>
                        <p v-html="markdownTextHtml(block.text)" />
                      </section>
                      <p v-if="galgameScene(m).dialogue" class="gal-dialogue" v-html="markdownTextHtml(galgameScene(m).dialogue)" />
                      <p v-else-if="galgameScene(m).text" class="gal-dialogue" v-html="markdownTextHtml(galgameScene(m).text)" />
                      <section v-for="block in galSceneStateBlocks(galgameScene(m))" :key="block.key" class="gal-section gal-state">
                        <span class="gal-section-title">{{ block.title }}</span>
                        <p v-html="markdownTextHtml(block.text)" />
                      </section>
                    </div>
                    <p v-else-if="plainMessageText(m)" v-html="markdownTextHtml(plainMessageText(m))" />
                    <p v-else-if="!m.image_url" class="empty-message">空消息</p>
                    <div v-if="galgameOptions(m).length" class="gal-options">
                      <span v-for="option in galgameOptions(m)" :key="`${messageKey(m)}-${option.label}`" class="gal-option">
                        {{ option.label }}
                      </span>
                    </div>
                  </template>
                  <template v-else>
                    <p v-if="m.content">{{ m.content }}</p>
                    <p v-else-if="!m.image_url" class="empty-message">空消息</p>
                  </template>
                  <div class="message-foot">
                    <span class="message-sender">{{ messageSenderName(m) }}</span>
                    <span class="message-time">{{ formatMessageTime(m.timestamp) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  fetchConversationDetail,
  fetchConversations,
  resetConversation as resetAdminConversation,
  softDeleteConversationMessage,
} from '../../../api/admin'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import {
  useAdminTableSort,
  adminTimeMs,
  beijingDateEndMs,
  beijingDateStartMs,
  beijingDateValue,
  cmpLocale,
  cmpNum,
  fmtDt,
  fmtDtSeconds,
} from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import '../../../styles/admin-shell.css'

const rows = ref([])
const error = ref('')
const search = ref('')
const selectedId = ref('')
const selectedDetail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const previewMessagesRef = ref(null)
const selectedMessageKeys = ref([])
const activeMessageKey = ref('')
const rangeStart = ref('')
const rangeEnd = ref('')
const openDatePicker = ref('')
const calendarMonth = ref(startOfMonth(new Date()))
const softDeleting = ref(false)
const resettingId = ref('')
const phoneAvatarFailed = ref(false)
const DETAIL_PAGE_SIZE = 100
const DETAIL_WINDOW_LIMIT = 120
const AUTO_REFRESH_MS = 1000
const MODE_LABELS = {
  normal: '普通聊天',
  galgame: '游戏模式',
  galgame_lock: '锁分模式',
}
const RELATIONSHIP_LABELS = {
  stranger: '陌生',
  acquainted: '认识',
  friend: '朋友',
  close_friend: '亲近',
  intimate: '亲密',
  lover: '恋人',
  new_contact: '新朋友',
  uncertain: '未知',
  familiar: '好朋友',
  flirting: '暧昧对象',
  committed_partner: '伴侣',
  intimate_partner: '亲密伴侣',
  broken_up: '已分手',
  in_conflict: '吵架中',
  mutual_dislike: '互相看不爽',
  hurtful_dynamic: '互相伤害',
  mentor_student: '师生',
  trusted_companion: '可信同伴',
  family_like: '家人般',
}
const MOOD_LABELS = {
  neutral: '平静',
  happy: '开心',
  sad: '难过',
  angry: '生气',
  shy: '害羞',
  nervous: '紧张',
  excited: '兴奋',
}
const sceneCache = new WeakMap()
const detailPaging = ref({
  offset: 0,
  total: 0,
  hasOlder: false,
  hasNewer: false,
  loadingOlder: false,
  loadingNewer: false,
})
let detailRequestSeq = 0
let lastBlankClickAt = 0
let autoRefreshTimer = null
let autoRefreshing = false
let previewUserScrollLocked = false
let previewProgrammaticScrollUntil = 0
const calendarWeekdays = ['一', '二', '三', '四', '五', '六', '日']

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('updated', 'desc')

const { startResize, thStyle } = useColResize(
  { mode: 86, title: 220, updated: 130, created: 130, user: 120, char: 120, n: 72, visible: 92, prev: null, op: 100 },
  {
    min: 48,
    columnOrder: ['mode', 'title', 'updated', 'created', 'user', 'char', 'n', 'visible', 'prev', 'op'],
    minByKey: { mode: 76, op: 80, visible: 78, updated: 112, created: 112 },
  },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 52,
  headHeight: 48,
  minRows: 4,
  maxRows: 200,
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let arr = !q
    ? rows.value.slice()
    : rows.value.filter((c) => {
        const u = (c.user || c.username || '').toLowerCase()
        const ch = (c.character || c.character_name || c.character_id || '').toLowerCase()
        const t = (c.title || c.id || '').toLowerCase()
        const mode = `${modeLabel(c)} ${modeValue(c)}`.toLowerCase()
        return mode.includes(q) || u.includes(q) || ch.includes(q) || t.includes(q)
      })
  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'mode') return cmpLocale(modeLabel(a), modeLabel(b), dir)
    if (sk === 'title') return cmpLocale(a.title || a.id, b.title || b.id, dir)
    if (sk === 'updated') return cmpNum(convTimeSort(a.updated_at || a.timestamp), convTimeSort(b.updated_at || b.timestamp), dir)
    if (sk === 'created') return cmpNum(convTimeSort(a.created_at || a.timestamp), convTimeSort(b.created_at || b.timestamp), dir)
    if (sk === 'user') return cmpLocale(a.user || a.username, b.user || b.username, dir)
    if (sk === 'char')
      return cmpLocale(
        a.character || a.character_name || a.character_id,
        b.character || b.character_name || b.character_id,
        dir,
      )
    if (sk === 'n') return cmpNum(a.messages, b.messages, dir)
    if (sk === 'visible') return cmpNum(isUserVisible(a) ? 1 : 0, isUserVisible(b) ? 1 : 0, dir)
    if (sk === 'prev') return cmpLocale(a.last_message, b.last_message, dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(filtered, viewportRows)

const selectedRow = computed(() => rows.value.find((x) => x.id === selectedId.value) || null)
const detailMessages = computed(() => selectedDetail.value?.messages || [])
const visibleDetailMessages = computed(() => detailMessages.value.filter((m) => !isSuppressedMessage(m)))
const phoneAvatarSrc = computed(() => avatarUrl(selectedDetail.value?.character_avatar || selectedRow.value?.character_avatar))
const selectedMode = computed(() => modeValue(selectedDetail.value || selectedRow.value))
const selectedModeLabel = computed(() => modeLabel(selectedDetail.value || selectedRow.value))
const isGalgameSelected = computed(() => isGalgameModeValue(selectedMode.value))
const selectedGameScore = computed(() => {
  const value = selectedDetail.value?.score ?? selectedRow.value?.score
  return value === null || value === undefined || value === '' ? '' : value
})
const selectedGameStatus = computed(() => gameStatusLabel(selectedDetail.value?.game_status || selectedRow.value?.game_status))
const selectableMessages = computed(() => visibleDetailMessages.value.filter((m) => m?.message_id))
const selectedMessages = computed(() => {
  const keys = new Set(selectedMessageKeys.value)
  return visibleDetailMessages.value.filter((m) => keys.has(messageKey(m)))
})
const activeSelectedMessage = computed(() => visibleDetailMessages.value.find((m) => messageKey(m) === activeMessageKey.value) || null)
const selectedDeletableMessages = computed(() => selectedMessages.value.filter((m) => m?.message_id && !isSuppressedMessage(m)))
const selectedSummary = computed(() => {
  if (!selectedMessages.value.length) return ''
  if (selectedMessages.value.length > 1) {
    return `已选择 ${selectedMessages.value.length} 条 · 可软删 ${selectedDeletableMessages.value.length} 条`
  }
  const m = selectedMessages.value[0]
  const side = m.role === 'user' ? '用户' : m.role === 'system' ? '系统' : '角色'
  return `${side} · ${formatMessageTime(m.timestamp) || '无时间'}`
})
const canSoftDeleteSelected = computed(() => {
  return Boolean(selectedId.value && isNormalConversation(selectedDetail.value || selectedRow.value) && selectedDeletableMessages.value.length)
})
const calendarTitle = computed(() => {
  const d = calendarMonth.value
  return `${d.getFullYear()}年${String(d.getMonth() + 1).padStart(2, '0')}月`
})
const calendarDays = computed(() => buildCalendarDays(calendarMonth.value))

watch([search, sortKey, sortDir], () => {
  resetPage()
})

watch(activeMessageKey, () => {
  scrollSelectedMessageIntoView()
})

watch(phoneAvatarSrc, () => {
  phoneAvatarFailed.value = false
})

function convTimeSort(t) {
  const ms = adminTimeMs(t)
  return Number.isFinite(ms) ? ms : 0
}

async function load(options = {}) {
  const silent = Boolean(options.silent)
  const shouldResetPage = options.resetPage !== false
  if (!silent) error.value = ''
  try {
    const data = await fetchConversations()
    rows.value = Array.isArray(data) ? data : data.conversations || data.items || []
    if (selectedId.value && !rows.value.some((x) => x.id === selectedId.value)) {
      selectedId.value = ''
      selectedDetail.value = null
    }
    if (shouldResetPage) resetPage()
  } catch (e) {
    if (!silent) error.value = e.message || String(e)
  }
}

async function selectConversation(c) {
  if (!c?.id) return
  selectedId.value = c.id
  selectedDetail.value = null
  previewUserScrollLocked = false
  clearSelectedMessages()
  rangeStart.value = ''
  rangeEnd.value = ''
  detailError.value = ''
  detailLoading.value = true
  resetDetailPaging()
  const seq = ++detailRequestSeq
  try {
    const data = await fetchConversationDetail(c.id, { limit: DETAIL_PAGE_SIZE, fromLatest: true, includeDeleted: false })
    if (seq !== detailRequestSeq) return
    selectedDetail.value = data
    applyDetailPaging(data)
    seedTimeRange()
    await scrollPreviewBottom()
  } catch (e) {
    if (seq !== detailRequestSeq) return
    detailError.value = e.message || String(e)
  } finally {
    if (seq === detailRequestSeq) detailLoading.value = false
  }
}

function resetDetailPaging() {
  detailPaging.value = {
    offset: 0,
    total: 0,
    hasOlder: false,
    hasNewer: false,
    loadingOlder: false,
    loadingNewer: false,
  }
}

function applyDetailPaging(data) {
  const offset = Number(data?.message_offset || 0)
  const total = Number(data?.message_total || data?.messages?.length || 0)
  const loaded = Array.isArray(data?.messages) ? data.messages.length : Number(data?.messages_loaded || 0)
  detailPaging.value = {
    offset,
    total,
    hasOlder: offset > 0 || Boolean(data?.has_older),
    hasNewer: offset + loaded < total || Boolean(data?.has_newer),
    loadingOlder: false,
    loadingNewer: false,
  }
}

function setDetailWindow(data, messages, offset) {
  const total = Number(data?.message_total || messages.length || 0)
  selectedDetail.value = {
    ...(selectedDetail.value || data),
    ...data,
    messages,
    message_offset: offset,
    messages_loaded: messages.length,
    has_older: offset > 0,
    has_newer: offset + messages.length < total,
  }
  applyDetailPaging(selectedDetail.value)
  pruneSelectedMessageKeys()
}

function pruneSelectedMessageKeys() {
  const existing = new Set(detailMessages.value.map((m) => messageKey(m)))
  selectedMessageKeys.value = selectedMessageKeys.value.filter((key) => existing.has(key))
  if (activeMessageKey.value && !existing.has(activeMessageKey.value)) {
    activeMessageKey.value = selectedMessageKeys.value.at(-1) || ''
  }
}

async function loadOlderPreviewMessages() {
  if (!selectedId.value || detailLoading.value || detailPaging.value.loadingOlder || !detailPaging.value.hasOlder) return
  const currentOffset = Number(detailPaging.value.offset || 0)
  if (currentOffset <= 0) return
  const nextOffset = Math.max(0, currentOffset - DETAIL_PAGE_SIZE)
  const nextLimit = currentOffset - nextOffset
  if (nextLimit <= 0) return

  const wrap = previewMessagesRef.value
  const prevHeight = wrap?.scrollHeight || 0
  const prevTop = wrap?.scrollTop || 0
  const requestId = detailRequestSeq
  detailPaging.value = { ...detailPaging.value, loadingOlder: true }
  try {
    const data = await fetchConversationDetail(selectedId.value, { limit: nextLimit, offset: nextOffset, includeDeleted: false })
    if (requestId !== detailRequestSeq || selectedId.value !== data?.id) return
    const oldMessages = Array.isArray(data.messages) ? data.messages : []
    const existingKeys = new Set(detailMessages.value.map((m) => messageKey(m)))
    const prepend = oldMessages.filter((m) => !existingKeys.has(messageKey(m)))
    const combined = [...prepend, ...detailMessages.value]
    const messages = combined.slice(0, DETAIL_WINDOW_LIMIT)
    setDetailWindow(data, messages, nextOffset)
    seedTimeRange()
    await nextTick()
    setPreviewScrollTop(wrap, wrap.scrollHeight - prevHeight + prevTop)
  } catch (e) {
    toast.error(e.message || String(e))
    detailPaging.value = { ...detailPaging.value, loadingOlder: false }
  }
}

async function loadNewerPreviewMessages() {
  if (!selectedId.value || detailLoading.value || detailPaging.value.loadingNewer || !detailPaging.value.hasNewer) return
  const currentOffset = Number(detailPaging.value.offset || 0)
  const currentLength = detailMessages.value.length
  const total = Number(detailPaging.value.total || 0)
  const nextOffset = currentOffset + currentLength
  if (nextOffset >= total) return
  const nextLimit = Math.min(DETAIL_PAGE_SIZE, total - nextOffset)
  if (nextLimit <= 0) return

  const wrap = previewMessagesRef.value
  const prevHeight = wrap?.scrollHeight || 0
  const prevTop = wrap?.scrollTop || 0
  const requestId = detailRequestSeq
  detailPaging.value = { ...detailPaging.value, loadingNewer: true }
  try {
    const data = await fetchConversationDetail(selectedId.value, { limit: nextLimit, offset: nextOffset, includeDeleted: false })
    if (requestId !== detailRequestSeq || selectedId.value !== data?.id) return
    const newMessages = Array.isArray(data.messages) ? data.messages : []
    const existingKeys = new Set(detailMessages.value.map((m) => messageKey(m)))
    const append = newMessages.filter((m) => !existingKeys.has(messageKey(m)))
    const combined = [...detailMessages.value, ...append]
    const drop = Math.max(0, combined.length - DETAIL_WINDOW_LIMIT)
    const messages = combined.slice(drop)
    setDetailWindow(data, messages, currentOffset + drop)
    seedTimeRange()
    await nextTick()
    setPreviewScrollTop(wrap, Math.max(0, wrap.scrollHeight - prevHeight + prevTop))
  } catch (e) {
    toast.error(e.message || String(e))
    detailPaging.value = { ...detailPaging.value, loadingNewer: false }
  }
}

function messageKey(m) {
  return String(m?.message_id || `${m?.sequence_number || ''}-${m?.timestamp || ''}`)
}

function toggleMessageSelection(m) {
  if (!m?.message_id) return
  const key = messageKey(m)
  activeMessageKey.value = key
  if (selectedMessageKeys.value.includes(key)) {
    selectedMessageKeys.value = selectedMessageKeys.value.filter((x) => x !== key)
    if (activeMessageKey.value === key) activeMessageKey.value = selectedMessageKeys.value.at(-1) || ''
  } else {
    selectedMessageKeys.value = [...selectedMessageKeys.value, key]
  }
}

function isSelectedMessage(m) {
  return selectedMessageKeys.value.includes(messageKey(m))
}

function selectMessages(messages) {
  const keys = []
  for (const m of messages) {
    const key = messageKey(m)
    if (m?.message_id && !keys.includes(key)) keys.push(key)
  }
  selectedMessageKeys.value = keys
  activeMessageKey.value = keys.at(-1) || ''
}

function seedTimeRange() {
  const visible = selectableMessages.value.filter((m) => !isSuppressedMessage(m))
  if (!visible.length) return
  rangeStart.value = toDateLocalValue(visible[0].timestamp)
  rangeEnd.value = toDateLocalValue(visible.at(-1).timestamp)
  calendarMonth.value = dateValueToMonth(rangeEnd.value || rangeStart.value)
}

function toggleDatePicker(which) {
  openDatePicker.value = openDatePicker.value === which ? '' : which
  const value = which === 'start' ? rangeStart.value : rangeEnd.value
  calendarMonth.value = dateValueToMonth(value || rangeStart.value || rangeEnd.value)
}

function pickDate(which, value) {
  if (which === 'start') rangeStart.value = value
  else rangeEnd.value = value
  openDatePicker.value = ''
}

function shiftCalendarMonth(delta) {
  const d = calendarMonth.value
  calendarMonth.value = new Date(d.getFullYear(), d.getMonth() + delta, 1)
}

function isDateInSelectedRange(value) {
  const start = parseLocalDateStart(rangeStart.value)
  const end = parseLocalDateEnd(rangeEnd.value)
  const ms = parseLocalDateStart(value)
  if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(ms)) return false
  return ms >= Math.min(start, end) && ms <= Math.max(start, end)
}

function selectByTimeRange() {
  const start = parseLocalDateStart(rangeStart.value)
  const end = parseLocalDateEnd(rangeEnd.value)
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    toast.error('请选择有效的开始和结束时间')
    return
  }
  const low = Math.min(start, end)
  const high = Math.max(start, end)
  const matched = selectableMessages.value.filter((m) => {
    if (isSuppressedMessage(m)) return false
    const ms = messageTimeMs(m)
    return ms >= low && ms <= high
  })
  if (!matched.length) {
    toast.error('这个时间段内没有未隐藏消息')
    return
  }
  selectMessages(matched)
  toast.success(`已选择 ${matched.length} 条消息`)
}

function selectAdjacentMessage(step) {
  const candidates = selectableMessages.value.filter((m) => !isSuppressedMessage(m))
  if (!candidates.length) return
  const currentKey = activeMessageKey.value || selectedMessageKeys.value.at(-1) || ''
  const currentIndex = candidates.findIndex((m) => messageKey(m) === currentKey)
  const nextIndex =
    currentIndex < 0
      ? step > 0
        ? 0
        : candidates.length - 1
      : Math.min(candidates.length - 1, Math.max(0, currentIndex + step))
  const m = candidates[nextIndex]
  if (!m) return
  const key = messageKey(m)
  activeMessageKey.value = key
  if (!selectedMessageKeys.value.includes(key)) {
    selectedMessageKeys.value = [...selectedMessageKeys.value, key]
  }
}

function clearSelectedMessages() {
  selectedMessageKeys.value = []
  activeMessageKey.value = ''
}

async function copySelectedMessageIds() {
  const ids = selectedMessages.value.map((m) => m.message_id).filter(Boolean)
  if (!ids.length) return
  try {
    await navigator.clipboard?.writeText(ids.join('\n'))
    toast.success(ids.length > 1 ? `已复制 ${ids.length} 个消息 ID` : '已复制消息 ID')
  } catch {
    toast.error('复制失败')
  }
}

async function softDeleteSelected() {
  const targets = selectedDeletableMessages.value
  if (!selectedId.value || !targets.length) return
  if (!isNormalConversation(selectedDetail.value || selectedRow.value)) {
    toast.error('游戏/锁分记录暂不支持在这里软删除')
    return
  }
  if (!(await confirmAsync({ title: '软删除消息', message: `隐藏选中的 ${targets.length} 条消息？`, danger: true }))) return
  softDeleting.value = true
  try {
    for (const m of targets) {
      await softDeleteConversationMessage(selectedId.value, m.message_id)
    }
    toast.success(`已软删除 ${targets.length} 条消息`)
    await reloadSelectedDetail()
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    softDeleting.value = false
  }
}

async function reloadSelectedDetail(options = {}) {
  if (!selectedId.value) return
  const silent = Boolean(options.silent)
  const preserveScroll = Boolean(options.preserveScroll)
  const wrap = previewMessagesRef.value
  const prevHeight = wrap?.scrollHeight || 0
  const prevTop = wrap?.scrollTop || 0
  const shouldFollowBottom = !previewUserScrollLocked && isPreviewNearBottom()
  const keys = selectedMessageKeys.value.slice()
  const active = activeMessageKey.value
  const currentLoaded = Math.max(DETAIL_PAGE_SIZE, Math.min(DETAIL_WINDOW_LIMIT, detailMessages.value.length || DETAIL_PAGE_SIZE))
  const detailOptions = shouldFollowBottom
    ? { limit: DETAIL_PAGE_SIZE, fromLatest: true, includeDeleted: false }
    : { limit: currentLoaded, offset: Number(detailPaging.value.offset || 0), includeDeleted: false }
  try {
    const data = await fetchConversationDetail(selectedId.value, detailOptions)
    selectedDetail.value = data
    applyDetailPaging(data)
    const existing = new Set(detailMessages.value.map((m) => messageKey(m)))
    selectedMessageKeys.value = keys.filter((key) => existing.has(key))
    activeMessageKey.value = existing.has(active) ? active : selectedMessageKeys.value.at(-1) || ''
    if (preserveScroll) {
      await nextTick()
      if (wrap) {
        if (shouldFollowBottom) {
          setPreviewScrollTop(wrap, wrap.scrollHeight)
        } else {
          setPreviewScrollTop(wrap, Math.max(0, wrap.scrollHeight - prevHeight + prevTop))
        }
      }
    }
  } catch (e) {
    if (!silent) throw e
  }
}

async function resetConversationRow(row) {
  const id = row?.id || row
  if (!id || resettingId.value) return
  const current = typeof row === 'object' ? row : rows.value.find((x) => x.id === id) || selectedDetail.value
  const mode = modeLabel(current)
  const character = current?.character || current?.character_name || current?.character_id || '该角色'
  const user = current?.user || current?.username || '该用户'
  const confirmed = await confirmAsync({
    title: '重置对话',
    message: `重置 ${user} / ${character} 的${mode}？当前可见内容和进度会被清空。`,
    danger: true,
  })
  if (!confirmed) return
  resettingId.value = id
  try {
    const res = await resetAdminConversation(id)
    toast.success(res?.message || '已重置')
    if (selectedId.value === id) {
      await reloadSelectedDetail({ silent: true, preserveScroll: false })
    }
    await load({ resetPage: false })
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    resettingId.value = ''
  }
}

async function scrollPreviewBottom() {
  await nextTick()
  const el = previewMessagesRef.value
  if (el) setPreviewScrollTop(el, el.scrollHeight)
}

function setPreviewScrollTop(el, top) {
  if (!el) return
  previewProgrammaticScrollUntil = Date.now() + 180
  el.scrollTop = top
}

function isPreviewNearBottom() {
  const el = previewMessagesRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 48
}

async function scrollSelectedMessageIntoView() {
  await nextTick()
  const wrap = previewMessagesRef.value
  if (!wrap || !activeMessageKey.value) return
  const target = wrap.querySelector(`[data-message-key="${cssAttr(activeMessageKey.value)}"]`)
  if (target) {
    previewProgrammaticScrollUntil = Date.now() + 600
    target.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
}

function handlePreviewBlankClick(event) {
  if (event.target?.closest?.('.message-bubble')) return
  const now = Date.now()
  if (now - lastBlankClickAt <= 1000) {
    clearSelectedMessages()
    lastBlankClickAt = 0
    return
  }
  lastBlankClickAt = now
}

function handlePreviewScroll(event) {
  const el = event.currentTarget
  if (!el || detailLoading.value || detailPaging.value.loadingOlder || detailPaging.value.loadingNewer) return
  if (Date.now() > previewProgrammaticScrollUntil) {
    previewUserScrollLocked = true
  }
  if (el.scrollTop <= 80) {
    loadOlderPreviewMessages()
  } else if (el.scrollHeight - el.scrollTop - el.clientHeight <= 80) {
    loadNewerPreviewMessages()
  }
}

function cssAttr(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

function firstChar(text) {
  return (text || '聊').trim().charAt(0) || '聊'
}

function avatarUrl(avatar) {
  if (!avatar || typeof avatar !== 'string') return ''
  const a = avatar.trim()
  if (a.startsWith('http') || a.startsWith('data:')) return a
  if (a.startsWith('/')) return a
  return `/${a.replace(/^\/+/, '')}`
}

function isUserVisible(c) {
  return c?.is_hidden !== true
}

function modeValue(item) {
  const raw = String(item?.mode || item?.conversation_mode || '').trim()
  if (raw === 'galgame' || raw === 'galgame_lock' || raw === 'normal') return raw
  const id = String(item?.id || '').trim()
  if (id.startsWith('galgame_lock:')) return 'galgame_lock'
  if (id.startsWith('galgame:')) return 'galgame'
  return 'normal'
}

function modeLabel(item) {
  const mode = modeValue(item)
  return item?.mode_label || MODE_LABELS[mode] || mode || '未知模式'
}

function modeClass(item) {
  return `mode-${modeValue(item)}`
}

function isNormalConversation(item) {
  return modeValue(item) === 'normal'
}

function isGalgameModeValue(mode) {
  return mode === 'galgame' || mode === 'galgame_lock'
}

function gameStatusLabel(status) {
  const raw = cleanSceneText(status)
  if (!raw) return ''
  const map = {
    playing: '进行中',
    completed: '已完成',
    complete: '已完成',
    ended: '已结束',
    archived: '已归档',
    locked: '锁分中',
  }
  return map[raw] || raw
}

function isGalgameAssistantMessage(m) {
  return isGalgameSelected.value && m?.role !== 'user' && m?.role !== 'system'
}

function messageBubbleClass(m) {
  return {
    'galgame-bubble': isGalgameAssistantMessage(m) && Boolean(galgameScene(m) || galgameOptions(m).length),
  }
}

function galgameScene(m) {
  if (!m || typeof m !== 'object') return null
  if (sceneCache.has(m)) return sceneCache.get(m)

  const sources = []
  const effectiveRaw =
    cleanSceneText(m.rawContent || m.raw_content) ||
    (String(m.content || '').trim().startsWith('{') ? m.content : '')
  sources.push(parseGalgameFieldsFromRaw(effectiveRaw))
  sources.push(parseGalgameFieldsFromRaw(m.scene_metadata))

  const htmlSource = [m.content, m.displayContent, m.display_content]
    .map((x) => String(x || '').trim())
    .find((x) => x.includes('gal-scene-') || x.includes('galgame-scene-container'))
  sources.push(parseGalgameFromHtml(htmlSource))

  const merged = {}
  for (const src of sources) {
    if (!src || typeof src !== 'object') continue
    for (const [key, value] of Object.entries(src)) {
      const text = normalizeSceneValue(value)
      if (text) merged[key] = text
    }
  }
  const result = Object.keys(merged).length ? merged : null
  sceneCache.set(m, result)
  return result
}

function parseGalgameFieldsFromRaw(raw) {
  const parsed = parseJsonMaybe(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  const root = parsed.data && typeof parsed.data === 'object' && !Array.isArray(parsed.data) ? parsed.data : parsed
  const scene = root.scene && typeof root.scene === 'object' && !Array.isArray(root.scene) ? root.scene : null
  const score = root.score && typeof root.score === 'object' && !Array.isArray(root.score) ? root.score : null
  const output = {}

  if (scene) {
    output.time = scene.time
    output.location = scene.location
    output.env = scene.env
    output.body_state = scene.body_state
    output.thought = scene.thoughts || scene.thought
    output.third_party = scene.third_party_dialogue || scene.third_party
    output.dialogue = scene.response || scene.dialogue
  } else {
    output.time = root.time
    output.location = root.location
    output.env = root.env
    output.body_state = root.body_state
    output.thought = root.thought || root.thoughts
    output.third_party = root.third_party || root.third_party_dialogue
    output.dialogue = root.dialogue || root.response
  }

  output.relationship_stage = root.relationship_stage
  output.mood = root.mood
  output.memory_tags = formatListLike(root.memory_tags)
  output.more_state = buildMoreStateRows(root)
  output.event_flags = formatListLike(root.event_flags)
  output.score_delta_reason = root.score_delta_reason || score?.reason
  output.text = root.text
  if (score?.current !== undefined || root.score_current !== undefined) {
    output.score_current = score?.current ?? root.score_current
  }
  if (score?.delta !== undefined || root.score_delta !== undefined) {
    output.score_delta = score?.delta ?? root.score_delta
  }
  return output
}

function parseGalgameFromHtml(content) {
  const html = String(content || '')
  if (!html.includes('gal-scene-') && !html.includes('galgame-scene-container')) return null
  const map = {}
  const blockRegex = /<div\s+class=["']([^"']*gal-scene-[^"']*)["'][^>]*>([\s\S]*?)<\/div>/gi
  let match
  while ((match = blockRegex.exec(html))) {
    const className = match[1] || ''
    const text = stripHtml(match[2])
    if (!text) continue
    if (className.includes('gal-scene-env')) map.env = text
    else if (className.includes('gal-scene-thought')) map.thought = text
    else if (className.includes('gal-scene-speech')) map.dialogue = text
    else if (className.includes('gal-scene-body-state') || className.includes('gal-scene-body')) map.body_state = text
    else if (className.includes('gal-scene-third-party')) map.third_party = text
  }
  map.time = findGalTagText(html, 'gal-time-tag')
  map.location = findGalTagText(html, 'gal-loc-tag')
  map.relationship_stage = findGalTagText(html, 'gal-rel-tag')
  map.mood = findGalTagText(html, 'gal-mood-tag')
  map.score_delta_reason = findGalDivText(html, 'gal-score-reason')
  const memoryRaw = findGalDivText(html, 'gal-memory-tags')
  if (memoryRaw) map.memory_tags = memoryRaw
  return Object.values(map).some((x) => cleanSceneText(x)) ? map : null
}

function findGalTagText(html, classPart) {
  const re = new RegExp(`<span\\s+class=["'][^"']*${classPart}[^"']*["'][^>]*>([\\s\\S]*?)<\\/span>`, 'i')
  const match = re.exec(html)
  return match ? stripHtml(match[1]) : ''
}

function findGalDivText(html, classPart) {
  const re = new RegExp(`<div\\s+class=["'][^"']*${classPart}[^"']*["'][^>]*>([\\s\\S]*?)<\\/div>`, 'i')
  const match = re.exec(html)
  return match ? stripHtml(match[1]) : ''
}

function galSceneBlocks(scene) {
  if (!scene) return []
  return [
    { key: 'env', title: '环境描写', text: scene.env },
    { key: 'body-state', title: '身体描写', text: scene.body_state },
    { key: 'thought', title: '心理活动', text: scene.thought },
    { key: 'third-party', title: '其他发言', text: scene.third_party },
  ].filter((item) => cleanSceneText(item.text))
}

function galSceneStateBlocks(scene) {
  if (!scene) return []
  return [
    { key: 'memory-tags', title: '记忆标签', text: scene.memory_tags },
    { key: 'more-state', title: '状态细节', text: scene.more_state },
    { key: 'event-flags', title: '事件标记', text: scene.event_flags },
  ].filter((item) => cleanSceneText(item.text))
}

function galTags(scene) {
  if (!scene) return []
  const rel = cleanSceneText(scene.relationship_stage)
  const mood = cleanSceneText(scene.mood)
  const tags = [
    { label: '时间', value: scene.time, type: 'time' },
    { label: '地点', value: scene.location, type: 'location' },
    { label: '关系', value: RELATIONSHIP_LABELS[rel] || rel, type: 'relationship' },
    { label: '心情', value: MOOD_LABELS[mood] || mood, type: 'mood' },
  ].filter((item) => cleanSceneText(item.value))
  const current = cleanSceneText(scene.score_current)
  const delta = cleanSceneText(scene.score_delta)
  if (current || delta) {
    tags.push({
      label: '分数',
      value: `${current || '-'}${delta ? ` (${Number(delta) > 0 ? '+' : ''}${delta})` : ''}`,
      type: 'score',
    })
  }
  return tags
}

function galgameOptions(m) {
  if (!m) return []
  const direct = normalizeGalOptions(m.galgameOptions || m.galgame_options || m.suggestions)
  if (direct.length) return direct
  const rawOptions =
    parseOptionsFromJson(m.rawContent || m.raw_content) ||
    parseOptionsFromJson(m.content) ||
    []
  return normalizeGalOptions(rawOptions)
}

function parseOptionsFromJson(value) {
  const parsed = parseJsonMaybe(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  const root = parsed.data && typeof parsed.data === 'object' && !Array.isArray(parsed.data) ? parsed.data : parsed
  return root.suggested_options || root.galgameOptions || root.galgame_options || root.options || null
}

function normalizeGalOptions(value) {
  const list = typeof value === 'string' ? parseJsonMaybe(value) : value
  if (!Array.isArray(list)) return []
  return list
    .map((item) => {
      if (typeof item === 'string') return { label: cleanSceneText(item) }
      return {
        label: cleanSceneText(item?.label || item?.text || item?.content),
        type: cleanSceneText(item?.type),
        tone: cleanSceneText(item?.tone),
      }
    })
    .filter((item) => item.label)
}

function plainMessageText(m) {
  const content = cleanSceneText(m?.content)
  const parsed = parseGalgameFieldsFromRaw(content)
  if (parsed) {
    return cleanSceneText(parsed.dialogue || parsed.text || parsed.env || parsed.thought)
  }
  return stripThinkBlocksForDisplay(stripHtml(content))
}

function markdownTextHtml(value) {
  const text = escapeHtml(stripThinkBlocksForDisplay(cleanSceneText(value)))
  if (!text) return ''
  return text
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__([\s\S]+?)__/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function parseJsonMaybe(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  const text = String(value || '').trim()
  if (!text || (!text.startsWith('{') && !text.startsWith('['))) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function buildMoreStateRows(root) {
  const direct = normalizeSceneValue(root?.more_state)
  if (direct) return direct
  const labels = [
    ['character_race', '角色种族'],
    ['character_gender', '角色性别'],
    ['character_outfit', '角色衣着'],
    ['character_pose', '角色姿势'],
    ['character_position', '角色位置'],
    ['character_action', '角色动作'],
    ['player_race', '玩家种族'],
    ['player_gender', '玩家性别'],
    ['player_outfit', '玩家衣着'],
    ['player_pose', '玩家姿势'],
    ['player_position', '玩家位置'],
    ['player_action', '玩家动作'],
  ]
  return labels
    .map(([key, label]) => {
      const text = normalizeSceneValue(root?.[key])
      return text ? `• ${label}: ${text}` : ''
    })
    .filter(Boolean)
    .join('\n')
}

function formatListLike(value) {
  const parsed = typeof value === 'string' ? parseJsonMaybe(value) : value
  if (Array.isArray(parsed)) {
    return parsed.map((item) => normalizeSceneValue(item)).filter(Boolean).map((item) => `• ${item}`).join('\n')
  }
  if (parsed && typeof parsed === 'object') {
    return Object.entries(parsed)
      .map(([key, item]) => `${key}: ${normalizeSceneValue(item)}`)
      .filter((line) => !line.endsWith(': '))
      .join('\n')
  }
  return normalizeSceneValue(value)
}

function normalizeSceneValue(value) {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map((item) => normalizeSceneValue(item)).filter(Boolean).join('\n')
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${normalizeSceneValue(item)}`)
      .filter((line) => !line.endsWith(': '))
      .join('\n')
  }
  return cleanSceneText(value)
}

function cleanSceneText(value) {
  const text = String(value ?? '').trim()
  if (!text || text.toLowerCase() === 'null' || text.toLowerCase() === 'none') return ''
  return text
}

function stripThinkBlocksForDisplay(raw) {
  return String(raw || '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, '')
    .trim()
}

function stripHtml(value) {
  const withBreaks = String(value || '').replace(/<br\s*\/?>/gi, '\n')
  return decodeHtml(withBreaks)
    .replace(/<[^>]+>/g, ' ')
    .replace(/[ \t\r\f\v]+/g, ' ')
    .replace(/\n\s+/g, '\n')
    .trim()
}

function decodeHtml(value) {
  return String(value || '')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
}

function lockStateItems(detail) {
  if (modeValue(detail) !== 'galgame_lock') return []
  return [
    { label: '生命', value: compactStateValue(detail?.char_vitals) },
    { label: '情绪', value: compactStateValue(detail?.char_mood) },
    { label: '锁定', value: compactStateValue(detail?.organ_fill) },
    { label: '性别', value: cleanSceneText(detail?.character_gender) },
  ].filter((item) => item.value)
}

function compactStateValue(value) {
  if (value === null || value === undefined || value === '') return ''
  const parsed = typeof value === 'string' ? parseJsonMaybe(value) : value
  if (Array.isArray(parsed)) return parsed.map((x) => cleanSceneText(x)).filter(Boolean).slice(0, 3).join(' / ')
  if (parsed && typeof parsed === 'object') {
    return Object.entries(parsed)
      .map(([key, item]) => `${key}:${typeof item === 'object' ? normalizeSceneValue(item) : cleanSceneText(item)}`)
      .filter((x) => !x.endsWith(':'))
      .slice(0, 2)
      .join(' / ')
  }
  return cleanSceneText(value)
}

function messageSide(m) {
  if (m?.role === 'user') return 'user'
  if (m?.role === 'system') return 'system'
  return 'assistant'
}

function messageSenderName(m) {
  if (m?.role === 'user') return selectedDetail.value?.user || selectedRow.value?.user || selectedRow.value?.username || '用户'
  if (m?.role === 'system') return '系统'
  return (
    m?.speaker_name ||
    m?.speakerName ||
    selectedDetail.value?.character ||
    selectedRow.value?.character ||
    selectedRow.value?.character_name ||
    '角色'
  )
}

function isSuppressedMessage(m) {
  return Boolean(m?.is_deleted || m?.is_hidden || m?.deleted_at || m?.hidden_at)
}

function messageTimeMs(m) {
  const ms = adminTimeMs(m?.timestamp)
  return Number.isFinite(ms) ? ms : 0
}

function toDateTimeLocalValue(ts) {
  const ms = messageTimeMs({ timestamp: ts })
  if (!ms) return ''
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const yyyy = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${yyyy}-${mo}-${dd}T${hh}:${mm}:${ss}`
}

function toDateLocalValue(ts) {
  return beijingDateValue(ts)
}

function formatRangeDate(value) {
  if (!value) return ''
  const parts = String(value).split('-')
  if (parts.length !== 3) return value
  return `${parts[0]}/${parts[1]}/${parts[2]}`
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function dateValueToMonth(value) {
  const parts = String(value || '').split('-').map((x) => Number(x))
  if (parts.length === 3 && parts.every((x) => Number.isFinite(x))) {
    return new Date(parts[0], parts[1] - 1, 1)
  }
  return startOfMonth(new Date())
}

function buildCalendarDays(monthDate) {
  const year = monthDate.getFullYear()
  const month = monthDate.getMonth()
  const first = new Date(year, month, 1)
  const mondayFirstOffset = (first.getDay() + 6) % 7
  const gridStart = new Date(year, month, 1 - mondayFirstOffset)
  const out = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i)
    const yyyy = d.getFullYear()
    const mo = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    out.push({
      key: `${yyyy}-${mo}-${dd}`,
      value: `${yyyy}-${mo}-${dd}`,
      day: d.getDate(),
      inMonth: d.getMonth() === month,
    })
  }
  return out
}

function parseLocalDateStart(value) {
  return beijingDateStartMs(value)
}

function parseLocalDateEnd(value) {
  return beijingDateEndMs(value)
}

function formatMessageTime(ts) {
  return fmtDtSeconds(ts)
}

async function refreshVisibleData() {
  if (autoRefreshing) return
  autoRefreshing = true
  try {
    await load({ silent: true, resetPage: false })
    if (selectedId.value) {
      await reloadSelectedDetail({ silent: true, preserveScroll: true })
    }
  } finally {
    autoRefreshing = false
  }
}

onMounted(async () => {
  await load()
  autoRefreshTimer = window.setInterval(refreshVisibleData, AUTO_REFRESH_MS)
})

onUnmounted(() => {
  if (autoRefreshTimer) window.clearInterval(autoRefreshTimer)
})
</script>

<style scoped>
.section-root {
  min-height: 0;
}
.card-fill {
  display: flex;
  flex-direction: column;
  min-height: 0;
  margin-bottom: 0;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
  gap: 0.5rem;
}
.toolbar-right {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.search-input {
  width: 260px;
  padding: 0.35rem 0.65rem;
}
.col-prev {
  min-width: 0;
}
.col-mode {
  min-width: 76px;
}
.col-title,
.col-user,
.col-char,
.col-updated,
.col-created {
  min-width: 0;
}
.col-op {
  min-width: 80px;
}
.col-visible {
  min-width: 78px;
}
.badge-on,
.badge-off {
  display: inline-block;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  line-height: 1.3;
}
.badge-on {
  background: rgba(61, 168, 130, 0.14);
  color: #6fb894;
}
.badge-off {
  background: rgba(100, 116, 139, 0.15);
  color: #64748b;
}
.mode-badge,
.phone-mode-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  padding: 0.1rem 0.42rem;
  border-radius: 6px;
  border: 1px solid transparent;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1.35;
}
.mode-normal {
  background: rgba(100, 116, 139, 0.16);
  border-color: rgba(148, 163, 184, 0.18);
  color: #cbd5e1;
}
.mode-galgame {
  background: rgba(61, 168, 130, 0.16);
  border-color: rgba(61, 168, 130, 0.28);
  color: #9de8c7;
}
.mode-galgame_lock {
  background: rgba(107, 127, 215, 0.2);
  border-color: rgba(139, 196, 207, 0.28);
  color: #c9d7ff;
}
.conv-row {
  cursor: pointer;
}
.conv-row.selected td {
  background: rgba(78, 191, 207, 0.08);
}
.conversations-workbench {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 0.9rem;
}
.list-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.preview-pane {
  min-height: 0;
  display: flex;
}
.phone-preview {
  width: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(17, 24, 39, 0.98)),
    var(--bg-deep);
  box-shadow: inset 0 0 0 6px rgba(2, 6, 23, 0.72);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(100, 116, 139, 0.8);
  flex-shrink: 0;
}
.status-dot.on {
  background: #3da882;
  box-shadow: 0 0 12px rgba(61, 168, 130, 0.6);
}
.phone-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.85rem 1rem;
  width: 100%;
  box-sizing: border-box;
  background: rgba(15, 23, 42, 0.92);
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 12px 0 0 rgba(15, 23, 42, 0.92);
}
.phone-action {
  flex-shrink: 0;
}
.selection-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.55rem 0.75rem;
  background: rgba(15, 23, 42, 0.88);
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}
.game-state-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
  padding: 0.45rem 0.75rem;
  background: rgba(12, 20, 35, 0.92);
  border-bottom: 1px solid rgba(139, 196, 207, 0.12);
}
.game-state-chip {
  display: inline-flex;
  max-width: 100%;
  padding: 0.12rem 0.42rem;
  border-radius: 6px;
  border: 1px solid rgba(139, 196, 207, 0.22);
  background: rgba(30, 41, 59, 0.74);
  color: rgba(226, 232, 240, 0.88);
  font-size: 0.68rem;
  font-weight: 650;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.date-picker-wrap {
  position: relative;
  flex: 1 1 132px;
  min-width: 0;
}
.date-input-btn {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  padding: 0.34rem 0.58rem;
  border-radius: 12px;
  border: 1px solid rgba(149, 120, 220, 0.58);
  background: rgba(15, 23, 42, 0.86);
  color: #eaf4ff;
  font-size: 0.78rem;
  line-height: 1.2;
  cursor: pointer;
}
.date-input-btn:hover,
.date-input-btn:focus-visible {
  border-color: rgba(139, 196, 207, 0.88);
  box-shadow: 0 0 0 2px rgba(139, 196, 207, 0.16);
  outline: none;
}
.calendar-icon {
  color: #fff;
  font-size: 1rem;
  line-height: 1;
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.38);
}
.pony-calendar {
  position: absolute;
  z-index: 20;
  top: calc(100% + 0.45rem);
  left: 0;
  width: 232px;
  padding: 0.7rem;
  border-radius: 14px;
  border: 1px solid rgba(139, 196, 207, 0.32);
  background:
    linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(15, 23, 42, 0.98)),
    var(--bg-deep);
  box-shadow:
    0 18px 44px rgba(2, 6, 23, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.calendar-right {
  left: auto;
  right: 0;
}
.calendar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.55rem;
  color: #f8fafc;
}
.calendar-head strong {
  font-size: 0.84rem;
  font-weight: 700;
}
.icon-btn {
  width: 28px;
  height: 28px;
  border: 1px solid rgba(149, 120, 220, 0.42);
  border-radius: 8px;
  background: rgba(30, 41, 59, 0.72);
  color: #fff;
  font-size: 1.05rem;
  line-height: 1;
  cursor: pointer;
}
.icon-btn:hover {
  border-color: rgba(139, 196, 207, 0.8);
  background: rgba(43, 63, 83, 0.86);
}
.calendar-week,
.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 0.25rem;
}
.calendar-week {
  margin-bottom: 0.35rem;
  color: rgba(203, 213, 225, 0.72);
  font-size: 0.66rem;
  text-align: center;
}
.calendar-day {
  aspect-ratio: 1;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #dbeafe;
  font-size: 0.72rem;
  cursor: pointer;
}
.calendar-day:hover {
  border-color: rgba(139, 196, 207, 0.72);
  background: rgba(139, 196, 207, 0.12);
}
.calendar-day.muted {
  color: rgba(148, 163, 184, 0.5);
}
.calendar-day.inRange {
  background: rgba(139, 196, 207, 0.14);
  color: #effcff;
}
.calendar-day.selected {
  border-color: rgba(139, 196, 207, 0.9);
  background: linear-gradient(135deg, rgba(61, 168, 130, 0.92), rgba(107, 127, 215, 0.92));
  color: #fff;
  font-weight: 700;
  box-shadow: 0 0 0 2px rgba(139, 196, 207, 0.14);
}
.avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: linear-gradient(135deg, #3da882, #6b7fd7);
  color: #fff;
  font-weight: 700;
  overflow: hidden;
}
.avatar img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.avatar span {
  line-height: 1;
}
.phone-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  flex: 1;
}
.phone-meta strong,
.phone-meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.phone-meta span {
  color: var(--text-muted);
  font-size: 0.76rem;
}
.phone-meta .phone-mode-pill {
  margin-top: 0.18rem;
  color: #dbeafe;
  font-size: 0.66rem;
}
.phone-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem 0.9rem 1.1rem;
  background:
    linear-gradient(rgba(15, 23, 42, 0.86), rgba(15, 23, 42, 0.86)),
    radial-gradient(circle at 18% 16%, rgba(61, 168, 130, 0.14), transparent 32%),
    radial-gradient(circle at 92% 72%, rgba(107, 127, 215, 0.12), transparent 30%);
}
.preview-state {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: var(--text-muted);
  text-align: center;
  font-size: 0.85rem;
}
.spin {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(148, 163, 184, 0.28);
  border-top-color: #8bc4cf;
  animation: spin 0.8s linear infinite;
}
.error-text {
  color: #fca5a5;
}
.load-more-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  min-height: 28px;
  margin-bottom: 0.45rem;
  color: var(--text-muted);
  font-size: 0.76rem;
}
.message-row {
  display: flex;
  margin: 0.45rem 0;
  cursor: pointer;
}
.message-row.user {
  justify-content: flex-end;
}
.message-row.assistant,
.message-row.system {
  justify-content: flex-start;
}
.message-bubble {
  max-width: 82%;
  padding: 0.55rem 0.68rem 0.42rem;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(30, 41, 59, 0.92);
  color: #e2e8f0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  font-size: 0.8rem;
  line-height: 1.55;
}
.message-row.user .message-bubble {
  background: rgba(61, 168, 130, 0.92);
  color: #f8fafc;
  border-color: rgba(110, 231, 183, 0.24);
}
.message-row.system .message-bubble {
  max-width: 90%;
  background: rgba(100, 116, 139, 0.18);
  color: #cbd5e1;
}
.message-bubble.galgame-bubble {
  max-width: 88%;
  padding: 0.58rem 0.62rem 0.44rem;
  background: rgba(28, 39, 56, 0.94);
  border-color: rgba(139, 196, 207, 0.18);
  white-space: normal;
}
.galgame-scene {
  display: flex;
  flex-direction: column;
  gap: 0.44rem;
  min-width: 0;
}
.gal-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.24rem;
}
.gal-tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  gap: 0.22rem;
  padding: 0.08rem 0.34rem;
  border-radius: 6px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(15, 23, 42, 0.48);
  color: rgba(226, 232, 240, 0.88);
  font-size: 0.66rem;
  line-height: 1.35;
}
.gal-tag b {
  color: #8bc4cf;
  font-size: 0.62rem;
}
.gal-score-reason {
  padding: 0.35rem 0.45rem;
  border-radius: 6px;
  background: rgba(61, 168, 130, 0.1);
  color: #baf1d7;
  font-size: 0.72rem;
  line-height: 1.45;
  white-space: pre-wrap;
}
.gal-section {
  padding: 0.42rem 0.48rem;
  border-radius: 7px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(15, 23, 42, 0.38);
}
.gal-section-title {
  display: block;
  margin-bottom: 0.18rem;
  color: #8bc4cf;
  font-size: 0.66rem;
  font-weight: 800;
}
.gal-section p {
  color: rgba(226, 232, 240, 0.94);
  white-space: pre-wrap;
}
.galgame-scene :deep(strong),
.gal-dialogue :deep(strong) {
  color: #f8fafc;
  font-weight: 800;
}
.galgame-scene :deep(code),
.gal-dialogue :deep(code) {
  padding: 0.02rem 0.22rem;
  border-radius: 4px;
  background: rgba(2, 6, 23, 0.36);
  color: #b8edf3;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.72rem;
}
.gal-section.thought {
  background: rgba(107, 127, 215, 0.12);
}
.gal-section.third-party {
  background: rgba(100, 116, 139, 0.12);
}
.gal-section.gal-state {
  background: rgba(2, 6, 23, 0.24);
}
.gal-dialogue {
  padding: 0.15rem 0.12rem 0;
  color: #f8fafc;
  font-size: 0.84rem;
  font-weight: 650;
  line-height: 1.58;
  white-space: pre-wrap;
}
.gal-options {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  margin-top: 0.5rem;
}
.gal-option {
  display: block;
  padding: 0.34rem 0.5rem;
  border-radius: 7px;
  border: 1px solid rgba(139, 196, 207, 0.24);
  background: rgba(139, 196, 207, 0.08);
  color: #d9fbff;
  font-size: 0.73rem;
  line-height: 1.42;
}
.message-row.muted .message-bubble {
  opacity: 0.58;
  border-style: dashed;
}
.message-row.selected .message-bubble {
  border-color: rgba(139, 196, 207, 0.9);
  box-shadow:
    0 0 0 2px rgba(139, 196, 207, 0.22),
    0 8px 20px rgba(2, 6, 23, 0.28);
}
.message-row.selected .message-bubble::after {
  content: '已选择';
  display: inline-block;
  margin-top: 0.28rem;
  padding: 0.03rem 0.28rem;
  border-radius: 4px;
  background: rgba(139, 196, 207, 0.18);
  color: #b8edf3;
  font-size: 0.64rem;
  line-height: 1.4;
}
.message-bubble p {
  margin: 0;
}
.message-image {
  display: block;
  max-width: 100%;
  border-radius: 6px;
  margin-bottom: 0.45rem;
}
.empty-message {
  color: rgba(226, 232, 240, 0.72);
}
.message-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  margin-top: 0.25rem;
  color: rgba(226, 232, 240, 0.68);
  font-size: 0.64rem;
  white-space: nowrap;
}
.message-sender {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.message-time {
  flex-shrink: 0;
}
.message-flag {
  margin-top: 0.25rem;
  color: #fecaca;
  font-size: 0.68rem;
}
.empty-cell {
  text-align: center;
  color: var(--text-muted);
  padding: 2rem 0.75rem;
}
.t {
  font-weight: 500;
}
.tiny {
  font-size: 0.7rem;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.78rem;
}
.nowrap {
  white-space: nowrap;
  font-size: 0.78rem;
}
.btn-sm {
  padding: 0.25rem 0.45rem;
  font-size: 0.75rem;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

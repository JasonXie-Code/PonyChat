<template>
  <div class="section-root logs-root">
    <p v-if="error" class="card card--error">{{ error }}</p>

    <div class="card logs-toolbar">
      <div class="toolbar-main">
        <div class="preset-tabs" aria-label="时间范围">
          <button
            v-for="p in timePresets"
            :key="p.key"
            type="button"
            class="preset-btn"
            :class="{ active: activePreset === p.key }"
            @click="applyPreset(p.key)"
          >
            {{ p.label }}
          </button>
        </div>

        <label class="control-field">
          <span>日期</span>
          <input v-model="filter.date" type="date" @change="onDateChanged" />
        </label>

        <label class="control-field control-hour">
          <span>小时</span>
          <select v-model="filter.hour" :disabled="!filter.date" @change="markCustomTime">
            <option value="">全天</option>
            <option v-for="h in hourOptions" :key="h" :value="h">{{ h }}:00</option>
          </select>
        </label>

        <label class="control-field control-status">
          <span>状态</span>
          <select v-model="filter.status">
            <option value="">全部状态</option>
            <option v-for="s in statusOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>

        <label class="control-field control-model">
          <span>模型</span>
          <select v-model="filter.model">
            <option value="">全部模型</option>
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </select>
        </label>

        <div class="toolbar-spacer" />

        <div class="search-wrap">
          <ion-icon name="search-outline" class="search-icon" aria-hidden="true" />
          <input
            ref="kwInputRef"
            v-model="filter.keyword"
            type="text"
            class="search-input"
            placeholder="搜索 prompt / response / requestId / 错误"
            autocomplete="off"
            @input="onKeywordInput"
            @keydown.enter.prevent="fetchList(true)"
          />
          <button
            v-if="filter.keyword"
            type="button"
            class="search-clear"
            aria-label="清空搜索"
            @click="clearKeyword"
          >
            <ion-icon name="close-outline" aria-hidden="true" />
          </button>
        </div>

        <button type="button" class="btn btn-sm" :disabled="loading || summaryLoading" @click="refresh">
          <ion-icon name="refresh-outline" aria-hidden="true" />
          刷新
        </button>
        <button type="button" class="btn btn-sm" :disabled="exporting" @click="exportLogs">
          <ion-icon name="download-outline" aria-hidden="true" />
          {{ exporting ? '导出中' : '导出' }}
        </button>
      </div>

      <div class="toolbar-sub">
        <button type="button" class="btn btn-sm btn-ghost" @click="advOpen = !advOpen">
          <ion-icon :name="advOpen ? 'chevron-up-outline' : 'options-outline'" aria-hidden="true" />
          {{ advOpen ? '收起条件' : '更多条件' }}
        </button>

        <label class="sort-select">
          <span>排序</span>
          <select v-model="sortMode">
            <option v-for="s in sortOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>

        <div class="active-filter-chips" aria-label="当前筛选">
          <button
            v-for="chip in activeChips"
            :key="chip.key"
            type="button"
            class="filter-chip"
            :title="`移除 ${chip.label}`"
            @click="clearChip(chip.key)"
          >
            <span>{{ chip.label }}</span>
            <ion-icon name="close-outline" aria-hidden="true" />
          </button>
          <span v-if="!activeChips.length" class="muted filter-empty">当前仅按时间范围筛选</span>
        </div>

        <button type="button" class="btn btn-sm btn-ghost" @click="resetFilters">
          <ion-icon name="return-up-back-outline" aria-hidden="true" />
          重置
        </button>

        <span class="muted summary-text">{{ summaryText }}</span>
      </div>

      <div v-if="advOpen" class="advanced-grid">
        <label class="control-field">
          <span>起始</span>
          <input v-model="filter.from" type="datetime-local" @change="markCustomTime" />
        </label>
        <label class="control-field">
          <span>结束</span>
          <input v-model="filter.to" type="datetime-local" @change="markCustomTime" />
        </label>
        <label class="control-field">
          <span>用户</span>
          <input v-model.trim="filter.userId" type="text" placeholder="用户名 / ID" />
        </label>
        <label class="control-field">
          <span>会话</span>
          <input v-model.trim="filter.conversationId" type="text" placeholder="conversationId" />
        </label>
        <label class="control-field">
          <span>请求</span>
          <input v-model.trim="filter.requestId" type="text" placeholder="requestId" />
        </label>
        <label class="control-field">
          <span>链路</span>
          <input v-model.trim="filter.traceId" type="text" placeholder="traceId" />
        </label>
        <label class="control-field">
          <span>供应商</span>
          <input v-model.trim="filter.provider" type="text" placeholder="provider" />
        </label>
        <label class="control-field compact-number">
          <span>延迟 ≥</span>
          <input v-model.number="filter.minLatency" type="number" min="0" placeholder="ms" />
        </label>
        <label class="control-field compact-number">
          <span>延迟 ≤</span>
          <input v-model.number="filter.maxLatency" type="number" min="0" placeholder="ms" />
        </label>
        <label class="control-field compact-number">
          <span>Token ≥</span>
          <input v-model.number="filter.minTokens" type="number" min="0" placeholder="total" />
        </label>
        <label class="control-field compact-number">
          <span>Token ≤</span>
          <input v-model.number="filter.maxTokens" type="number" min="0" placeholder="total" />
        </label>
      </div>
    </div>

    <div class="card card-fill logs-workbench">
      <section class="browser-pane">
        <header class="pane-head browser-head">
          <div>
            <strong>日志浏览</strong>
            <span class="muted">{{ listCaption }}</span>
          </div>
          <div class="browser-head-actions">
            <label class="summary-range">
              <span>索引</span>
              <select v-model.number="summaryHours" @change="loadSummary">
                <option v-for="opt in summaryHourOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </label>
            <button
              type="button"
              class="btn btn-sm btn-icon"
              title="刷新时间索引"
              :disabled="summaryLoading"
              @click="loadSummary"
            >
              <ion-icon name="reload-outline" aria-hidden="true" />
            </button>
          </div>
        </header>

        <div class="browser-body">
          <aside class="time-index">
            <div class="index-stat-strip">
              <div>
                <strong>{{ formatNumber(summaryStats.total) }}</strong>
                <span>总量</span>
              </div>
              <div>
                <strong class="danger-text">{{ formatNumber(summaryStats.errors) }}</strong>
                <span>异常</span>
              </div>
            </div>

            <div class="time-index-head">
              <button type="button" class="btn btn-sm btn-ghost" @click="selectRecent">
                <ion-icon name="flash-outline" aria-hidden="true" />
                最近日志
              </button>
              <button type="button" class="btn btn-sm btn-ghost" @click="toggleAllDays">
                <ion-icon :name="allDaysExpanded ? 'contract-outline' : 'expand-outline'" aria-hidden="true" />
              </button>
            </div>

            <div v-if="summaryLoading" class="time-index-state">
              <span class="spin" />
              <span>加载时间索引...</span>
            </div>
            <div v-else-if="summary.days?.length" class="time-tree">
              <button
                type="button"
                class="time-node time-node-recent"
                :class="{ active: !filter.date && activePreset !== 'custom' }"
                @click="selectRecent"
              >
                <span class="node-label">最近范围</span>
                <span class="node-count">{{ activePresetLabel }}</span>
              </button>

              <template v-for="day in summary.days" :key="day.date">
                <button
                  type="button"
                  class="time-node time-node-day"
                  :class="{ active: filter.date === day.date && !filter.hour }"
                  @click="selectDayAndToggle(day.date)"
                >
                  <ion-icon
                    :name="expandedDays[day.date] ? 'chevron-down-outline' : 'chevron-forward-outline'"
                    class="node-chevron"
                    aria-hidden="true"
                    @click.stop="selectDayAndToggle(day.date)"
                  />
                  <span class="node-label">{{ day.date }}</span>
                  <span class="node-count">{{ formatNumber(day.total) }}</span>
                  <span v-if="day.errors" class="node-badge">{{ formatNumber(day.errors) }}</span>
                </button>

                <template v-if="expandedDays[day.date]">
                  <button
                    v-for="h in day.hours"
                    :key="`${day.date}-${h.hour}`"
                    type="button"
                    class="time-node time-node-hour"
                    :class="{ active: filter.date === day.date && filter.hour === h.hour }"
                    @click="selectHour(day.date, h.hour)"
                  >
                    <span class="hour-rail" />
                    <span class="node-label">{{ h.hour }}:00</span>
                    <span class="node-count">{{ formatNumber(h.total) }}</span>
                    <span v-if="h.errors" class="node-badge">{{ formatNumber(h.errors) }}</span>
                  </button>
                </template>
              </template>
            </div>
            <div v-else class="time-index-state">
              <ion-icon name="folder-open-outline" aria-hidden="true" />
              <span>暂无索引数据</span>
            </div>
          </aside>

          <main class="list-pane">
            <div class="log-grid-head">
              <span class="col-status">状态</span>
              <span class="col-model">模型</span>
              <span class="col-user">用户</span>
              <span class="col-latency">延迟</span>
              <span class="col-tokens">Token</span>
              <span class="col-time">时间</span>
              <span class="col-request">请求</span>
            </div>

            <div v-if="loading && !items.length" class="list-skeleton">
              <div v-for="i in 10" :key="i" class="skeleton-row">
                <span class="skel-dot" />
                <span class="skel-line wide" />
                <span class="skel-line" />
                <span class="skel-line short" />
                <span class="skel-line" />
              </div>
            </div>

            <div v-else-if="!loading && !items.length" class="list-empty">
              <ion-icon name="document-text-outline" aria-hidden="true" />
              <strong>没有匹配日志</strong>
              <span class="muted">换一个时间段，或减少筛选条件后重试。</span>
            </div>

            <div v-else ref="listViewportRef" class="log-viewport" @scroll="onListScroll">
              <div :style="{ height: totalListHeight + 'px' }" class="log-canvas">
                <button
                  v-for="(row, i) in visibleItems"
                  :key="row.id"
                  type="button"
                  class="log-row"
                  :class="[
                    statusTone(row.status),
                    { selected: selectedId === row.id },
                  ]"
                  :style="{ transform: `translateY(${visibleOffsets[i]}px)` }"
                  @click="openDetail(row)"
                >
                  <span class="col-status">
                    <span class="status-dot" :class="statusClass(row.status)" />
                    <span>{{ statusLabel(row.status) }}</span>
                  </span>
                  <span class="col-model admin-mono" :title="row.model">{{ row.model || 'unknown' }}</span>
                  <span class="col-user" :title="row.username || row.userId">{{ row.username || row.userId || '-' }}</span>
                  <span class="col-latency admin-mono" :class="{ hot: row.latencyMs >= 5000 }">{{ fmtLatency(row.latencyMs) }}</span>
                  <span class="col-tokens admin-mono">{{ fmtTokens(row) }}</span>
                  <span class="col-time admin-mono">{{ fmtTimeCompact(row.timestamp) }}</span>
                  <span class="col-request admin-mono" :title="row.requestId || row.traceId">
                    {{ row.requestId || row.traceId || `#${row.id}` }}
                  </span>
                </button>
              </div>
            </div>

            <div class="list-footer">
              <span v-if="loadingMore" class="muted footer-state"><span class="spin spin-sm" />加载更多...</span>
              <span v-else class="muted footer-state">{{ hasMore ? '滚到底部自动加载更多' : '已到当前结果末尾' }}</span>
              <button type="button" class="btn btn-sm btn-ghost" :disabled="!hasMore || loadingMore" @click="loadMore">
                加载更多
              </button>
            </div>
          </main>
        </div>
      </section>

      <aside class="detail-pane">
        <header class="pane-head detail-head">
          <div class="detail-title-wrap">
            <span v-if="selectedRow || detail" class="status-dot detail-dot" :class="statusClass((detail || selectedRow).status)" />
            <div>
              <strong>日志详情</strong>
              <span class="muted detail-subtitle">{{ detailSubtitle }}</span>
            </div>
          </div>
          <div class="detail-actions">
            <button type="button" class="btn btn-sm" :disabled="!detail" @click="copyDetailPart('request')">
              <ion-icon name="copy-outline" aria-hidden="true" />
              请求
            </button>
            <button type="button" class="btn btn-sm" :disabled="!detail" @click="copyDetailPart('response')">
              <ion-icon name="copy-outline" aria-hidden="true" />
              响应
            </button>
            <button type="button" class="btn btn-sm" :disabled="!detail" @click="downloadDetail">
              <ion-icon name="download-outline" aria-hidden="true" />
              JSON
            </button>
          </div>
        </header>

        <div v-if="detailLoading" class="detail-state">
          <span class="spin" />
          <span>读取原始日志...</span>
        </div>

        <div v-else-if="detailError" class="detail-state detail-state-error">
          <ion-icon name="warning-outline" aria-hidden="true" />
          <strong>详情读取失败</strong>
          <span>{{ detailError }}</span>
        </div>

        <div v-else-if="!detail" class="detail-state detail-empty">
          <ion-icon name="analytics-outline" aria-hidden="true" />
          <strong>选择一条日志</strong>
          <span>这里会固定显示请求、响应、参数和原始 JSON，不再以侧边抽屉遮挡列表。</span>
        </div>

        <div v-else class="detail-scroll">
          <section class="detail-block overview-block">
            <div class="detail-block-head">
              <h3>概览</h3>
              <span class="badge" :class="badgeClass(detail.status)">{{ statusLabel(detail.status) }}</span>
            </div>
            <div class="meta-grid">
              <div class="meta-item">
                <span>模型</span>
                <strong class="admin-mono">{{ detail.model || '-' }}</strong>
              </div>
              <div class="meta-item">
                <span>用户</span>
                <strong>{{ detail.username || detail.userId || '-' }}</strong>
              </div>
              <div class="meta-item">
                <span>时间</span>
                <strong class="admin-mono">{{ fmtTime(detail.timestamp) }}</strong>
              </div>
              <div class="meta-item">
                <span>阶段</span>
                <strong>{{ detail.stage || '-' }}</strong>
              </div>
              <div class="meta-item">
                <span>延迟</span>
                <strong class="admin-mono" :class="{ hot: detail.latencyMs >= 5000 }">{{ fmtLatency(detail.latencyMs) }}</strong>
              </div>
              <div class="meta-item">
                <span>Total Token</span>
                <strong class="admin-mono">{{ formatNumber(detail.totalTokens) }}</strong>
              </div>
              <div class="meta-item">
                <span>Prompt</span>
                <strong class="admin-mono">{{ formatNumber(detail.promptTokens) }}</strong>
              </div>
              <div class="meta-item">
                <span>Completion</span>
                <strong class="admin-mono">{{ formatNumber(detail.completionTokens) }}</strong>
              </div>
              <div class="meta-item meta-wide">
                <span>requestId</span>
                <strong class="admin-mono break-all">{{ detail.requestId || selectedRow?.requestId || '-' }}</strong>
              </div>
              <div class="meta-item meta-wide">
                <span>会话</span>
                <strong class="admin-mono break-all">{{ detail.conversationId || selectedRow?.conversationId || '-' }}</strong>
              </div>
            </div>

            <div class="focus-actions">
              <button type="button" class="btn btn-sm btn-ghost" :disabled="!detail.username" @click="focusUser(detail.username)">
                同用户
              </button>
              <button
                type="button"
                class="btn btn-sm btn-ghost"
                :disabled="!(detail.conversationId || selectedRow?.conversationId)"
                @click="focusConversation(detail.conversationId || selectedRow?.conversationId)"
              >
                同会话
              </button>
              <button
                type="button"
                class="btn btn-sm btn-ghost"
                :disabled="!(detail.requestId || selectedRow?.requestId)"
                @click="copyText(detail.requestId || selectedRow?.requestId, '已复制 requestId')"
              >
                复制 requestId
              </button>
            </div>
          </section>

          <AgentLogDetails :key="selectedId" :detail="detail" @trace="focusTrace" />

          <section v-if="detail.errorCode || detail.errorMessage" class="detail-block error-block">
            <div class="detail-block-head">
              <h3>错误</h3>
              <span v-if="detail.errorCode" class="admin-mono">{{ detail.errorCode }}</span>
            </div>
            <LogValue :value="detail.errorMessage || detail.raw?.data?.error" />
          </section>

          <section class="detail-block">
            <div class="detail-block-head">
              <h3>请求消息</h3>
              <button type="button" class="inline-action" @click="copyDetailPart('request')">复制</button>
            </div>
            <div v-if="requestMessages.length" class="message-stack">
              <article
                v-for="(m, i) in visibleRequestMessages"
                :key="`${roleLabel(m.role)}-${i}`"
                class="message-card"
                :class="roleClass(m.role)"
              >
                <div class="message-role">{{ roleLabel(m.role) }}</div>
                <LogValue :value="m.content ?? m" />
              </article>
            </div>
            <LogValue v-else :value="detail.request" />
            <div v-if="requestMessages.length > 10">
              <button class="btn btn-sm" :disabled="messagePage === 0" @click="messagePage--">上一页消息</button>
              <span>{{ messagePage + 1 }} / {{ Math.ceil(requestMessages.length / 10) }}</span>
              <button class="btn btn-sm" :disabled="(messagePage + 1) * 10 >= requestMessages.length" @click="messagePage++">下一页消息</button>
            </div>
          </section>

          <section class="detail-block">
            <div class="detail-block-head">
              <h3>响应内容</h3>
              <button type="button" class="inline-action" @click="copyDetailPart('response')">复制</button>
            </div>
            <div v-if="responseText" class="response-readable">
              <LogValue :value="responseText" />
            </div>
            <LogValue :key="selectedId" :value="detail.response" collapsible label="响应 JSON" />
          </section>

          <section class="detail-block">
            <LogValue :key="selectedId" :value="detail.raw || detail" collapsible label="原始 JSON" />
          </section>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { fetchLlmLogDetail, fetchLlmLogs, fetchLlmLogSummary } from '../../../api/admin'
import { toast } from '../../../composables/useToast'
import AgentLogDetails from './AgentLogDetails.vue'
import LogValue from './LogValue.vue'

const HOUR_MS = 60 * 60 * 1000
const ROW_H = 46
const BUFFER = 8
const DEFAULT_LIMIT = 100

const error = ref('')
const loading = ref(false)
const loadingMore = ref(false)
const summaryLoading = ref(false)
const exporting = ref(false)
const advOpen = ref(false)
const allDaysExpanded = ref(false)
const activePreset = ref('recent-24h')
const sortMode = ref('time_desc')
const summaryHours = ref(8760)
const kwInputRef = ref(null)
const listViewportRef = ref(null)

const filter = reactive({
  date: '',
  hour: '',
  from: toLocalInput(new Date(Date.now() - 24 * HOUR_MS)),
  to: '',
  keyword: '',
  model: '',
  status: '',
  provider: '',
  userId: '',
  conversationId: '',
  requestId: '',
  traceId: '',
  minLatency: '',
  maxLatency: '',
  minTokens: '',
  maxTokens: '',
})

const summary = ref({ days: [] })
const expandedDays = reactive({})
const items = shallowRef([])
const cursor = ref(null)
const hasMore = ref(false)
const selectedId = ref(null)
const detail = shallowRef(null)
const detailError = ref('')
const detailLoading = ref(false)
const scrollTop = ref(0)
const viewportH = ref(620)

let keywordTimer = null
let resizeObserver = null
let suppressFilterWatch = false
let listRequestSeq = 0
let detailRequestSeq = 0

const timePresets = [
  { key: 'recent-1h', label: '近 1 小时' },
  { key: 'recent-24h', label: '近 24 小时' },
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
]

const statusOptions = [
  { value: 'success', label: '成功' },
  { value: 'error', label: '失败' },
  { value: 'timeout', label: '超时' },
  { value: 'interrupted', label: '流式中断' },
]

const sortOptions = [
  { value: 'time_desc', label: '时间倒序' },
  { value: 'errors_first', label: '异常优先' },
  { value: 'latency_desc', label: '耗时最高' },
  { value: 'tokens_desc', label: 'Token 最高' },
]

const summaryHourOptions = [
  { value: 24, label: '24 小时' },
  { value: 168, label: '7 天' },
  { value: 720, label: '30 天' },
  { value: 2160, label: '90 天' },
  { value: 8760, label: '全年' },
]

const hourOptions = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))

const modelOptions = computed(() => {
  const set = new Set(items.value.map((x) => x.model).filter(Boolean))
  if (filter.model) set.add(filter.model)
  return [...set].sort((a, b) => a.localeCompare(b))
})

const selectedRow = computed(() => items.value.find((x) => x.id === selectedId.value) || null)

const totalListHeight = computed(() => items.value.length * ROW_H)
const visibleRange = computed(() => {
  const start = Math.max(0, Math.floor(scrollTop.value / ROW_H) - BUFFER)
  const count = Math.ceil(viewportH.value / ROW_H) + BUFFER * 2
  return { start, count }
})
const visibleItems = computed(() => {
  const { start, count } = visibleRange.value
  return items.value.slice(start, start + count)
})
const visibleOffsets = computed(() => {
  const { start } = visibleRange.value
  return visibleItems.value.map((_, i) => (start + i) * ROW_H)
})

const summaryStats = computed(() => {
  const days = summary.value.days || []
  return {
    total: days.reduce((sum, day) => sum + Number(day.total || 0), 0),
    errors: days.reduce((sum, day) => sum + Number(day.errors || 0), 0),
  }
})

const summaryText = computed(() => {
  const loaded = items.value.length
  const suffix = hasMore.value ? '，还有更多' : ''
  if (loading && !loaded) return '正在查询...'
  return `已载入 ${formatNumber(loaded)} 条${suffix}`
})

const listCaption = computed(() => {
  if (filter.date && filter.hour) return `${filter.date} ${filter.hour}:00`
  if (filter.date) return `${filter.date} 全天`
  return activePresetLabel.value
})

const activePresetLabel = computed(() => {
  return timePresets.find((x) => x.key === activePreset.value)?.label || '自定义'
})

const activeChips = computed(() => {
  const chips = []
  const push = (key, label, value) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      chips.push({ key, label: `${label}: ${value}` })
    }
  }
  push('keyword', '关键词', filter.keyword)
  push('model', '模型', filter.model)
  push('status', '状态', statusLabel(filter.status))
  push('provider', '供应商', filter.provider)
  push('userId', '用户', filter.userId)
  push('conversationId', '会话', filter.conversationId)
  push('requestId', '请求', filter.requestId)
  push('traceId', '链路', filter.traceId)
  push('minLatency', '延迟≥', filter.minLatency)
  push('maxLatency', '延迟≤', filter.maxLatency)
  push('minTokens', 'Token≥', filter.minTokens)
  push('maxTokens', 'Token≤', filter.maxTokens)
  return chips.filter((chip) => !chip.label.endsWith(': 全部状态') && !chip.label.endsWith(': 未知'))
})

const detailSubtitle = computed(() => {
  const row = detail.value || selectedRow.value
  if (!row) return '固定详情区'
  return row.requestId || row.traceId || `#${row.id}`
})

const requestMessages = computed(() => {
  const req = detail.value?.request
  const raw = detail.value?.raw
  const candidates = [
    req?.messages,
    req?.params?.messages,
    req?.body?.messages,
    raw?.params?.messages,
    raw?.data?.messages,
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate
  }
  if (req?.prompt != null) {
    return [
      ...(req.system_prompt ? [{ role: 'system', content: req.system_prompt }] : []),
      { role: 'user', content: req.prompt },
    ]
  }
  return []
})

const messagePage = ref(0)
const visibleRequestMessages = computed(() => requestMessages.value.slice(messagePage.value * 10, (messagePage.value + 1) * 10))
watch(selectedId, () => { messagePage.value = 0 })
const responseText = computed(() => extractResponseText(detail.value?.response))

watch(
  () => [
    filter.date,
    filter.hour,
    filter.from,
    filter.to,
    filter.model,
    filter.status,
    filter.provider,
    filter.userId,
    filter.conversationId,
    filter.requestId,
    filter.traceId,
    filter.minLatency,
    filter.maxLatency,
    filter.minTokens,
    filter.maxTokens,
    sortMode.value,
  ],
  () => {
    if (!suppressFilterWatch) fetchList(true)
  },
)

function runFilterUpdate(fn) {
  suppressFilterWatch = true
  fn()
  nextTick(() => {
    suppressFilterWatch = false
    fetchList(true)
  })
}

function buildQuery(useCursor = false) {
  const q = {}
  if (filter.date) q.date = filter.date
  if (filter.date && filter.hour) q.hour = filter.hour
  if (!filter.date && filter.from) q.from = localInputToIso(filter.from)
  if (!filter.date && filter.to) q.to = localInputToIso(filter.to)
  if (filter.keyword) q.keyword = filter.keyword.trim()
  if (filter.model) q.model = filter.model
  if (filter.status) q.status = filter.status
  if (filter.provider) q.provider = filter.provider
  if (filter.userId) q.userId = filter.userId
  if (filter.conversationId) q.conversationId = filter.conversationId
  if (filter.requestId) q.requestId = filter.requestId
  if (filter.traceId) q.traceId = filter.traceId
  if (hasValue(filter.minLatency)) q.minLatency = filter.minLatency
  if (hasValue(filter.maxLatency)) q.maxLatency = filter.maxLatency
  if (hasValue(filter.minTokens)) q.minTokens = filter.minTokens
  if (hasValue(filter.maxTokens)) q.maxTokens = filter.maxTokens
  if (sortMode.value) q.sort = sortMode.value
  if (useCursor && cursor.value) q.cursor = cursor.value
  q.limit = DEFAULT_LIMIT
  return q
}

async function loadSummary() {
  summaryLoading.value = true
  try {
    const data = await fetchLlmLogSummary({ hours: summaryHours.value })
    summary.value = data || { days: [] }
    const recentDays = (summary.value.days || []).slice(0, 3)
    for (const day of recentDays) expandedDays[day.date] = true
  } catch (e) {
    console.error('加载日志摘要失败', e)
  } finally {
    summaryLoading.value = false
  }
}

async function fetchList(reset = false) {
  const seq = ++listRequestSeq
  if (reset) {
    cursor.value = null
    items.value = []
    scrollTop.value = 0
    if (listViewportRef.value) listViewportRef.value.scrollTop = 0
    loading.value = true
  } else {
    loadingMore.value = true
  }
  error.value = ''

  try {
    const data = await fetchLlmLogs(buildQuery(!reset))
    if (seq !== listRequestSeq) return

    const newItems = data?.items || []
    items.value = reset ? newItems : [...items.value, ...newItems]
    cursor.value = data?.nextCursor || null
    hasMore.value = Boolean(data?.hasMore)

    if (reset) {
      const first = items.value[0]
      if (first) {
        await openDetail(first, { keepListState: true })
      } else {
        selectedId.value = null
        detail.value = null
        detailError.value = ''
      }
    }
  } catch (e) {
    if (seq === listRequestSeq) error.value = e?.data?.detail || e.message || '日志加载失败'
  } finally {
    if (seq === listRequestSeq) {
      loading.value = false
      loadingMore.value = false
      nextTick(updateViewportHeight)
    }
  }
}

async function loadMore() {
  if (!hasMore.value || loadingMore.value || loading.value) return
  await fetchList(false)
}

async function refresh() {
  await Promise.all([loadSummary(), fetchList(true)])
}

async function openDetail(row) {
  if (!row?.id) return
  selectedId.value = row.id
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  const seq = ++detailRequestSeq
  try {
    const data = await fetchLlmLogDetail(row.id)
    if (seq !== detailRequestSeq) return
    detail.value = {
      ...row,
      ...data,
      conversationId: data?.conversationId || row.conversationId || '',
      traceId: data?.traceId || row.traceId || '',
      userId: data?.userId || row.userId || '',
    }
  } catch (e) {
    if (seq !== detailRequestSeq) return
    detailError.value = e?.data?.detail || e.message || '详情读取失败'
  } finally {
    if (seq === detailRequestSeq) detailLoading.value = false
  }
}

async function exportLogs() {
  exporting.value = true
  try {
    const qs = new URLSearchParams(buildQuery(false))
    const resp = await fetch(`/api/admin/llm-logs/export?${qs}`)
    if (!resp.ok) throw new Error('导出失败')
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `llm-logs-export-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('导出已开始')
  } catch (e) {
    toast.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

function applyPreset(key) {
  activePreset.value = key
  runFilterUpdate(() => {
    filter.date = ''
    filter.hour = ''
    filter.to = ''
    const now = new Date()
    if (key === 'recent-1h') {
      filter.from = toLocalInput(new Date(now.getTime() - HOUR_MS))
    } else if (key === 'recent-24h') {
      filter.from = toLocalInput(new Date(now.getTime() - 24 * HOUR_MS))
    } else if (key === 'today') {
      filter.date = dateValue(now)
      filter.from = ''
    } else if (key === 'yesterday') {
      const y = new Date(now)
      y.setDate(now.getDate() - 1)
      filter.date = dateValue(y)
      filter.from = ''
    }
  })
}

function selectRecent() {
  applyPreset('recent-24h')
}

function selectDay(date) {
  activePreset.value = 'custom'
  runFilterUpdate(() => {
    filter.date = date
    filter.hour = ''
    filter.from = ''
    filter.to = ''
  })
}

function selectDayAndToggle(date) {
  expandedDays[date] = !expandedDays[date]
  selectDay(date)
}

function selectHour(date, hour) {
  activePreset.value = 'custom'
  runFilterUpdate(() => {
    filter.date = date
    filter.hour = hour
    filter.from = ''
    filter.to = ''
  })
}

function onDateChanged() {
  markCustomTime()
  if (!filter.date) filter.hour = ''
  if (filter.date) {
    filter.from = ''
    filter.to = ''
  }
}

function markCustomTime() {
  activePreset.value = 'custom'
}

function toggleDay(date) {
  expandedDays[date] = !expandedDays[date]
}

function toggleAllDays() {
  const expand = !allDaysExpanded.value
  allDaysExpanded.value = expand
  for (const day of summary.value.days || []) {
    expandedDays[day.date] = expand
  }
}

function onKeywordInput() {
  clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => fetchList(true), 350)
}

function clearKeyword() {
  filter.keyword = ''
  clearTimeout(keywordTimer)
  fetchList(true)
  nextTick(() => kwInputRef.value?.focus())
}

function clearChip(key) {
  if (!(key in filter)) return
  if (key === 'keyword') {
    clearKeyword()
    return
  }
  runFilterUpdate(() => {
    filter[key] = ''
    if (key === 'date') filter.hour = ''
  })
}

function resetFilters() {
  activePreset.value = 'recent-24h'
  runFilterUpdate(() => {
    Object.assign(filter, {
      date: '',
      hour: '',
      from: toLocalInput(new Date(Date.now() - 24 * HOUR_MS)),
      to: '',
      keyword: '',
      model: '',
      status: '',
      provider: '',
      userId: '',
      conversationId: '',
      requestId: '',
      traceId: '',
      minLatency: '',
      maxLatency: '',
      minTokens: '',
      maxTokens: '',
    })
    sortMode.value = 'time_desc'
  })
}

function focusUser(username) {
  if (!username) return
  advOpen.value = true
  filter.userId = username
}

function focusConversation(conversationId) {
  if (!conversationId) return
  advOpen.value = true
  filter.conversationId = conversationId
}

function focusTrace(traceId) {
  if (!traceId) return
  advOpen.value = true
  Object.assign(filter, {
    traceId, requestId: '', status: '', model: '', keyword: '', provider: '', userId: '', conversationId: '',
    date: '', hour: '', from: '1970-01-01T00:00', to: '', minLatency: '', maxLatency: '', minTokens: '', maxTokens: '',
  })
}

function onListScroll() {
  const el = listViewportRef.value
  if (!el) return
  scrollTop.value = el.scrollTop
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 220) loadMore()
}

function updateViewportHeight() {
  if (listViewportRef.value) viewportH.value = listViewportRef.value.clientHeight || 620
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== ''
}

function statusClass(status) {
  const map = { success: 'st-ok', error: 'st-err', timeout: 'st-warn', interrupted: 'st-int' }
  return map[status] || 'st-unknown'
}

function statusTone(status) {
  const map = { success: 'tone-ok', error: 'tone-err', timeout: 'tone-warn', interrupted: 'tone-int' }
  return map[status] || 'tone-muted'
}

function badgeClass(status) {
  const map = {
    success: 'badge-success',
    error: 'badge-danger',
    timeout: 'badge-warning',
    interrupted: 'badge-info',
  }
  return map[status] || 'badge-muted'
}

function statusLabel(status) {
  const map = { success: '成功', error: '失败', timeout: '超时', interrupted: '流式中断' }
  return map[status] || (status ? String(status) : '未知')
}

function fmtLatency(ms) {
  if (!Number.isFinite(Number(ms)) || Number(ms) <= 0) return '-'
  const n = Number(ms)
  if (n < 1000) return `${n}ms`
  return `${(n / 1000).toFixed(1)}s`
}

function fmtTokens(row) {
  const total = Number(row?.totalTokens || 0)
  if (total > 0) return formatNumber(total)
  const prompt = Number(row?.promptTokens || 0)
  const completion = Number(row?.completionTokens || 0)
  if (!prompt && !completion) return '-'
  return `${formatNumber(prompt)}/${formatNumber(completion)}`
}

function fmtTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function fmtTimeCompact(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}:${ss}`
}

function formatNumber(value) {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n.toLocaleString() : '0'
}

function roleLabel(role) {
  if (role === 'system') return 'system'
  if (role === 'assistant') return 'assistant'
  if (role === 'tool') return 'tool'
  if (role === 'user') return 'user'
  return role || 'message'
}

function roleClass(role) {
  return `role-${String(role || 'message').replace(/[^a-z0-9_-]/gi, '').toLowerCase()}`
}

function extractResponseText(resp) {
  if (!resp) return ''
  if (typeof resp === 'string') return resp
  if (typeof resp.final_response === 'string') return resp.final_response
  if (typeof resp.content === 'string') return resp.content
  if (typeof resp.text === 'string') return resp.text
  const choice = Array.isArray(resp.choices) ? resp.choices[0] : null
  if (choice?.message?.content) return choice.message.content
  if (choice?.delta?.content) return choice.delta.content
  if (choice?.text) return choice.text
  return ''
}

async function copyText(text, message = '已复制') {
  if (!text) return
  try {
    await navigator.clipboard.writeText(String(text))
    toast.success(message)
  } catch {
    toast.error('复制失败')
  }
}

function serializeLog(value, download = false) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./logExport.worker.js', import.meta.url), { type: 'module' })
    worker.onmessage = ({ data }) => {
      worker.terminate()
      if (data.error) reject(new Error(data.error))
      else resolve(data.result)
    }
    worker.onerror = () => { worker.terminate(); reject(new Error('日志导出失败')) }
    try { worker.postMessage({ value, download }) }
    catch (error) { worker.terminate(); reject(error) }
  })
}

async function copyDetailPart(part) {
  if (!detail.value) return
  const payload = part === 'request' ? detail.value.request : detail.value.response
  try {
    await copyText(await serializeLog(payload), part === 'request' ? '已复制请求' : '已复制响应')
  } catch (error) { toast.error(error.message) }
}

async function downloadDetail() {
  if (!detail.value) return
  const selected = detail.value
  try {
    const blob = await serializeLog(selected.raw || selected, true)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `llm-log-${selected.id || 'detail'}.json`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { toast.error(error.message) }
}

function dateValue(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function toLocalInput(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const h = String(date.getHours()).padStart(2, '0')
  const mi = String(date.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${d}T${h}:${mi}`
}

function localInputToIso(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString()
}

onMounted(() => {
  loadSummary()
  fetchList(true)
  nextTick(updateViewportHeight)
  resizeObserver = new ResizeObserver(updateViewportHeight)
  if (listViewportRef.value) resizeObserver.observe(listViewportRef.value)
})

onBeforeUnmount(() => {
  clearTimeout(keywordTimer)
  if (resizeObserver) resizeObserver.disconnect()
})
</script>


<style scoped src="./styles/ConversationLogsSection.css"></style>

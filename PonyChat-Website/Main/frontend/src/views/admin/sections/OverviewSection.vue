<template>
  <div class="overview section-root section-scrollable">
    <div v-if="error" class="card card--error">{{ error }}</div>
    <template v-else>
      <div class="stat-grid">
        <div v-for="s in statCards" :key="s.k" class="card stat-card">
          <div class="stat-card-inner">
            <div class="stat-icon" :style="{ background: s.gradient }">
              <ion-icon :name="s.ion" />
            </div>
            <div class="stat-text">
              <div class="stat-val-row">
                <span class="stat-val">{{ s.v }}</span>
                <span v-if="s.delta !== undefined && s.delta !== 0" class="stat-delta" :class="s.delta > 0 ? 'up' : 'down'">
                  {{ s.delta > 0 ? '↑' : '↓' }} {{ Math.abs(s.delta) }}
                </span>
              </div>
              <div class="stat-label">{{ s.label }}</div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="uptimeServices.length" class="card uptime-card">
        <div class="uptime-card-head">
          <h3>服务器正常运行时间</h3>
          <span class="uptime-range">{{ uptime.range_label || '本月' }} · 1 小时/格</span>
        </div>
        <div class="uptime-services">
          <section v-for="svc in uptimeServices" :key="svc.key" class="uptime-service">
            <div class="uptime-service-head">
              <div>
                <div class="uptime-service-title">{{ svc.title }}</div>
                <div class="uptime-service-detail">{{ svc.detail || '等待采样' }}</div>
              </div>
              <div class="uptime-status" :class="{ down: !svc.current_ok }">
                {{ svc.status_label || (svc.current_ok ? '运行中' : '异常') }}
              </div>
            </div>
            <div class="uptime-main-row">
              <div class="uptime-current">
                <span class="uptime-value">{{ svc.current_ok ? svc.current_uptime_text : '中断' }}</span>
                <span class="uptime-label">当前连续运行</span>
              </div>
              <div class="uptime-current">
                <span class="uptime-value">{{ uptimePercent(svc.month_ratio) }}</span>
                <span class="uptime-label">已采样可用率</span>
              </div>
              <div class="uptime-current">
                <span class="uptime-value">{{ fmtCount(svc.total_response_count) }}</span>
                <span class="uptime-label">累计响应次数</span>
              </div>
              <div class="uptime-current">
                <span class="uptime-value">{{ fmtCount(svc.today_response_count) }}</span>
                <span class="uptime-label">当天响应次数</span>
              </div>
            </div>
            <div class="uptime-heatmap" :aria-label="svc.title + ' 本月可用性'">
              <span
                v-for="hour in uptimeSlots(svc)"
                :key="svc.key + hour.hour"
                class="uptime-hour"
                :class="'status-' + (hour.status || 'unknown')"
                :style="heatCellStyle(hour)"
                :aria-label="hourTooltip(hour)"
              >
                <span class="uptime-tooltip" :style="chartTooltipVars" role="tooltip">
                  <span class="uptime-tooltip-title">{{ hourLabel(hour) }}</span>
                  <span class="uptime-tooltip-body">
                    <i :style="{ background: heatTooltipColor(hour) }" />
                    <span>可用率: {{ uptimePercentCompact(hour?.ratio) }}</span>
                  </span>
                </span>
              </span>
            </div>
            <div class="uptime-legend">
              <span><i class="legend-up" />正常</span>
              <span><i class="legend-partial" />部分</span>
              <span><i class="legend-down" />异常</span>
              <span><i class="legend-unknown" />未采样</span>
            </div>
          </section>
        </div>
      </div>

      <div class="charts">
        <div class="card chart-box">
          <h3>用户增长趋势（7 日）</h3>
          <div class="chart-canvas-wrap">
            <canvas ref="elUsers"></canvas>
          </div>
        </div>
        <div class="card chart-box">
          <h3>消息活跃趋势（7 日）</h3>
          <div class="chart-canvas-wrap">
            <canvas ref="elMsgs"></canvas>
          </div>
        </div>
        <div class="card chart-box">
          <h3>Token 用量趋势（7 日）</h3>
          <div class="chart-canvas-wrap">
            <canvas ref="elTokens"></canvas>
          </div>
        </div>
        <div class="card chart-box">
          <h3>Token 用量 Top 10（累计）</h3>
          <div class="chart-canvas-wrap">
            <canvas ref="elTop"></canvas>
          </div>
        </div>
      </div>

      <div class="tables-row">
        <div class="card table-card">
          <h3 class="table-title">服务器运行状态</h3>
          <table class="data-table admin-data-table">
            <tbody>
              <tr>
                <td class="k">CPU</td>
                <td>{{ sys.cpu_percent != null ? sys.cpu_percent + '%' : '—' }}</td>
              </tr>
              <tr>
                <td class="k">内存</td>
                <td>
                  {{ sys.memory_used_mb != null ? sys.memory_used_mb + ' / ' + sys.memory_total_mb + ' MB' : '—' }}
                  <span v-if="sys.memory_percent != null" class="muted">（{{ sys.memory_percent }}%）</span>
                </td>
              </tr>
              <tr>
                <td class="k">磁盘</td>
                <td>
                  {{ sys.disk_percent != null ? '已用 ' + sys.disk_percent + '%' : '—' }}
                  <span v-if="sys.disk_free_gb != null" class="muted"> · 剩余 {{ sys.disk_free_gb }} GB</span>
                </td>
              </tr>
              <tr>
                <td class="k">WebSocket 连接</td>
                <td>{{ sys.active_users ?? '—' }}</td>
              </tr>
              <tr>
                <td class="k">角色总数</td>
                <td>{{ sys.total_characters ?? sys.active_conversations ?? '—' }}</td>
              </tr>
              <tr>
                <td class="k">消息总数</td>
                <td>{{ sys.total_messages ?? stats.total_conversations ?? '—' }}</td>
              </tr>
              <tr>
                <td class="k">数据库占用</td>
                <td>{{ sys.storage_usage ?? '—' }}</td>
              </tr>
              <tr>
                <td class="k">当前模型</td>
                <td>{{ sys.active_model ?? '—' }}</td>
              </tr>
              <tr>
                <td class="k">接口响应</td>
                <td>{{ sys.response_time != null ? sys.response_time + ' ms' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card table-card">
          <h3 class="table-title">Token 统计</h3>
          <table class="data-table admin-data-table">
            <tbody>
              <tr>
                <td class="k">今日大模型调用次数</td>
                <td>{{ stats.today_llm_calls ?? stats.today_chats ?? 0 }}</td>
              </tr>
              <tr>
                <td class="k">今日输入</td>
                <td>{{ fmtNum(tokenSummary.today_input_tokens) }}</td>
              </tr>
              <tr>
                <td class="k">今日输出</td>
                <td>{{ fmtNum(tokenSummary.today_output_tokens) }}</td>
              </tr>
              <tr>
                <td class="k">今日 Token 合计</td>
                <td><strong>{{ fmtNum(tokenSummary.today_total_tokens) }}</strong></td>
              </tr>
              <tr class="sep-row">
                <td colspan="2" class="muted tiny">以下为累计（自统计写入以来）</td>
              </tr>
              <tr>
                <td class="k">累计输入</td>
                <td>{{ fmtNum(tokenSummary.cumulative_input_tokens) }}</td>
              </tr>
              <tr>
                <td class="k">累计输出</td>
                <td>{{ fmtNum(tokenSummary.cumulative_output_tokens) }}</td>
              </tr>
              <tr>
                <td class="k">累计 Token 合计</td>
                <td><strong>{{ fmtNum(tokenSummary.cumulative_total_tokens) }}</strong></td>
              </tr>
              <tr class="sep-row">
                <td colspan="2" class="muted tiny">费用统计（输入 ¥2/百万 · 输出 ¥10/百万）</td>
              </tr>
              <tr>
                <td class="k">今日费用</td>
                <td>{{ fmtCost(tokenSummary.today_cost_cny) }}</td>
              </tr>
              <tr>
                <td class="k">累计费用</td>
                <td>{{ fmtCost(tokenSummary.cumulative_cost_cny) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { fetchStats, fetchSystemStatus, fetchUptimeHeatmap } from '../../../api/admin'
import {
  getAdminChartDefaults,
  getAdminChartTooltipVars,
  lineDatasetStyle,
  attachChartHoverCursor,
} from '../../../composables/useAdminChart'
import '../../../styles/admin-shell.css'

const G1 = 'linear-gradient(135deg, #9f86d6 0%, #4ebfcf 100%)'
const G2 = 'linear-gradient(135deg, #c9a0b2 0%, #4ebfcf 100%)'
const G3 = 'linear-gradient(135deg, #8b9fe0 0%, #42c49a 100%)'
const G4 = 'linear-gradient(135deg, #42c49a 0%, #4ebfcf 100%)'

const error = ref('')
const statCards = ref([])
const sys = ref({})
const stats = ref({})
const tokenSummary = ref({})
const uptime = ref({ services: [], days: 30 })
const chartTooltipVars = getAdminChartTooltipVars()

const elUsers = ref(null)
const elMsgs = ref(null)
const elTokens = ref(null)
const elTop = ref(null)

let chartUsers = null
let chartMsgs = null
let chartTokens = null
let chartTop = null
let unhook1 = () => {}
let unhook2 = () => {}
let unhook3 = () => {}
let unhook4 = () => {}

let pollTimer = null
let chartJsReady = false
let chartResizeObserver = null
let chartResizeRaf = 0
let chartWindowResizeAttached = false

const uptimeServices = computed(() => (Array.isArray(uptime.value?.services) ? uptime.value.services : []))

function frame() {
  return new Promise((resolve) => requestAnimationFrame(resolve))
}

async function waitForChartLayout() {
  await nextTick()
  await frame()
  await frame()
}

function liveCharts() {
  return [chartUsers, chartMsgs, chartTokens, chartTop].filter(Boolean)
}

function scheduleChartResize() {
  if (chartResizeRaf) cancelAnimationFrame(chartResizeRaf)
  chartResizeRaf = requestAnimationFrame(() => {
    chartResizeRaf = 0
    for (const chart of liveCharts()) {
      chart.resize()
      chart.update('none')
    }
  })
}

function bindChartResizeObserver() {
  const wrappers = [elUsers, elMsgs, elTokens, elTop]
    .map((r) => r.value?.parentElement)
    .filter(Boolean)

  if (typeof ResizeObserver === 'undefined') {
    if (!chartWindowResizeAttached) {
      window.addEventListener('resize', scheduleChartResize)
      chartWindowResizeAttached = true
    }
    return
  }

  chartResizeObserver?.disconnect()
  chartResizeObserver = new ResizeObserver(scheduleChartResize)
  wrappers.forEach((el) => chartResizeObserver.observe(el))
}

function fmtNum(n) {
  if (n == null || Number.isNaN(n)) return '0'
  return Number(n).toLocaleString('zh-CN')
}

function fmtCount(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return fmtNum(Number(n))
}

function fmtCost(n) {
  if (n == null || Number.isNaN(Number(n))) return '¥0.00'
  const x = Number(n)
  if (x > 0 && x < 0.01) return `¥${x.toFixed(4)}`
  return `¥${x.toFixed(2)}`
}

function uptimePercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value) * 1000) / 10}%`
}

function uptimePercentCompact(value) {
  if (value == null || Number.isNaN(Number(value))) return '未采样'
  return `${Math.round(Number(value) * 100)}%`
}

function uptimeSlots(svc) {
  if (Array.isArray(svc?.hours)) return svc.hours
  if (Array.isArray(svc?.days)) return svc.days
  return []
}

function hourLabel(hour) {
  const value = String(hour?.hour || '')
  const m = value.match(/^\d{4}-(\d{1,2})-(\d{1,2})T(\d{1,2}):/)
  if (m) return `${Number(m[1])}月${Number(m[2])}日${Number(m[3])}点`
  return hour?.label || value || ''
}

function hourTooltip(hour) {
  return `${hourLabel(hour)} ${uptimePercentCompact(hour?.ratio)}`
}

function heatCellStyle(slot) {
  const status = slot?.status || 'unknown'
  const ratio = Number(slot?.ratio ?? 0)
  if (status === 'up') {
    const alpha = 0.36 + Math.max(0, Math.min(1, ratio)) * 0.52
    return { backgroundColor: `rgba(66, 196, 154, ${alpha})`, borderColor: 'rgba(66, 196, 154, 0.7)' }
  }
  if (status === 'partial') {
    const alpha = 0.34 + Math.max(0, Math.min(1, ratio)) * 0.38
    return { backgroundColor: `rgba(220, 180, 92, ${alpha})`, borderColor: 'rgba(220, 180, 92, 0.7)' }
  }
  if (status === 'down') {
    return { backgroundColor: 'rgba(216, 90, 112, 0.68)', borderColor: 'rgba(216, 90, 112, 0.75)' }
  }
  return { backgroundColor: 'rgba(148, 163, 184, 0.12)', borderColor: 'rgba(148, 163, 184, 0.2)' }
}

function heatTooltipColor(slot) {
  const status = slot?.status || 'unknown'
  if (status === 'up') return '#42c49a'
  if (status === 'partial') return '#dcb45c'
  if (status === 'down') return '#d85a70'
  return '#64748b'
}

function buildStatCards(data, deltas) {
  const d = deltas || {}
  return [
    { k: 'u', label: '总用户', v: data.total_users, delta: d.users_vs_yesterday, ion: 'people-outline', gradient: G1 },
    { k: 'c', label: '总角色', v: data.total_characters, ion: 'planet-outline', gradient: G2 },
    { k: 'm', label: '总消息数', v: data.total_conversations, delta: d.msgs_vs_yesterday, ion: 'chatbubble-ellipses-outline', gradient: G3 },
    { k: 'a', label: '当前在线连接', v: data.active_users, ion: 'flash-outline', gradient: G4 },
  ]
}

async function load() {
  error.value = ''
  try {
    const [data, status, uptimeData] = await Promise.all([
      fetchStats(),
      fetchSystemStatus(),
      fetchUptimeHeatmap(30, 'month'),
    ])
    stats.value = data
    sys.value = status
    uptime.value = uptimeData || { services: [], days: 30 }
    tokenSummary.value = data.token_summary || {}
    statCards.value = buildStatCards(data, data.deltas)

    const { Chart, registerables } = await import('chart.js')
    if (!chartJsReady) {
      Chart.register(...registerables)
      chartJsReady = true
    }
    const base = getAdminChartDefaults()
    const labels = data.charts?.dates || []
    const uTrend = data.charts?.user_trend || []
    const cTrend = data.charts?.conversation_trend || []
    const tTrend = data.charts?.token_trend || []
    const topList = data.top_token_users || []

    const dsUsers = {
      label: '新注册用户',
      data: uTrend,
      ...lineDatasetStyle('#9f86d6', true),
    }
    const dsMsgs = {
      label: '消息数',
      data: cTrend,
      ...lineDatasetStyle('#42c49a', true),
    }
    const dsTok = {
      label: 'Token 合计',
      data: tTrend,
      ...lineDatasetStyle('#5cb0c8', true),
    }

    await waitForChartLayout()

    if (!chartUsers && elUsers.value) {
      chartUsers = new Chart(elUsers.value.getContext('2d'), {
        type: 'line',
        data: { labels, datasets: [dsUsers] },
        options: base,
      })
      unhook1 = attachChartHoverCursor(chartUsers)
    } else if (chartUsers) {
      chartUsers.data.labels = labels
      chartUsers.data.datasets[0].data = uTrend
      chartUsers.update()
    }

    if (!chartMsgs && elMsgs.value) {
      chartMsgs = new Chart(elMsgs.value.getContext('2d'), {
        type: 'line',
        data: { labels, datasets: [dsMsgs] },
        options: base,
      })
      unhook2 = attachChartHoverCursor(chartMsgs)
    } else if (chartMsgs) {
      chartMsgs.data.labels = labels
      chartMsgs.data.datasets[0].data = cTrend
      chartMsgs.update()
    }

    if (!chartTokens && elTokens.value) {
      chartTokens = new Chart(elTokens.value.getContext('2d'), {
        type: 'line',
        data: { labels, datasets: [dsTok] },
        options: base,
      })
      unhook3 = attachChartHoverCursor(chartTokens)
    } else if (chartTokens) {
      chartTokens.data.labels = labels
      chartTokens.data.datasets[0].data = tTrend
      chartTokens.update()
    }

    const topLabels = topList.map((x) => x.username)
    const topData = topList.map((x) => x.total_tokens)
    const optTop = {
      ...getAdminChartDefaults(),
      indexAxis: 'y',
      interaction: {
        mode: 'index',
        intersect: false,
        axis: 'y',
      },
      hover: {
        mode: 'index',
        intersect: false,
        axis: 'y',
      },
      scales: {
        x: {
          ticks: { color: '#94a3b8' },
          grid: { color: 'rgba(148, 163, 184, 0.12)' },
          beginAtZero: true,
        },
        y: {
          ticks: { color: '#94a3b8' },
          grid: { color: 'rgba(148, 163, 184, 0.12)' },
        },
      },
    }

    if (!chartTop && elTop.value) {
      chartTop = new Chart(elTop.value.getContext('2d'), {
        type: 'bar',
        data: {
          labels: topLabels,
          datasets: [
            {
              label: '累计 Token',
              data: topData,
              backgroundColor: 'rgba(159, 134, 214, 0.32)',
              borderColor: '#9f86d6',
              borderWidth: 1,
            },
          ],
        },
        options: optTop,
      })
      unhook4 = attachChartHoverCursor(chartTop)
    } else if (chartTop) {
      chartTop.data.labels = topLabels
      chartTop.data.datasets[0].data = topData
      chartTop.update()
    }
    bindChartResizeObserver()
    scheduleChartResize()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(() => {
  load()
  pollTimer = setInterval(load, 30000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (chartResizeRaf) cancelAnimationFrame(chartResizeRaf)
  chartResizeObserver?.disconnect()
  if (chartWindowResizeAttached) {
    window.removeEventListener('resize', scheduleChartResize)
  }
  unhook1()
  unhook2()
  unhook3()
  unhook4()
  chartUsers?.destroy()
  chartMsgs?.destroy()
  chartTokens?.destroy()
  chartTop?.destroy()
})
</script>

<style scoped>
.section-root {
  min-height: 0;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.stat-card {
  padding: 0.85rem 1rem;
}
.stat-val-row {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.stat-delta {
  font-size: 0.75rem;
  font-weight: 600;
}
.stat-delta.up {
  color: #6fb894;
}
.stat-delta.down {
  color: #d88080;
}
.uptime-card {
  margin-bottom: 1rem;
  padding: 1rem;
}
.uptime-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.9rem;
}
.uptime-card-head h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  font-family: var(--font-display);
}
.uptime-range {
  color: var(--text-muted, #94a3b8);
  font-size: 0.78rem;
  white-space: nowrap;
}
.uptime-services {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.uptime-service {
  min-width: 0;
  padding-top: 0.1rem;
}
.uptime-service + .uptime-service {
  border-left: 1px solid rgba(148, 163, 184, 0.14);
  padding-left: 1rem;
}
.uptime-service-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  min-height: 48px;
}
.uptime-service-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-primary, #e2e8f0);
}
.uptime-service-detail {
  margin-top: 0.2rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.76rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: min(520px, 100%);
}
.uptime-status {
  flex: 0 0 auto;
  border: 1px solid rgba(66, 196, 154, 0.35);
  background: rgba(66, 196, 154, 0.15);
  color: #7de2b8;
  border-radius: 999px;
  padding: 0.18rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 700;
}
.uptime-status.down {
  border-color: rgba(216, 90, 112, 0.4);
  background: rgba(216, 90, 112, 0.16);
  color: #f0a2ad;
}
.uptime-main-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.55rem;
  margin: 0.75rem 0;
}
.uptime-current {
  min-width: 0;
  background: rgba(15, 23, 42, 0.22);
  border: 1px solid rgba(148, 163, 184, 0.11);
  border-radius: 8px;
  padding: 0.52rem 0.58rem;
}
.uptime-value {
  display: block;
  color: var(--text-primary, #e2e8f0);
  font-size: 0.94rem;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.uptime-label {
  display: block;
  margin-top: 0.22rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.68rem;
  line-height: 1.25;
}
.uptime-heatmap {
  display: grid;
  grid-template-columns: repeat(72, minmax(0, 1fr));
  gap: 0.14rem;
  margin-top: 0.25rem;
}
.uptime-hour {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 2px;
  cursor: crosshair;
  position: relative;
  transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
}
.uptime-hour:hover,
.uptime-hour:focus-visible {
  border-color: rgba(226, 232, 240, 0.72);
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.7), 0 0 0 3px rgba(66, 196, 154, 0.16);
  transform: scale(1.25);
  z-index: 12;
}
.uptime-tooltip {
  --uptime-tooltip-scale: 0.67;
  background: var(--admin-chart-tooltip-bg);
  border: 1px solid var(--admin-chart-tooltip-border);
  border-radius: var(--admin-chart-tooltip-radius);
  box-shadow: 0 12px 30px rgba(2, 6, 23, 0.38);
  color: var(--admin-chart-tooltip-body);
  display: grid;
  gap: 0.42rem;
  left: 50%;
  min-width: 8.9rem;
  opacity: 0;
  padding: var(--admin-chart-tooltip-padding);
  pointer-events: none;
  position: absolute;
  bottom: calc(100% + 0.55rem);
  transform: translate(-50%, 0.25rem) scale(var(--uptime-tooltip-scale));
  transform-origin: center bottom;
  transition: opacity 0.12s ease, transform 0.12s ease, visibility 0.12s ease;
  visibility: hidden;
  white-space: nowrap;
  z-index: 30;
}
.uptime-tooltip::after {
  background: var(--admin-chart-tooltip-bg);
  border-bottom: 1px solid var(--admin-chart-tooltip-border);
  border-right: 1px solid var(--admin-chart-tooltip-border);
  bottom: -0.32rem;
  content: '';
  height: 0.55rem;
  left: 50%;
  position: absolute;
  transform: translateX(-50%) rotate(45deg);
  width: 0.55rem;
}
.uptime-hour:hover .uptime-tooltip,
.uptime-hour:focus-visible .uptime-tooltip {
  opacity: 1;
  transform: translate(-50%, 0) scale(var(--uptime-tooltip-scale));
  visibility: visible;
}
.uptime-tooltip-title {
  color: var(--admin-chart-tooltip-title);
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.15;
}
.uptime-tooltip-body {
  align-items: center;
  color: var(--admin-chart-tooltip-body);
  display: inline-flex;
  font-size: 0.78rem;
  gap: 0.36rem;
  line-height: 1.2;
}
.uptime-tooltip-body i {
  display: inline-block;
  height: 0.72rem;
  width: 0.72rem;
}
.uptime-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 0.65rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.72rem;
}
.uptime-legend span {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
}
.uptime-legend i {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 3px;
  display: inline-block;
}
.legend-up {
  background: rgba(66, 196, 154, 0.82);
}
.legend-partial {
  background: rgba(220, 180, 92, 0.68);
}
.legend-down {
  background: rgba(216, 90, 112, 0.72);
}
.legend-unknown {
  background: rgba(148, 163, 184, 0.18);
}
.charts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  margin-bottom: 1rem;
}
.chart-box h3 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  font-weight: 600;
  font-family: var(--font-display);
}
.chart-canvas-wrap {
  height: 280px;
  position: relative;
}
.chart-canvas-wrap canvas {
  display: block;
  width: 100% !important;
  height: 100% !important;
}
.tables-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.table-title {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  font-weight: 600;
}
.data-table {
  width: 100%;
  font-size: 0.875rem;
}
.data-table td {
  padding: 0.5rem 0.65rem;
}
.data-table td.k {
  width: 160px;
  color: var(--text-muted, #94a3b8);
}
.sep-row td {
  padding-top: 0.75rem;
  font-size: 0.75rem;
}
.tiny {
  font-size: 0.75rem;
}
@media (max-width: 960px) {
  .uptime-services {
    grid-template-columns: 1fr;
  }
  .uptime-service + .uptime-service {
    border-left: 0;
    border-top: 1px solid rgba(148, 163, 184, 0.14);
    padding-left: 0;
    padding-top: 1rem;
  }
  .uptime-heatmap {
    grid-template-columns: repeat(48, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .uptime-main-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

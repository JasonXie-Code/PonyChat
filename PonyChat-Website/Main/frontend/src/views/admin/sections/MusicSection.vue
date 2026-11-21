<template>
  <div class="music section-root section-scrollable">
    <div class="toolbar card">
      <div><h3>音乐站运营统计</h3><p class="muted">访客、收听与流量 · 北京时间</p></div>
      <div class="filters">
        <label>日期范围 <select v-model="preset" @change="load"><option value="1">今日</option><option value="7">近 7 天</option><option value="30">近 30 天</option><option value="custom">自定义</option></select></label>
        <template v-if="preset === 'custom'">
          <input v-model="start" type="date" aria-label="开始日期" />
          <span>至</span><input v-model="end" type="date" aria-label="结束日期" />
        </template>
        <button class="btn btn-primary" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新统计' }}</button>
        <a class="btn" href="https://music.ponychat.org" target="_blank" rel="noopener">打开音乐站 ↗</a>
      </div>
    </div>
    <div v-if="error" class="card error" role="alert">{{ error }}</div>
    <p v-if="!data && loading" class="muted" role="status">正在获取音乐站统计…</p>
    <template v-if="data && !error">
      <p class="muted range">{{ data.start }} 至 {{ data.end }} · 更新于 {{ updated }} · 采集开始于 {{ since }}</p>
      <div class="stat-grid">
        <div v-for="card in cards" :key="card.label" class="card metric"><span class="muted">{{ card.label }}</span><strong>{{ card.value }}</strong><small class="muted">{{ card.hint }}</small></div>
      </div>
      <div v-if="!data.traffic.available" class="card warning" role="status">{{ data.traffic.error }}。流量暂不可用，访客和播放统计仍可查看。</div>
      <div class="card chart-card">
        <div class="chart-head"><h3>每日趋势</h3><label>指标 <select v-model="metric"><option value="visitors">访客</option><option value="plays">播放次数</option><option value="seconds">播放分钟</option><option value="bytes">流量 (MiB)</option></select></label></div>
        <p v-if="metric === 'bytes' && !data.traffic.available" class="muted">等待流量日志接入</p>
        <div v-else class="chart"><canvas ref="canvas" role="img" :aria-label="`${data.start} 至 ${data.end}的每日统计趋势，明细见下表`"></canvas></div>
      </div>
      <div class="details">
        <section class="card"><h3>热门歌曲 <small class="muted">按播放次数排序 · 最多 50 首</small></h3>
          <div class="table-wrap"><table><thead><tr><th>歌曲</th><th>播放次数</th><th>听众</th><th>收听分钟</th></tr></thead><tbody>
            <tr v-for="song in data.songs" :key="song.id"><td class="song-title">{{ song.title }}</td><td>{{ count(song.plays) }}</td><td>{{ count(song.listeners) }}</td><td>{{ minutes(song.seconds) }}</td></tr>
            <tr v-if="!data.songs.length"><td colspan="4" class="muted empty">此日期范围暂无播放记录</td></tr>
          </tbody></table></div>
        </section>
        <section class="card"><h3>流量分布</h3><p class="muted">音乐站响应正文 · 含预加载和下载</p>
          <ul v-if="data.traffic.available && data.traffic.categories.length" class="traffic-list"><li v-for="row in data.traffic.categories" :key="row.category"><span>{{ row.category }}<small class="muted">{{ count(row.requests) }} 次请求</small></span><strong>{{ bytes(row.bytes) }}</strong></li></ul>
          <p v-else class="muted empty">{{ data.traffic.available ? '此日期范围暂无流量记录' : '等待流量日志接入' }}</p>
        </section>
      </div>
      <section class="card"><h3>每日明细</h3><div class="table-wrap"><table><thead><tr><th>日期</th><th>访客</th><th>访问次数</th><th>播放次数</th><th>播放分钟</th><th>流量</th></tr></thead><tbody>
        <tr v-for="row in [...data.daily].reverse()" :key="row.date"><td>{{ row.date }}</td><td>{{ count(row.visitors) }}</td><td>{{ count(row.visits) }}</td><td>{{ count(row.plays) }}</td><td>{{ minutes(row.seconds) }}</td><td>{{ data.traffic.available ? bytes(row.bytes) : '—' }}</td></tr>
      </tbody></table></div></section>
      <p class="muted notes">访客按匿名浏览器标识去重，清理浏览器数据或更换设备会产生新访客；访问次数按页面打开计数。实际开始播放才计一次，暂停后继续不重复计数；播放分钟不包含暂停、缓冲及跳转进度。流量来自 Nginx 实际发送的响应正文，包含音频、乐谱、图片及网页，不包含 TLS 和请求头；浏览器缓存命中不产生服务器流量。统计从采集启用后开始，历史收听数据无法追溯。</p>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import Chart from 'chart.js/auto'
import { fetchMusicStats } from '../../../api/admin'
import { useAdminStore } from '../../../stores/adminStore'

const admin = useAdminStore()
const preset = ref('7'), start = ref(''), end = ref(''), metric = ref('visitors')
const data = ref(null), loading = ref(false), error = ref(''), canvas = ref(null), updated = ref('')
let chart, revision = 0
const count = n => Number(n || 0).toLocaleString('zh-CN')
const minutes = n => (Number(n || 0) / 60).toLocaleString('zh-CN', { maximumFractionDigits: 1 })
function bytes(n) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let value = Number(n || 0), index = 0
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index++ }
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${units[index]}`
}
const since = computed(() => data.value?.since ? new Date(data.value.since).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '—')
const cards = computed(() => {
  const t = data.value.totals
  return [
    { label: '独立访客', value: count(t.visitors), hint: '所选日期范围内去重' },
    { label: '访问次数', value: count(t.visits), hint: '页面打开次数' },
    { label: '播放次数', value: count(t.plays), hint: '实际开始收听的次数' },
    { label: '播放分钟', value: minutes(t.seconds), hint: '实际收听时间' },
    { label: '使用流量', value: data.value.traffic.available ? bytes(t.bytes) : '—', hint: 'Nginx 实际发送字节' },
    { label: '资源请求', value: data.value.traffic.available ? count(t.requests) : '—', hint: '包含预加载和下载' },
  ]
})
async function load() {
  const token = ++revision
  loading.value = true; error.value = ''
  try {
    const params = preset.value === 'custom' ? { start: start.value, end: end.value } : { days: preset.value }
    if (preset.value === 'custom' && (!start.value || !end.value || start.value > end.value)) throw new Error('请选择有效的开始与结束日期')
    const result = await fetchMusicStats(params, admin.username, admin.adminPassword)
    if (token !== revision) return
    data.value = result; updated.value = new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai' })
    if (!start.value) start.value = result.start
    if (!end.value) end.value = result.end
    await nextTick(); draw()
  } catch (e) { if (token === revision) error.value = e.message || '统计加载失败，请重试' }
  finally { if (token === revision) loading.value = false }
}
function draw() {
  chart?.destroy(); chart = null
  if (!canvas.value || !data.value || error.value) return
  const divisor = metric.value === 'seconds' ? 60 : metric.value === 'bytes' ? 1048576 : 1
  chart = new Chart(canvas.value, { type: 'bar', data: { labels: data.value.daily.map(r => r.date.slice(5)), datasets: [{ data: data.value.daily.map(r => r[metric.value] / divisor), backgroundColor: '#a78bfa', borderRadius: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#aab6cb', maxTicksLimit: 14 }, grid: { display: false } }, y: { beginAtZero: true, ticks: { color: '#aab6cb' }, grid: { color: 'rgba(148,163,184,.12)' } } } } })
}
watch(metric, async () => { await nextTick(); draw() })
onMounted(load)
onUnmounted(() => { revision++; chart?.destroy() })
</script>

<style scoped>
.music { display: flex; flex-direction: column; gap: 16px; }
.toolbar, .chart-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
h3, p { margin: 0; } h3 { font-size: 1rem; margin-bottom: 8px; }
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filters input, select { color: var(--text); background: var(--bg-deep); border: 1px solid var(--stroke); border-radius: 6px; padding: 7px; color-scheme: dark; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.metric { display: flex; flex-direction: column; gap: 10px; } .metric strong { font-size: 2rem; font-variant-numeric: tabular-nums; }
.range, .notes { font-size: .8rem; line-height: 1.8; } .error { color: #fca5a5; } .warning { color: #fcd34d; }
.chart { position: relative; height: 220px; } .details { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; align-items: start; }
.table-wrap { overflow-x: auto; max-height: 430px; } table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px 10px; text-align: right; border-bottom: 1px solid var(--stroke); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; } th { color: var(--text-muted); font-weight: 500; } .song-title { max-width: 350px; overflow-wrap: anywhere; }
.empty { text-align: center; padding: 24px; } .traffic-list { list-style: none; padding: 0; margin: 0; }
.traffic-list li { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--stroke); }
.traffic-list small { display: block; margin-top: 5px; } h3 small { font-size: .75rem; font-weight: 400; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .details { grid-template-columns: 1fr; } }
</style>

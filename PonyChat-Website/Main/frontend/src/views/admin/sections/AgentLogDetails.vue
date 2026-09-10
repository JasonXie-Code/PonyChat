<template>
  <section v-if="isAgent" class="agent-log">
    <header>
      <h3>Agent 执行过程</h3>
      <button v-if="detail.traceId" type="button" @click="$emit('trace', detail.traceId)">查看同一链路</button>
    </header>
    <dl>
      <div><dt>链路</dt><dd>{{ detail.traceId || '旧日志未记录' }}</dd></div>
      <div v-if="params.run_number"><dt>执行轮次</dt><dd>{{ params.run_number }}</dd></div>
      <div v-if="data.llm_api_calls != null"><dt>模型调用</dt><dd>{{ data.llm_api_calls }}</dd></div>
      <div v-if="data.tool_call_count != null"><dt>工具调用</dt><dd>{{ data.tool_call_count }}</dd></div>
      <div v-if="data.finish_reason"><dt>结束原因</dt><dd>{{ data.finish_reason }}</dd></div>
      <div v-if="params.parent_stage"><dt>来源阶段</dt><dd>{{ params.parent_stage }}</dd></div>
      <div v-if="data.phase"><dt>阶段</dt><dd>{{ data.phase === 'generation' ? '生成结束（保存结果见同一链路）' : data.phase === 'persistence' ? '对话保存' : data.phase }}</dd></div>
    </dl>
    <p v-if="data.events_dropped" class="warning">事件超过记录上限，省略 {{ data.events_dropped }} 条；请结合 SDK 原始事件查看。</p>
    <p v-if="!events.length">此记录没有中间事件，可通过同一链路查看请求、执行响应及结束记录。</p>
    <ol v-else :start="page * PAGE_SIZE + 1">
      <li v-for="(event, index) in visibleEvents" :key="`${page}-${index}`">
        <details @toggle="opened[index] = $event.target.open">
          <summary>
            <span class="time">{{ event.data?.captured_on_completion ? '结束时补录' : event.elapsed_ms == null ? '—' : `${event.elapsed_ms} ms` }}</span>
            <strong>{{ label(event) }}</strong>
            <span v-if="event.data?.status" :class="{ warning: event.data.status !== 'success' }">{{ statusLabel(event.data.status) }}</span>
          </summary>
          <template v-if="opened[index]">
          <template v-if="event.type === 'tool/execution'">
            <p>耗时 {{ event.data.latency_ms }} ms · HTTP {{ event.data.http_status }}</p>
            <h4>工具参数</h4><LogValue :value="event.data.arguments" />
            <h4>返回结果</h4><LogValue :value="event.data.result" />
            <template v-if="event.data.error"><h4>失败原因</h4><LogValue :value="event.data.error" /></template>
          </template>
          <LogValue v-else :value="event.data" />
          </template>
        </details>
      </li>
    </ol>
    <nav v-if="events.length > PAGE_SIZE" aria-label="事件分页">
      <button :disabled="page === 0" @click="changePage(-1)">上一页事件</button>
      <span>{{ page + 1 }} / {{ Math.ceil(events.length / PAGE_SIZE) }} 页 · {{ events.length }} 条</span>
      <button :disabled="(page + 1) * PAGE_SIZE >= events.length" @click="changePage(1)">下一页事件</button>
    </nav>
    <LogValue v-if="data.sdk_events?.length" :value="data.sdk_events" collapsible :label="`SDK 原始事件（${data.sdk_events.length} 条）`" />
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import LogValue from './LogValue.vue'

const props = defineProps({ detail: { type: Object, required: true } })
defineEmits(['trace'])
const data = computed(() => props.detail.raw?.data || {})
const params = computed(() => props.detail.raw?.params || {})
const isAgent = computed(() => String(props.detail.stage || '').includes('AGENT'))
const events = computed(() => Array.isArray(data.value.events) ? data.value.events : [])
const PAGE_SIZE = 30
const page = ref(0)
const opened = ref({})
const visibleEvents = computed(() => events.value.slice(page.value * PAGE_SIZE, (page.value + 1) * PAGE_SIZE))
function changePage(delta) { page.value += delta; opened.value = {} }
watch(() => props.detail, () => { page.value = 0; opened.value = {} })
const statusLabel = value => ({ success: '成功', error: '失败', timeout: '超时', interrupted: '已取消' }[value] || value)
function label(event) {
  if (event.type === 'tool/execution') return `工具 · ${event.data?.tool || ''}`
  if (event.type === 'tool/start') return `开始调用 · ${event.data?.tool || ''}`
  const names = { 'step/start': '模型步骤开始', 'step/end': '模型步骤结束', 'assistant/message': '模型回复', 'turn/start': '执行开始', 'turn/end': '执行结束' }
  const step = event.data?.step
  return `${names[event.type] || event.type}${step == null ? '' : ` · Step ${step}`}`
}
</script>

<style scoped>
.agent-log { padding: 16px; border: 1px solid var(--admin-border, #ddd); border-radius: 10px; margin-bottom: 16px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
button { background: transparent; color: inherit; border: 1px solid #8886; border-radius: 6px; padding: 6px 10px; cursor: pointer; }
dl { display: grid; gap: 8px; font-size: 12px; }
dl > div { display: flex; gap: 12px; }
dt { min-width: 60px; opacity: .7; }
dd { margin: 0; overflow-wrap: anywhere; }
ol { padding-left: 22px; }
li { padding: 8px 0; border-top: 1px solid #8883; }
summary { cursor: pointer; overflow-wrap: anywhere; }
summary span, summary strong { margin-right: 10px; }
.time { font: 11px monospace; opacity: .7; }
.warning { color: #c96b20; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 420px; overflow: auto; padding: 10px; background: #8881; border-radius: 6px; font-size: 12px; }
h4, p { font-size: 12px; }
</style>

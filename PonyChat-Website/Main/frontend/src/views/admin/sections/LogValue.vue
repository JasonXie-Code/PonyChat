<template>
  <details v-if="collapsible" class="log-value" @toggle="opened = $event.target.open">
    <summary>{{ label }}</summary>
    <template v-if="opened">
      <pre>{{ preview.text }}</pre>
      <p v-if="preview.truncated">当前为截取预览，完整内容请使用顶部 JSON 下载。</p>
    </template>
  </details>
  <div v-else class="log-value">
    <pre>{{ preview.text }}</pre>
    <p v-if="preview.truncated">当前为截取预览，完整内容请使用顶部 JSON 下载。</p>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { logPreview } from './logPreview'
const props = defineProps({ value: {}, collapsible: Boolean, label: { type: String, default: '查看内容' } })
const opened = ref(false)
const preview = computed(() => logPreview(props.value))
</script>
<style scoped>
summary { cursor: pointer; padding: 8px 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 420px; overflow: auto; padding: 10px; background: #8881; border-radius: 6px; font-size: 12px; }
p { font-size: 12px; opacity: .75; }
</style>

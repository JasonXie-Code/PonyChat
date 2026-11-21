<template>
  <div class="creation-root">
    <p v-if="error" class="card" role="alert">{{ error }}</p>
      <div class="card detail">
        <p v-if="opening">加载会话…</p>
        <template v-else-if="selected">
          <header class="toolbar">
            <strong>{{ selected.username }} · {{ selected.character_name }}</strong>
            <button class="btn" :disabled="working" @click="open(selected.id)">刷新</button>
            <button class="btn" @click="exportSession">导出 JSON</button>
            <button class="btn btn-danger-outline" :disabled="working || selected.busy" @click="removeSession">删除会话</button>
          </header>
          <p v-if="selected.busy" role="status">正在生成，请等待完成后刷新再修改。</p>
          <p v-if="selected.last_error" class="muted">{{ selected.last_error }}</p>
          <form class="settings" @submit.prevent="save">
            <label>标题<input v-model="draft.title" required maxlength="80" :disabled="working || selected.busy" /></label>
            <label>创造要求<textarea v-model="draft.instructions" rows="3" maxlength="120000" :disabled="working || selected.busy" /></label>
            <label><input v-model="customSetting" type="checkbox" :disabled="working || selected.busy" /> 使用自定义角色设定</label>
            <label v-if="customSetting">角色设定<textarea v-model="draft.character_setting" rows="5" maxlength="200000" :disabled="working || selected.busy" /></label>
            <button class="btn btn-primary" :disabled="working || selected.busy">保存设定</button>
          </form>
          <details><summary>上下文编排</summary><pre>{{ JSON.stringify(selected.context_layout, null, 2) }}</pre></details>
        </template>
        <p v-else class="muted">选择左侧会话查看完整内容与设定</p>
      </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { creationAdmin } from '../../../api/admin'
import { confirmAsync } from '../../../composables/useConfirm'

const props = defineProps({ sessionId: { type: String, required: true } })
const emit = defineEmits(['changed', 'deleted'])
const selected = ref(null)
const opening = ref(false), working = ref(false), error = ref(''), customSetting = ref(false)
const draft = reactive({ title: '', instructions: '', character_setting: '' })
let detailRequest = 0
function setSelected(data) {
  selected.value = data
  Object.assign(draft, { title: data.title, instructions: data.instructions, character_setting: data.character_setting ?? '' })
  customSetting.value = data.character_setting !== null
}
async function open(id) {
  const request = ++detailRequest
  opening.value = true; error.value = ''
  try { const data = await creationAdmin(`/${encodeURIComponent(id)}`); if (request === detailRequest) setSelected(data) }
  catch (e) { if (request === detailRequest) { selected.value = null; error.value = e.message } }
  finally { if (request === detailRequest) opening.value = false }
}

async function mutate(suffix, method, body) {
  working.value = true; error.value = ''
  try {
    const data = await creationAdmin(`/${encodeURIComponent(selected.value.id)}${suffix}`, method, body)
    if (method === 'DELETE' && !suffix.includes('/messages/')) { selected.value = null; emit('deleted') }
    else setSelected(data)
    emit('changed')
  } catch (e) { error.value = e.message }
  finally { working.value = false }
}
async function save() {
  await mutate('', 'PATCH', { ...draft, character_setting: customSetting.value ? draft.character_setting : null, version: selected.value.version })
}
async function removeSession() {
  const s = selected.value
  if (await confirmAsync({ title: '删除创造会话', message: `永久删除“${s.title}”及全部消息？此操作无法撤销。`, danger: true })) {
    if (selected.value?.id === s.id) await mutate(`?version=${s.version}`, 'DELETE')
  }
}
function exportSession() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(selected.value, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = `creation-${selected.value.id}.json`; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => props.sessionId, open, { immediate: true })
</script>

<style scoped>
.creation-root { overflow: auto; width: 100%; min-height: 0; }
.toolbar, .toolbar form { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.detail { padding: 1rem; min-width: 0; }
.settings { display: grid; gap: .75rem; margin: 1rem 0; }
.settings label { display: grid; gap: .4rem; }
input:not([type=checkbox]), textarea { width: 100%; box-sizing: border-box; color: var(--text); background: var(--bg-deep); border: 1px solid var(--stroke); padding: .6rem; border-radius: .4rem; }
textarea { resize: vertical; }
.message { border-top: 1px solid var(--stroke); padding: 1rem 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.65; }
small { color: var(--text-muted); }
</style>

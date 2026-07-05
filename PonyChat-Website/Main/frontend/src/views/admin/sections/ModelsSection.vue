<template>
  <div class="section-root">
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <span class="muted">当前启用: <strong>{{ cfg.active_model_id || '—' }}</strong></span>
        <div class="toolbar-right">
          <button type="button" class="btn btn-primary" @click="openAdd">新增模型</button>
          <button type="button" class="btn" @click="load">刷新</button>
        </div>
      </div>
      <div ref="tableViewportRef" class="table-wrap table-viewport">
        <table class="model-table admin-data-table">
          <thead>
            <tr>
              <th :style="thStyle('id')" class="col-id th-sortable th-resizable" @click="toggleSort('id')">
                ID {{ sortIcon('id') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('id', e)" @click.stop />
              </th>
              <th :style="thStyle('name')" class="col-name th-sortable th-resizable" @click="toggleSort('name')">
                名称 {{ sortIcon('name') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('name', e)" @click.stop />
              </th>
              <th :style="thStyle('type')" class="col-type th-sortable th-resizable" @click="toggleSort('type')">
                类型 {{ sortIcon('type') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('type', e)" @click.stop />
              </th>
              <th :style="thStyle('endpoint')" class="col-end th-sortable th-resizable" @click="toggleSort('endpoint')">
                Endpoint {{ sortIcon('endpoint') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('endpoint', e)" @click.stop />
              </th>
              <th :style="thStyle('op')" class="col-op">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in pagedItems" :key="m.id" :class="{ active: m.id === cfg.active_model_id }">
              <td class="col-id admin-mono">{{ m.id }}</td>
              <td class="col-name">{{ m.name }}</td>
              <td class="col-type">{{ m.type || m.provider || '—' }}</td>
              <td class="col-end admin-ellipsis" :title="m.endpoint">{{ m.endpoint }}</td>
              <td class="col-op admin-actions">
                <button v-if="m.id !== cfg.active_model_id" type="button" class="btn btn-sm btn-primary" @click="setActive(m.id)">设为当前</button>
                <button type="button" class="btn btn-sm" @click="runTest(m)">测试连接</button>
                <button type="button" class="btn btn-sm" @click="openEdit(m)">编辑</button>
                <button type="button" class="btn btn-sm btn-danger" @click="onDelete(m)">删除</button>
              </td>
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

    <Teleport to="body">
      <div
        v-if="editOpen"
        class="modal-mask admin-shell"
        @mousedown="onBackdropMouseDown"
        @click.self="onBackdropClickSelf"
      >
        <div class="modal card">
          <header class="modal-header">
            <div class="modal-header-left">
              <h3 class="modal-title">{{ isAdd ? '新增模型' : '编辑模型' }}</h3>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="editOpen = false">×</button>
          </header>
          <div class="modal-body">
            <label class="fld"><span>ID</span><input v-model="form.id" :disabled="!isAdd" /></label>
            <label class="fld"><span>名称</span><input v-model="form.name" /></label>
            <label class="fld"><span>类型 (provider)</span><input v-model="form.type" placeholder="openai / xai / ..." /></label>
            <label class="fld"><span>Endpoint</span><input v-model="form.endpoint" /></label>
            <label class="fld">
              <span>API Key（编辑时留空表示不修改）</span>
              <AdminPasswordInput v-model="form.api_key" autocomplete="off" />
            </label>
            <label class="fld fld-last"><span>模型名 model_name</span><input v-model="form.model_name" /></label>
          </div>
          <footer class="modal-footer">
            <div class="modal-actions">
              <button type="button" class="btn" @click="editOpen = false">取消</button>
              <button type="button" class="btn btn-primary" :disabled="saving" @click="saveModel">保存</button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { fetchModelsConfig, saveModelsConfig, testModel } from '../../../api/admin'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { useAdminTableSort, cmpLocale } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { useModalBackdropDismiss } from '../../../composables/useModalBackdropDismiss'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import AdminPasswordInput from '../../../components/admin/AdminPasswordInput.vue'
import '../../../styles/admin-shell.css'

const cfg = reactive({ active_model_id: '', models: [] })
const error = ref('')

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('id', 'asc')

const { startResize, thStyle } = useColResize(
  { id: null, name: null, type: 100, endpoint: null, op: 280 },
  {
    min: 56,
    columnOrder: ['id', 'name', 'type', 'endpoint', 'op'],
    minByKey: { op: 200 },
  },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 48,
  headHeight: 48,
  minRows: 4,
  maxRows: 200,
})

const modelsList = computed(() => {
  const arr = (cfg.models || []).slice()
  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'id') return cmpLocale(a.id, b.id, dir)
    if (sk === 'name') return cmpLocale(a.name, b.name, dir)
    if (sk === 'type') return cmpLocale(a.type || a.provider, b.type || b.provider, dir)
    if (sk === 'endpoint') return cmpLocale(a.endpoint, b.endpoint, dir)
    return 0
  })
  return arr
})
const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(modelsList, viewportRows)

watch([sortKey, sortDir], () => {
  resetPage()
})

const editOpen = ref(false)
const { onBackdropMouseDown, onBackdropClickSelf } = useModalBackdropDismiss(() => {
  editOpen.value = false
})
const isAdd = ref(false)
const saving = ref(false)
const form = ref({
  id: '',
  name: '',
  type: '',
  endpoint: '',
  api_key: '',
  model_name: '',
})

async function load() {
  error.value = ''
  try {
    const data = await fetchModelsConfig()
    cfg.active_model_id = data.active_model_id || ''
    cfg.models = data.models || []
    resetPage()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function setActive(id) {
  try {
    await saveModelsConfig({ action: 'set_active', model_id: id })
    toast.success('已切换当前模型')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function runTest(m) {
  try {
    const r = await testModel({
      provider: m.type || m.provider,
      api_key: m.api_key,
      base_url: m.endpoint,
      model_name: m.model_name || m.id,
    })
    if (r.success) toast.success(r.message || '连接成功')
    else toast.error(r.message || '连接失败')
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

function openAdd() {
  isAdd.value = true
  form.value = {
    id: '',
    name: '',
    type: 'openai',
    endpoint: '',
    api_key: '',
    model_name: '',
  }
  editOpen.value = true
}

function openEdit(m) {
  isAdd.value = false
  form.value = {
    id: m.id,
    name: m.name || '',
    type: m.type || m.provider || '',
    endpoint: m.endpoint || '',
    api_key: '',
    model_name: m.model_name || m.model_id || '',
  }
  editOpen.value = true
}

async function saveModel() {
  saving.value = true
  try {
    if (isAdd.value) {
      const data = {
        id: form.value.id || undefined,
        name: form.value.name,
        type: form.value.type,
        endpoint: form.value.endpoint,
        api_key: form.value.api_key || undefined,
        model_name: form.value.model_name,
        enabled: true,
      }
      await saveModelsConfig({ action: 'add', model_data: data })
      toast.success('已添加模型')
    } else {
      const updates = {
        name: form.value.name,
        type: form.value.type,
        endpoint: form.value.endpoint,
        model_name: form.value.model_name,
      }
      if (form.value.api_key) updates.api_key = form.value.api_key
      await saveModelsConfig({ action: 'update', model_id: form.value.id, updates })
      toast.success('已保存')
    }
    editOpen.value = false
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    saving.value = false
  }
}

async function onDelete(m) {
  if (!(await confirmAsync({ title: '删除模型', message: `删除模型 ${m.id}？`, danger: true }))) return
  try {
    await saveModelsConfig({ action: 'delete', model_id: m.id })
    toast.success('已删除')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
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
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
  gap: 0.5rem;
}
.toolbar-right {
  display: flex;
  gap: 0.5rem;
}
.col-end {
  min-width: 0;
}
.col-op {
  min-width: 200px;
}
.btn-sm {
  padding: 0.25rem 0.45rem;
  font-size: 0.75rem;
}
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 8000;
  background: rgba(15, 23, 42, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.modal {
  width: min(600px, 100%);
  max-height: 90dvh;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  flex-shrink: 0;
}
.modal-header-left {
  min-width: 0;
}
.modal-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  line-height: 1.3;
}
.modal-close {
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  margin: -0.15rem -0.25rem 0 0;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-muted, #94a3b8);
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.modal-close:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text, #e2e8f0);
}
.modal-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1.25rem;
  -webkit-overflow-scrolling: touch;
}
.modal-footer {
  flex-shrink: 0;
  padding: 0.85rem 1.25rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
}
.modal-body .fld > input:not([type='checkbox']):not([type='radio']),
.modal-body .fld > select,
.modal-body .fld > textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.55rem 0.75rem !important;
  resize: vertical;
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}
.fld span {
  color: #cbd5e1;
  font-weight: 500;
}
.fld-last {
  margin-bottom: 0 !important;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0;
}
</style>

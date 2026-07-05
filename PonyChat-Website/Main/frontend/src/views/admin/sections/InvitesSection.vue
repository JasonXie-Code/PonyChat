<template>
  <div class="section-root">
    <p class="card muted">邀请码接口需要管理员密码（与旧版一致，使用登录时保存的密码）。</p>
    <p v-if="!adminStore.adminPassword" class="card card--warning">
      未检测到本地保存的管理员密码，请重新登录管理后台后再试。
    </p>
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <div class="gen">
          <AdminNumberInput v-model="genCount" :min="1" :max="100" :step="1" class="num-inp" />
          <input v-model="genNote" type="text" placeholder="备注（可选）" class="note-inp" />
          <button type="button" class="btn btn-primary" :disabled="loading || !adminStore.adminPassword" @click="generate">
            生成邀请码
          </button>
        </div>
        <button type="button" class="btn" @click="load">刷新列表</button>
      </div>
      <div v-if="stats" class="stats-bar">
        <p class="muted stats-text">
          总计 {{ stats.total }} · 已用 {{ stats.used }} · 可用 {{ stats.available }} · 过期 {{ stats.expired }}
        </p>
      </div>
      <div ref="tableViewportRef" class="table-wrap table-viewport">
        <table class="invite-table admin-data-table">
          <thead>
            <tr>
              <th
                :style="thStyle('code')"
                class="col-code th-sortable th-resizable"
                @click="toggleSort('code')"
              >
                代码 {{ sortIcon('code') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('code', e)" @click.stop />
              </th>
              <th
                :style="thStyle('note')"
                class="col-note th-sortable th-resizable"
                @click="toggleSort('note')"
              >
                备注 {{ sortIcon('note') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('note', e)" @click.stop />
              </th>
              <th
                :style="thStyle('used')"
                class="col-used th-sortable th-resizable"
                @click="toggleSort('used')"
              >
                已用 {{ sortIcon('used') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('used', e)" @click.stop />
              </th>
              <th
                :style="thStyle('exp')"
                class="col-exp th-sortable th-resizable"
                @click="toggleSort('exp')"
              >
                过期 {{ sortIcon('exp') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('exp', e)" @click.stop />
              </th>
              <th :style="thStyle('op')" class="col-op">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pagedItems" :key="row.code">
              <td class="admin-mono col-code">{{ row.code }}</td>
              <td class="col-note">{{ row.note || '—' }}</td>
              <td class="col-used">{{ row.is_used ? '是' : '否' }}</td>
              <td class="col-exp admin-nowrap">{{ fmtDt(row.expires_at) }}</td>
              <td class="col-op">
                <button type="button" class="btn btn-sm" @click="copyCode(row.code)">复制</button>
                <button type="button" class="btn btn-sm btn-danger" @click="del(row.code)">删除</button>
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { fetchInviteCodes, generateInviteCodes, deleteInviteCode } from '../../../api/admin'
import { useAdminStore } from '../../../stores/adminStore'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useAdminTableSort, cmpLocale, cmpNum, fmtDt } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import AdminNumberInput from '../../../components/admin/AdminNumberInput.vue'
import '../../../styles/admin-shell.css'

const adminStore = useAdminStore()
const error = ref('')
const loading = ref(false)
const stats = ref(null)
const codeRows = ref([])
const genCount = ref(1)
const genNote = ref('')

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('code', 'asc')

const { startResize, thStyle } = useColResize(
  { code: 120, note: null, used: 60, exp: 130, op: 140 },
  { min: 48, columnOrder: ['code', 'note', 'used', 'exp', 'op'], minByKey: { op: 96 } },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 48,
  headHeight: 48,
  minRows: 4,
  maxRows: 200,
})

const sortedCodeRows = computed(() => {
  const arr = codeRows.value.slice()
  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'code') return cmpLocale(a.code, b.code, dir)
    if (sk === 'note') return cmpLocale(a.note, b.note, dir)
    if (sk === 'used') return cmpNum(a.is_used ? 1 : 0, b.is_used ? 1 : 0, dir)
    if (sk === 'exp') return cmpLocale(a.expires_at, b.expires_at, dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(sortedCodeRows, viewportRows)

watch([sortKey, sortDir], () => {
  resetPage()
})

async function load() {
  error.value = ''
  if (!adminStore.adminPassword) return
  try {
    const data = await fetchInviteCodes(adminStore.adminPassword)
    stats.value = data.stats || null
    codeRows.value = Array.isArray(data.codes) ? data.codes : []
    resetPage()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function generate() {
  loading.value = true
  error.value = ''
  try {
    await generateInviteCodes(adminStore.adminPassword, genCount.value || 1, genNote.value || undefined)
    toast.success('已生成')
    await load()
  } catch (e) {
    error.value = e.message || String(e)
    toast.error(error.value)
  } finally {
    loading.value = false
  }
}

function copyCode(code) {
  navigator.clipboard.writeText(code).then(
    () => toast.success('已复制'),
    () => toast.error('复制失败')
  )
}

async function del(code) {
  if (!(await confirmAsync({ title: '删除邀请码', message: `删除邀请码 ${code}？`, danger: true }))) return
  try {
    await deleteInviteCode(adminStore.adminPassword, code)
    toast.success('已删除')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

onMounted(() => {
  adminStore.hydrate()
  load()
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
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
}
.gen {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  flex: 1;
}
.note-inp {
  flex: 1;
  max-width: 280px;
}
.stats-bar {
  margin-bottom: 0.75rem;
}
.stats-text {
  margin: 0;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
}
.col-note {
  min-width: 0;
}
.col-op {
  min-width: 96px;
}
.nowrap {
  white-space: nowrap;
  font-size: 0.78rem;
}
.btn-sm {
  padding: 0.25rem 0.45rem;
  font-size: 0.75rem;
  margin-right: 0.25rem;
}
</style>

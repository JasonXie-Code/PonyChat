<template>
  <div class="sys section-root section-scrollable">
    <p v-if="error" class="card card--error">{{ error }}</p>

    <div class="status-grid">
      <div class="card stat-mini">
        <div class="stat-mini-label">后端</div>
        <div class="stat-mini-val">{{ status?.backend_status || '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">WS 连接</div>
        <div class="stat-mini-val">{{ status?.active_users ?? '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">对话表行数</div>
        <div class="stat-mini-val">{{ status?.active_conversations ?? '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">当前模型</div>
        <div class="stat-mini-val small">{{ status?.active_model || '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">数据库文件</div>
        <div class="stat-mini-val small">{{ status?.storage_usage || '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">响应时间</div>
        <div class="stat-mini-val">{{ status?.response_time != null ? status.response_time + ' ms' : '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">CPU</div>
        <div class="stat-mini-val">{{ status?.cpu_percent != null ? status.cpu_percent + '%' : '—' }}</div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">内存</div>
        <div class="stat-mini-val small">
          {{ memLine }}
        </div>
      </div>
      <div class="card stat-mini">
        <div class="stat-mini-label">磁盘</div>
        <div class="stat-mini-val small">{{ diskLine }}</div>
      </div>
    </div>

    <div class="card">
      <h3>修改管理员密码</h3>
      <div class="row">
        <AdminPasswordInput v-model="pwdCurrent" placeholder="当前密码" autocomplete="current-password" class="inp" />
        <AdminPasswordInput v-model="pwdNew" placeholder="新密码" autocomplete="new-password" class="inp" />
        <AdminPasswordInput v-model="pwdNew2" placeholder="确认新密码" autocomplete="new-password" class="inp" />
        <button type="button" class="btn btn-primary" @click="changePwd">保存</button>
      </div>
      <p v-if="pwdMsg" class="muted">{{ pwdMsg }}</p>
    </div>

    <div class="card">
      <h3>数据库备份</h3>
      <div class="row">
        <button type="button" class="btn btn-primary" :disabled="busy" @click="doBackup">立即备份</button>
        <button type="button" class="btn" :disabled="busy" @click="loadBackups">刷新列表</button>
      </div>
      <div v-if="backups.length" class="table-wrap">
        <table class="bk-table admin-data-table">
          <thead>
            <tr>
              <th :style="thStyle('idx')" class="bk-col-idx th-sortable th-resizable" @click="toggleSortBk('idx')">
                # {{ sortIconBk('idx') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('idx', e)" @click.stop />
              </th>
              <th :style="thStyle('name')" class="bk-col-name th-sortable th-resizable" @click="toggleSortBk('name')">
                名称 {{ sortIconBk('name') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('name', e)" @click.stop />
              </th>
              <th :style="thStyle('size')" class="bk-col-size th-sortable th-resizable" @click="toggleSortBk('size')">
                大小 {{ sortIconBk('size') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('size', e)" @click.stop />
              </th>
              <th :style="thStyle('time')" class="bk-col-time th-sortable th-resizable" @click="toggleSortBk('time')">
                时间 {{ sortIconBk('time') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('time', e)" @click.stop />
              </th>
              <th :style="thStyle('op')" class="bk-col-op">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in sortedBackups" :key="b.filename">
              <td class="bk-col-idx">{{ b.index }}</td>
              <td class="mono bk-col-name">{{ b.display_name || b.filename }}</td>
              <td class="bk-col-size">{{ b.size }}</td>
              <td class="nowrap bk-col-time">{{ fmtDt(b.timestamp) }}</td>
              <td class="bk-col-op">
                <button type="button" class="btn btn-sm btn-danger" @click="onRestore(b)">还原</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">暂无备份列表，点击「立即备份」或「刷新列表」</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  fetchSystemStatus,
  changeAdminPassword,
  backupDatabase,
  listBackups,
  restoreDatabase,
} from '../../../api/admin'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import '../../../styles/admin-shell.css'
import { useAdminTableSort, cmpLocale, cmpNum, fmtDt } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import AdminPasswordInput from '../../../components/admin/AdminPasswordInput.vue'

const error = ref('')
const status = ref(null)
const pwdCurrent = ref('')
const pwdNew = ref('')
const pwdNew2 = ref('')
const pwdMsg = ref('')
const backups = ref([])
const busy = ref(false)

const {
  sortKey: bkSortKey,
  sortDir: bkSortDir,
  toggleSort: toggleSortBk,
  sortIcon: sortIconBk,
} = useAdminTableSort('time', 'desc')

const { startResize, thStyle } = useColResize(
  { idx: 44, name: null, size: 90, time: 130, op: 72 },
  { min: 40, columnOrder: ['idx', 'name', 'size', 'time', 'op'], minByKey: { op: 64 } },
)

const sortedBackups = computed(() => {
  const arr = backups.value.slice()
  const dir = bkSortDir.value === 'asc' ? 1 : -1
  const sk = bkSortKey.value
  arr.sort((a, b) => {
    if (sk === 'idx') return cmpNum(a.index, b.index, dir)
    if (sk === 'name') return cmpLocale(a.display_name || a.filename, b.display_name || b.filename, dir)
    if (sk === 'size') return cmpNum(backupSizeBytes(a), backupSizeBytes(b), dir)
    if (sk === 'time') return cmpNum(backupTimeMs(a), backupTimeMs(b), dir)
    return 0
  })
  return arr
})

function backupSizeBytes(b) {
  if (b.size_bytes != null) return Number(b.size_bytes)
  const s = String(b.size ?? '')
  const m = s.match(/([\d.]+)\s*([KMGT]?)\s*B?/i)
  if (!m) return 0
  let n = parseFloat(m[1])
  if (!Number.isFinite(n)) return 0
  const u = (m[2] || '').toUpperCase()
  if (u === 'K') n *= 1024
  else if (u === 'M') n *= 1024 ** 2
  else if (u === 'G') n *= 1024 ** 3
  else if (u === 'T') n *= 1024 ** 4
  return n
}

function backupTimeMs(b) {
  const t = b.timestamp
  if (t == null) return 0
  const n = Number(t)
  if (Number.isFinite(n)) return n > 1e12 ? n : n * 1000
  const d = Date.parse(String(t))
  return Number.isFinite(d) ? d : 0
}

const memLine = computed(() => {
  const s = status.value
  if (!s?.memory_used_mb) return '—'
  return `${s.memory_used_mb} / ${s.memory_total_mb} MB (${s.memory_percent ?? '—'}%)`
})
const diskLine = computed(() => {
  const s = status.value
  if (s?.disk_percent == null) return '—'
  return `已用 ${s.disk_percent}% · 剩余 ${s.disk_free_gb ?? '—'} GB`
})

async function loadStatus() {
  error.value = ''
  try {
    status.value = await fetchSystemStatus()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function changePwd() {
  pwdMsg.value = ''
  if (pwdNew.value !== pwdNew2.value) {
    pwdMsg.value = '两次输入的新密码不一致'
    return
  }
  if ((pwdNew.value || '').length < 4) {
    pwdMsg.value = '新密码至少 4 位'
    return
  }
  try {
    await changeAdminPassword(pwdCurrent.value, pwdNew.value)
    toast.success('密码已更新')
    pwdMsg.value = '已更新（请牢记新密码）'
    pwdCurrent.value = ''
    pwdNew.value = ''
    pwdNew2.value = ''
  } catch (e) {
    pwdMsg.value = e.message || String(e)
    toast.error(pwdMsg.value)
  }
}

async function doBackup() {
  busy.value = true
  try {
    const data = await backupDatabase()
    toast.success(data?.skipped ? '内容无变化，未创建新备份' : '备份完成')
    await loadBackups()
  } catch (e) {
    error.value = e.message || String(e)
    toast.error(error.value)
  } finally {
    busy.value = false
  }
}

async function loadBackups() {
  try {
    const data = await listBackups()
    backups.value = Array.isArray(data.backups) ? data.backups : []
  } catch (e) {
    error.value = e.message || String(e)
    toast.error(error.value)
  }
}

async function onRestore(b) {
  if (
    !(await confirmAsync({
      title: '还原数据库',
      message: `从「${b.display_name || b.filename}」还原？当前数据将被覆盖，服务可能中断。`,
      danger: true,
    }))
  )
    return
  try {
    await restoreDatabase({ backup_index: b.index })
    toast.success('已发起还原（请重启后端使配置生效）')
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

onMounted(() => {
  loadStatus()
  loadBackups()
})
</script>

<style scoped>
.section-root {
  min-height: 0;
}
h3 {
  margin: 0 0 0.65rem;
  font-size: 1rem;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.stat-mini {
  padding: 0.75rem 1rem;
}
.stat-mini-label {
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 0.25rem;
}
.stat-mini-val {
  font-size: 1.1rem;
  font-weight: 600;
}
.stat-mini-val.small {
  font-size: 0.85rem;
  font-weight: 500;
  word-break: break-all;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.5rem;
}
.inp {
  min-width: 160px;
}
.table-wrap {
  overflow-x: auto;
  margin-top: 0.75rem;
}
.bk-table {
  font-size: 0.85rem;
}
.bk-col-name {
  min-width: 0;
}
.bk-col-op {
  min-width: 64px;
}
.bk-table th,
.bk-table td {
  padding: 0.5rem 0.45rem;
}
.mono {
  font-family: Consolas, monospace;
  font-size: 0.78rem;
}
.nowrap {
  white-space: nowrap;
  font-size: 0.78rem;
}
.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
}
</style>

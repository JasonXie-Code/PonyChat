<template>
  <div class="section-root">
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <span class="muted">共 {{ filtered.length }} 个用户</span>
        <div class="toolbar-right">
          <input v-model="search" class="search-input" placeholder="搜索用户名…" />
          <button type="button" class="btn btn-warning" @click="resetAllUsage">重置全员今日积分</button>
          <button type="button" class="btn" @click="load">刷新</button>
        </div>
      </div>
      <div ref="tableViewportRef" class="table-wrap table-viewport">
        <table class="user-table admin-data-table">
          <thead>
            <tr>
              <th :style="thStyle('user')" class="col-user th-sortable th-resizable" @click="toggleSort('user')">
                用户 {{ sortIcon('user') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('user', e)" @click.stop />
              </th>
              <th :style="thStyle('status')" class="col-status th-sortable th-resizable" @click="toggleSort('status')">
                状态 {{ sortIcon('status') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('status', e)" @click.stop />
              </th>
              <th :style="thStyle('mem')" class="col-mem th-sortable th-resizable" @click="toggleSort('mem')">
                会员 {{ sortIcon('mem') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('mem', e)" @click.stop />
              </th>
              <th :style="thStyle('chars')" class="col-count th-sortable th-resizable" @click="toggleSort('chars')">
                角色数 {{ sortIcon('chars') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('chars', e)" @click.stop />
              </th>
              <th :style="thStyle('msgs')" class="col-count th-sortable th-resizable" @click="toggleSort('msgs')">
                消息数 {{ sortIcon('msgs') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('msgs', e)" @click.stop />
              </th>
              <th :style="thStyle('use')" class="col-use th-sortable th-resizable" @click="toggleSort('use')">
                今日积分 {{ sortIcon('use') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('use', e)" @click.stop />
              </th>
              <th :style="thStyle('created')" class="col-reg th-sortable th-resizable" @click="toggleSort('created')">
                注册时间 {{ sortIcon('created') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('created', e)" @click.stop />
              </th>
              <th :style="thStyle('active')" class="col-act th-sortable th-resizable" @click="toggleSort('active')">
                最后活跃 {{ sortIcon('active') }}
                <span class="col-resizer" @mousedown.stop="(e) => startResize('active', e)" @click.stop />
              </th>
              <th :style="thStyle('op')" class="col-op">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in pagedItems" :key="u.username">
              <td class="col-user">
                <span class="uname">{{ u.username }}</span>
                <span v-if="u.is_online" class="badge badge-success">在线</span>
              </td>
              <td class="col-status">
                <span v-if="u.disabled" class="badge badge-danger">已禁用</span>
                <span v-else class="badge badge-info">正常</span>
              </td>
              <td class="col-mem">
                <button type="button" class="btn btn-sm mem-btn" @click="openMembership(u)">
                  {{ u.membership_label || u.membership_type || '—' }}
                </button>
                <span v-if="u.membership_expire_at" class="muted small block">{{ fmtDt(u.membership_expire_at) }}</span>
              </td>
              <td class="col-count">{{ u.character_count ?? 0 }}</td>
              <td class="col-count">{{ u.message_count ?? 0 }}</td>
              <td class="col-use">
                {{ u.used_today ?? 0 }} / {{ u.daily_limit ?? '—' }}
                <span v-if="u.remaining_today != null" class="muted small">余 {{ u.remaining_today }} 分</span>
              </td>
              <td class="col-reg nowrap">{{ fmtDt(u.created_at) }}</td>
              <td class="col-act nowrap">{{ fmtDt(u.last_active) }}</td>
              <td class="col-op actions">
                <button type="button" class="btn btn-sm" @click="openEdit(u)">编辑</button>
                <button v-if="!u.disabled" type="button" class="btn btn-sm" @click="onDisable(u.username)">禁用</button>
                <button v-else type="button" class="btn btn-sm" @click="onEnable(u.username)">启用</button>
                <button type="button" class="btn btn-sm btn-danger" @click="onRemove(u.username)">删除</button>
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
        @mousedown="onEditBackdropMouseDown"
        @click.self="onEditBackdropClickSelf"
      >
        <div class="modal card">
          <header class="modal-header">
            <div class="modal-header-left">
              <h3 class="modal-title">编辑用户</h3>
              <p class="modal-id">{{ editForm.old_username }}</p>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="editOpen = false">×</button>
          </header>
          <div class="modal-body">
            <label class="fld"><span>新用户名（可选）</span><input v-model="editForm.new_username" type="text" /></label>
            <label class="fld"><span>性别</span>
              <select v-model="editForm.gender">
                <option value="male">男</option>
                <option value="female">女</option>
              </select>
            </label>
            <label class="fld fld-last">
              <span>新密码（留空不改）</span>
              <AdminPasswordInput v-model="editForm.new_password" autocomplete="new-password" />
            </label>
          </div>
          <footer class="modal-footer">
            <div class="modal-actions">
              <button type="button" class="btn" @click="editOpen = false">取消</button>
              <button type="button" class="btn btn-primary" :disabled="editSaving" @click="saveEdit">保存</button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="memOpen"
        class="modal-mask admin-shell"
        @mousedown="onMemBackdropMouseDown"
        @click.self="onMemBackdropClickSelf"
      >
        <div class="modal card mem-modal">
          <header class="modal-header">
            <div class="modal-header-left">
              <div class="mem-modal-header">
                <span class="mem-modal-title">会员</span>
                <span class="mem-modal-user">{{ memUsername }}</span>
              </div>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="memOpen = false">×</button>
          </header>
          <div class="modal-body">
            <p v-if="memLoadError" class="card card--error mem-dash-err">{{ memLoadError }}</p>
            <div v-else-if="memInfo" class="mem-dashboard">
              <div class="mem-dash-head">
                <span class="mem-badge-tier">{{ memInfo.membership_label || memInfo.membership_type || '—' }}</span>
                <span class="mem-badge-role">{{ memRoleLabel }}</span>
              </div>
              <p v-if="memQuotaIsAdmin" class="mem-hint mem-hint--accent">
                该账号为<strong>系统管理员</strong>，今日积分不受会员表限制。
              </p>
              <template v-else>
                <div class="mem-stats">
                  <div class="mem-stat">
                    <span class="mem-stat-label">今日已用积分</span>
                    <span class="mem-stat-value">{{ memInfo.used_today ?? 0 }}</span>
                  </div>
                  <div class="mem-stat">
                    <span class="mem-stat-label">每日积分上限</span>
                    <span class="mem-stat-value">{{ memInfo.daily_limit ?? '—' }}</span>
                  </div>
                  <div class="mem-stat">
                    <span class="mem-stat-label">剩余积分</span>
                    <span class="mem-stat-value mem-stat-value--ok">{{ memInfo.remaining ?? '—' }}</span>
                  </div>
                </div>
                <div class="mem-quota-wrap">
                  <div class="mem-quota-bar" aria-hidden="true">
                    <div class="mem-quota-fill" :style="{ width: memQuotaPct + '%' }" />
                  </div>
                  <div class="mem-quota-footer">
                    <span class="mem-quota-caption">今日积分 {{ memQuotaPct }}%</span>
                    <span class="mem-expire-inline">到期：{{ memExpireDisplay }}</span>
                  </div>
                </div>
              </template>
            </div>
            <p v-else class="muted tiny mem-loading">加载中…</p>

            <div class="mem-divider" />

            <div class="mem-form-section">
              <label class="fld">
                <span>会员类型</span>
                <select v-model="memForm.membership_type">
                  <option value="free">免费 (free)</option>
                  <option value="pro">Pro</option>
                  <option value="pro_plus">Pro+</option>
                  <option value="developer">开发者 (developer)</option>
                </select>
              </label>
              <div class="fld">
                <span>到期时间<em class="fld-hint">（留空 = 永久）</em></span>
                <div class="expire-row">
                  <AdminNumberInput
                    v-model="memForm.expire_year"
                    :min="2024"
                    :max="2099"
                    placeholder="年"
                    align="center"
                    class="expire-input"
                  />
                  <span class="expire-sep">/</span>
                  <AdminNumberInput
                    v-model="memForm.expire_month"
                    :min="1"
                    :max="12"
                    placeholder="月"
                    size="sm"
                    align="center"
                    class="expire-input expire-input--sm"
                  />
                  <span class="expire-sep">/</span>
                  <AdminNumberInput
                    v-model="memForm.expire_day"
                    :min="1"
                    :max="31"
                    placeholder="日"
                    size="sm"
                    align="center"
                    class="expire-input expire-input--sm"
                  />
                  <button type="button" class="btn btn-sm expire-clear-btn" @click="clearExpire">永久</button>
                </div>
                <span v-if="memExpirePreview" class="expire-preview">{{ memExpirePreview }}</span>
              </div>
              <label class="fld fld-last">
                <span>备注</span>
                <input v-model="memForm.note" type="text" />
              </label>
            </div>
          </div>
          <footer class="modal-footer">
            <div class="modal-actions">
              <button type="button" class="btn" @click="memOpen = false">关闭</button>
              <button type="button" class="btn" @click="resetUsage">重置今日积分</button>
              <button type="button" class="btn btn-primary" :disabled="memSaving" @click="saveMembership">保存会员</button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { useAdminTableSort, adminTimeMs, cmpLocale, cmpNum, fmtDt } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { useModalBackdropDismiss } from '../../../composables/useModalBackdropDismiss'
import {
  fetchUsers,
  disableUser,
  enableUser,
  deleteUser,
  editUser,
  fetchUserMembership,
  updateUserMembership,
  resetMembershipUsage,
  resetAllMembershipUsage,
} from '../../../api/admin'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import AdminNumberInput from '../../../components/admin/AdminNumberInput.vue'
import AdminPasswordInput from '../../../components/admin/AdminPasswordInput.vue'
import '../../../styles/admin-shell.css'

const route = useRoute()
const router = useRouter()

const users = ref([])
const error = ref('')
const search = ref('')
const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort(
  'created',
  'desc',
  (k) => (k === 'mem' ? 'asc' : 'desc'),
)

const { startResize, thStyle } = useColResize(
  {
    user: 140,
    status: 88,
    mem: 130,
    chars: 92,
    msgs: 110,
    use: 130,
    created: 130,
    active: 130,
    op: 200,
  },
  {
    min: 56,
    columnOrder: ['user', 'status', 'mem', 'chars', 'msgs', 'use', 'created', 'active', 'op'],
    minByKey: { op: 160 },
  },
)

const tableViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(tableViewportRef, {
  rowHeight: 48,
  headHeight: 48,
  minRows: 5,
  maxRows: 200,
})

const filtered = computed(() => {
  let arr = users.value.slice()
  const q = search.value.trim().toLowerCase()
  if (q) arr = arr.filter((u) => (u.username || '').toLowerCase().includes(q))

  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'user') return cmpLocale(a.username, b.username, dir)
    if (sk === 'status') return cmpNum(a.disabled ? 1 : 0, b.disabled ? 1 : 0, dir)
    if (sk === 'mem')
      return cmpLocale(
        a.membership_type || a.membership_label || '',
        b.membership_type || b.membership_label || '',
        dir,
      )
    if (sk === 'chars') return cmpNum(a.character_count ?? 0, b.character_count ?? 0, dir)
    if (sk === 'msgs') return cmpNum(a.message_count ?? 0, b.message_count ?? 0, dir)
    if (sk === 'use') return cmpNum(a.used_today ?? -1, b.used_today ?? -1, dir)
    if (sk === 'created') return cmpNum(adminTimeMs(a.created_at), adminTimeMs(b.created_at), dir)
    if (sk === 'active') return cmpNum(adminTimeMs(a.last_active), adminTimeMs(b.last_active), dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(filtered, viewportRows)

watch([sortKey, sortDir], () => {
  resetPage()
})

const editOpen = ref(false)
const editSaving = ref(false)
const editForm = ref({
  old_username: '',
  new_username: '',
  gender: 'male',
  new_password: '',
})

function openEdit(u) {
  editForm.value = {
    old_username: u.username,
    new_username: u.username,
    gender: u.gender || 'male',
    new_password: '',
  }
  editOpen.value = true
}

async function saveEdit() {
  editSaving.value = true
  try {
    await editUser({
      old_username: editForm.value.old_username,
      new_username: editForm.value.new_username !== editForm.value.old_username ? editForm.value.new_username : undefined,
      gender: editForm.value.gender,
      new_password: editForm.value.new_password || undefined,
    })
    toast.success('用户已更新')
    editOpen.value = false
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    editSaving.value = false
  }
}

const memOpen = ref(false)
const { onBackdropMouseDown: onEditBackdropMouseDown, onBackdropClickSelf: onEditBackdropClickSelf } =
  useModalBackdropDismiss(() => {
    editOpen.value = false
  })
const { onBackdropMouseDown: onMemBackdropMouseDown, onBackdropClickSelf: onMemBackdropClickSelf } =
  useModalBackdropDismiss(() => {
    memOpen.value = false
  })
const memUsername = ref('')
const memInfo = ref(null)
const memLoadError = ref('')
const memSaving = ref(false)
const memForm = ref({ membership_type: 'free', expire_year: null, expire_month: null, expire_day: null, note: '' })

const memRoleLabel = computed(() => {
  const r = memInfo.value?.user_role
  if (r === 'admin') return '系统管理员'
  if (r === 'disabled') return '账号已禁用'
  return '普通用户'
})

const memQuotaIsAdmin = computed(() => {
  const m = memInfo.value
  return m?.membership_type === 'admin' || m?.user_role === 'admin'
})

const memQuotaPct = computed(() => {
  const m = memInfo.value
  if (!m || memQuotaIsAdmin.value) return 0
  const lim = Number(m.daily_limit)
  if (!Number.isFinite(lim) || lim <= 0) return 0
  const used = Number(m.used_today) || 0
  return Math.min(100, Math.round((used / lim) * 100))
})

const memExpireDisplay = computed(() => {
  const raw = memInfo.value?.expire_at
  if (raw == null || raw === '') return '永久'
  return fmtDt(raw)
})

const memExpireIso = computed(() => {
  const { expire_year: y, expire_month: m, expire_day: d } = memForm.value
  if (!y || !m || !d) return null
  const yy = String(y).padStart(4, '0')
  const mm = String(m).padStart(2, '0')
  const dd = String(d).padStart(2, '0')
  return `${yy}-${mm}-${dd}T00:00:00`
})

const memExpirePreview = computed(() => {
  const iso = memExpireIso.value
  if (!iso) {
    const { expire_year: y, expire_month: m, expire_day: d } = memForm.value
    if (y || m || d) return '请填写完整的年、月、日'
    return ''
  }
  return `到期：${iso.slice(0, 10)}（当日零点）`
})

function _parseExpireToForm(raw) {
  if (!raw) return { expire_year: null, expire_month: null, expire_day: null }
  const s = String(raw).slice(0, 10)
  const parts = s.split('-')
  return {
    expire_year: parts[0] ? Number(parts[0]) : null,
    expire_month: parts[1] ? Number(parts[1]) : null,
    expire_day: parts[2] ? Number(parts[2]) : null,
  }
}

function clearExpire() {
  memForm.value.expire_year = null
  memForm.value.expire_month = null
  memForm.value.expire_day = null
}

async function openMembership(u) {
  memUsername.value = u.username
  memInfo.value = null
  memLoadError.value = ''
  memForm.value = {
    membership_type: u.membership_type || 'free',
    ..._parseExpireToForm(u.membership_expire_at),
    note: '',
  }
  memOpen.value = true
  try {
    const info = await fetchUserMembership(u.username)
    memInfo.value = info
    let mtype = info.record_membership_type || info.membership_type || 'free'
    if (mtype === 'admin') mtype = 'free'
    memForm.value = {
      membership_type: mtype,
      ..._parseExpireToForm(info.record_expire_at),
      note: info.record_note || '',
    }
  } catch (e) {
    memLoadError.value = e.message || String(e)
    toast.error(memLoadError.value)
  }
}

async function saveMembership() {
  const { expire_year: y, expire_month: m, expire_day: d } = memForm.value
  const hasAny = y || m || d
  const hasAll = y && m && d

  if (hasAny && !hasAll) {
    toast.error('请填写完整的年、月、日，或全部留空表示永久')
    return
  }
  if (hasAll) {
    const yn = Number(y), mn = Number(m), dn = Number(d)
    if (!Number.isInteger(yn) || yn < 2024 || yn > 2099) { toast.error('年份需在 2024–2099 之间'); return }
    if (!Number.isInteger(mn) || mn < 1 || mn > 12) { toast.error('月份需在 1–12 之间'); return }
    if (!Number.isInteger(dn) || dn < 1 || dn > 31) { toast.error('日期需在 1–31 之间'); return }
    const dt = new Date(yn, mn - 1, dn)
    if (dt.getFullYear() !== yn || dt.getMonth() !== mn - 1 || dt.getDate() !== dn) {
      toast.error(`${yn} 年 ${mn} 月没有 ${dn} 日，请检查`)
      return
    }
    const today = new Date(); today.setHours(0, 0, 0, 0)
    if (dt < today) { toast.error('到期时间不能早于今天'); return }
  }

  memSaving.value = true
  try {
    await updateUserMembership(memUsername.value, {
      membership_type: memForm.value.membership_type,
      expire_at: memExpireIso.value,
      note: memForm.value.note,
    })
    toast.success('会员已更新')
    memOpen.value = false
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  } finally {
    memSaving.value = false
  }
}

async function resetUsage() {
  if (!(await confirmAsync({ title: '重置积分', message: `重置 ${memUsername.value} 今日积分？` }))) return
  try {
    await resetMembershipUsage(memUsername.value)
    toast.success('已重置今日积分')
    const info = await fetchUserMembership(memUsername.value)
    memInfo.value = info
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function resetAllUsage() {
  if (!(await confirmAsync({ title: '重置全员今日积分', message: '将重置所有用户今日积分，确认继续？' }))) return
  try {
    const res = await resetAllMembershipUsage()
    toast.success(res.message || '已重置全员今日积分')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function load() {
  error.value = ''
  try {
    users.value = await fetchUsers()
    resetPage()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

function clearHighlightQuery() {
  const nq = { ...route.query }
  delete nq.highlight
  router.replace({ path: route.path, query: nq })
}

function applyHighlightFromRoute() {
  const raw = route.query.highlight
  if (raw == null || raw === '') return
  const username = decodeURIComponent(String(Array.isArray(raw) ? raw[0] : raw)).trim()
  if (!username) {
    clearHighlightQuery()
    return
  }
  if (!users.value.length) return
  const u = users.value.find(
    (x) => (x.username || '').toLowerCase() === username.toLowerCase(),
  )
  if (u) {
    openEdit(u)
    search.value = u.username
    clearHighlightQuery()
  } else {
    clearHighlightQuery()
  }
}

watch(
  () => [route.query.highlight, users.value],
  () => {
    applyHighlightFromRoute()
  },
  { flush: 'post' },
)

async function onDisable(username) {
  if (!(await confirmAsync({ title: '禁用用户', message: `禁用用户 ${username}？` }))) return
  try {
    await disableUser(username)
    toast.success('已禁用')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function onEnable(username) {
  try {
    await enableUser(username)
    toast.success('已启用')
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

async function onRemove(username) {
  if (!(await confirmAsync({ title: '删除用户', message: `永久删除用户 ${username}？不可恢复`, danger: true }))) return
  try {
    await deleteUser(username)
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
  align-items: center;
  gap: 0.5rem;
}
.search-input {
  width: 220px;
  padding: 0.35rem 0.65rem;
  font-size: 0.875rem;
}
.user-table th {
  cursor: default;
  user-select: none;
}
.user-table th.th-sortable {
  cursor: pointer;
}
.col-count {
  text-align: left;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.col-op {
  min-width: 160px;
}
.uname {
  font-weight: 600;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.mem-btn {
  max-width: 100%;
  justify-content: flex-start;
  text-align: left;
  white-space: normal;
  line-height: 1.25;
}
.small.block {
  display: block;
  margin-top: 0.2rem;
}
.nowrap {
  white-space: nowrap;
  font-size: 0.8rem;
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
  width: min(560px, 100%);
  max-height: 90dvh;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
.mem-modal {
  width: min(560px, 100%);
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
.modal-id {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
  word-break: break-all;
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
.fld-last {
  margin-bottom: 0 !important;
}
/* ── 会员弹窗标题行（置于 modal-header 内） ── */
.mem-modal-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0;
}
.mem-modal-title {
  font-size: 0.85rem;
  color: var(--text-muted);
  font-weight: 500;
}
.mem-modal-user {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text);
}
/* ── 信息卡 ── */
.mem-dash-err {
  margin-bottom: 1rem;
  font-size: 0.875rem;
}
.mem-loading {
  margin-bottom: 1rem;
  font-size: 0.85rem;
}
.mem-dashboard {
  margin-bottom: 0;
  padding: 1rem 1.1rem;
  border-radius: var(--radius-sm, 8px);
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.2));
}
.mem-dash-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.85rem;
}
.mem-badge-tier {
  display: inline-flex;
  align-items: center;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
  background: rgba(117, 73, 212, 0.22);
  color: #ddd6f5;
  border: 1px solid rgba(159, 134, 214, 0.32);
}
.mem-badge-role {
  display: inline-flex;
  align-items: center;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  font-size: 0.75rem;
  color: var(--text-muted);
  background: rgba(51, 65, 85, 0.5);
  border: 1px solid var(--stroke-strong);
}
.mem-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem 1rem;
}
.mem-stat {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}
.mem-stat-label {
  font-size: 0.7rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.mem-stat-value {
  font-size: 1.15rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.mem-stat-value--ok {
  color: #6fb894;
}
.mem-quota-wrap {
  margin-top: 0.9rem;
}
.mem-quota-bar {
  height: 6px;
  border-radius: 999px;
  background: rgba(51, 65, 85, 0.65);
  overflow: hidden;
}
.mem-quota-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--cta-gradient, linear-gradient(90deg, #7549d4, #4ebfcf));
  transition: width 0.3s ease;
}
.mem-quota-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.4rem;
}
.mem-quota-caption {
  font-size: 0.7rem;
  color: var(--text-muted);
}
.mem-expire-inline {
  font-size: 0.7rem;
  color: var(--text-muted);
}
.mem-hint {
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.5;
}
.mem-hint--accent {
  color: var(--accent-mid, #bbb0ea);
  background: rgba(117, 73, 212, 0.1);
  padding: 0.5rem 0.7rem;
  border-radius: 6px;
  border: 1px solid rgba(159, 134, 214, 0.22);
}
.mem-hint strong {
  font-weight: 600;
  color: #ddd6f5;
}
/* ── 分隔线 ── */
.mem-divider {
  height: 1px;
  background: var(--stroke, rgba(148, 163, 184, 0.15));
  margin: 1.1rem 0;
}
/* ── 表单区 ── */
.mem-form-section {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 0.85rem;
}
.fld span {
  font-size: 0.82rem;
  color: var(--text-muted);
  font-weight: 500;
}
.fld-hint {
  font-weight: 400;
  font-style: normal;
  margin-left: 0.3rem;
  font-size: 0.76rem;
  opacity: 0.75;
}
/* ── 到期日期三联输入 ── */
.expire-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.expire-sep {
  font-size: 0.9rem;
  color: var(--text-muted);
  user-select: none;
}
.expire-clear-btn {
  margin-left: 0.25rem;
  font-size: 0.78rem;
  padding: 0.3rem 0.65rem;
}
.expire-preview {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 0.1rem;
}
/* ── 底部操作 ── */
.modal-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0;
  flex-wrap: wrap;
}
.tiny {
  font-size: 0.75rem;
}
</style>

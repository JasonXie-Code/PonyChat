<template>
  <div class="section-root">
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="assets-layout">
      <!-- 左侧分类栏 -->
      <aside class="cat-sidebar">
        <div
          v-for="cat in categories"
          :key="cat.category"
          class="cat-item"
          :class="{ active: activeCat === cat.category }"
          @click="selectCat(cat.category)"
        >
          <span class="cat-label">{{ cat.label }}</span>
          <span class="cat-count">{{ cat.count }}</span>
        </div>
      </aside>

      <!-- 右侧内容区 -->
      <div class="assets-main">
        <!-- 工具栏 -->
        <div class="toolbar">
          <span class="muted">共 {{ total }} 个素材</span>
          <div class="toolbar-right">
            <input v-model="search" class="search-input" placeholder="搜索名称 / 简介 / 详细描述 / 标签…" @input="resetAndLoad" />
            <button type="button" class="btn btn-primary" @click="uploadOpen = true">上传图片</button>
            <button type="button" class="btn" @click="load">刷新</button>
          </div>
        </div>

        <!-- 筛选 + 排序栏 -->
        <div class="filter-bar">
          <!-- 视图切换（移到强度左侧） -->
          <div class="view-toggle">
            <button
              type="button"
              class="view-btn"
              :class="{ active: viewMode === 'grid' }"
              title="宫格视图"
              @click="viewMode = 'grid'"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="0" y="0" width="6" height="6" rx="1"/><rect x="8" y="0" width="6" height="6" rx="1"/>
                <rect x="0" y="8" width="6" height="6" rx="1"/><rect x="8" y="8" width="6" height="6" rx="1"/>
              </svg>
            </button>
            <button
              type="button"
              class="view-btn"
              :class="{ active: viewMode === 'list' }"
              title="列表视图"
              @click="viewMode = 'list'"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="0" y="1" width="14" height="2" rx="1"/><rect x="0" y="6" width="14" height="2" rx="1"/>
                <rect x="0" y="11" width="14" height="2" rx="1"/>
              </svg>
            </button>
          </div>
          <!-- 自定义下拉：强度 -->
          <div class="csel" :class="{ open: openDrop === 'intensity' }">
            <button type="button" class="csel-trigger" @click.stop="toggleDrop('intensity')">
              <span>{{ INTENSITY_OPTS.find(o => o.v === filterIntensity)?.l ?? '强度 全部' }}</span>
              <svg class="csel-arrow" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="2,3.5 5,6.5 8,3.5"/>
              </svg>
            </button>
            <div class="csel-panel" @click.stop>
              <button
                v-for="o in INTENSITY_OPTS" :key="o.v"
                type="button" class="csel-opt"
                :class="{ active: filterIntensity === o.v }"
                @click="pickDrop('intensity', o.v)"
              >{{ o.l }}</button>
            </div>
          </div>

          <!-- 自定义下拉：分级 -->
          <div class="csel" :class="{ open: openDrop === 'age' }">
            <button type="button" class="csel-trigger" @click.stop="toggleDrop('age')">
              <span>{{ AGE_OPTS.find(o => o.v === filterAgeRating)?.l ?? '分级 全部' }}</span>
              <svg class="csel-arrow" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="2,3.5 5,6.5 8,3.5"/>
              </svg>
            </button>
            <div class="csel-panel" @click.stop>
              <button
                v-for="o in AGE_OPTS" :key="o.v"
                type="button" class="csel-opt"
                :class="{ active: filterAgeRating === o.v }"
                @click="pickDrop('age', o.v)"
              >{{ o.l }}</button>
            </div>
          </div>

          <!-- 自定义下拉：排序 -->
          <div class="csel" :class="{ open: openDrop === 'sort' }">
            <button type="button" class="csel-trigger" @click.stop="toggleDrop('sort')">
              <span>{{ SORT_OPTS.find(o => o.v === sortBy)?.l ?? '排序' }}</span>
              <svg class="csel-arrow" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="2,3.5 5,6.5 8,3.5"/>
              </svg>
            </button>
            <div class="csel-panel" @click.stop>
              <button
                v-for="o in SORT_OPTS" :key="o.v"
                type="button" class="csel-opt"
                :class="{ active: sortBy === o.v }"
                @click="pickDrop('sort', o.v)"
              >{{ o.l }}</button>
            </div>
          </div>
          <button type="button" class="sort-dir-btn" :title="sortDir === 'desc' ? '降序' : '升序'" @click="toggleSortDir">
            <svg v-if="sortDir === 'desc'" width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="2,4 6.5,9 11,4"/>
            </svg>
            <svg v-else width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="2,9 6.5,4 11,9"/>
            </svg>
          </button>
        </div>

        <!-- 宫格视图 -->
        <div v-if="viewMode === 'grid'" ref="gridViewportRef" class="asset-grid">
          <div
            v-for="a in items"
            :key="a.id"
            class="asset-card"
            @mouseenter="hoverId = a.id"
            @mouseleave="hoverId = null"
          >
            <div class="asset-preview" @click="openPreview(a)">
              <img :src="a.file_url" :alt="a.name" loading="lazy" />
              <span v-if="a.is_animated" class="badge-anim">动图</span>
            </div>
            <div class="asset-meta">
              <span class="asset-name" :title="a.name">{{ a.name }}</span>
              <div class="asset-tags">
                <span v-if="a.source === 'user'" class="tag tag-custom">用户上传</span>
                <span v-for="e in a.emotions.slice(0, 2)" :key="e" class="tag tag-emo">{{ EMOTION_LABELS[e] || e }}</span>
                <span class="tag" :class="ageClass(a.age_rating)">{{ AGE_LABELS[a.age_rating] }}</span>
                <span v-if="a.review_status && a.review_status !== 'ready'" class="tag tag-policy">{{ REVIEW_LABELS[a.review_status] || a.review_status }}</span>
                <span v-if="a.is_active === false" class="tag tag-blocked">停用</span>
              </div>
              <p v-if="a.uploader_username" class="asset-desc" :title="`上传者：${a.uploader_username}`">上传者：{{ a.uploader_username }}</p>
              <p v-if="a.intro" class="asset-desc" :title="a.intro">{{ a.intro }}</p>
            </div>
            <!-- 悬停操作 -->
            <div v-show="hoverId === a.id" class="asset-actions">
              <button type="button" class="btn btn-sm" @click.stop="openEdit(a)">编辑</button>
              <button type="button" class="btn btn-sm btn-danger" @click.stop="onDelete(a)">删除</button>
            </div>
          </div>
          <p v-if="!items.length && !loading" class="empty-hint">暂无素材</p>
        </div>

        <!-- 列表视图 -->
        <div
          v-else
          ref="listViewportRef"
          class="asset-list-viewport char-list-viewport admin-grid-list"
          :style="gridVars({ '--aw-name': 'name', '--aw-tags': 'tags', '--aw-desc': 'desc' })"
        >
          <div class="list-head admin-grid-head">
            <span></span>
            <span class="th-resizable">
              名称
              <span class="col-resizer" @mousedown.stop="(e) => startResize('name', e, e.currentTarget.parentElement)" @click.stop />
            </span>
            <span class="th-resizable">
              情绪 / 场景
              <span class="col-resizer" @mousedown.stop="(e) => startResize('tags', e, e.currentTarget.parentElement)" @click.stop />
            </span>
            <span>强度</span>
            <span>分级</span>
            <span class="th-resizable">
              简介
              <span class="col-resizer" @mousedown.stop="(e) => startResize('desc', e, e.currentTarget.parentElement)" @click.stop />
            </span>
            <span>大小</span>
            <span>时间</span>
            <span></span>
          </div>
          <div class="list-body admin-grid-body">
            <div v-for="a in items" :key="a.id" class="list-row admin-grid-row">
              <div class="list-thumb" @click="openPreview(a)">
                <img :src="a.file_url" :alt="a.name" loading="lazy" />
                <span v-if="a.is_animated" class="badge-anim-sm">动</span>
              </div>
              <span class="fw ellipsis" :title="a.name">{{ a.name }}</span>
              <div class="list-tags">
                <span v-if="a.source === 'user'" class="tag tag-custom">用户上传</span>
                <span v-for="e in a.emotions.slice(0, 3)" :key="e" class="tag tag-emo">{{ EMOTION_LABELS[e] || e }}</span>
              </div>
              <span class="tag" :class="intensityClass(a.intensity)">{{ INTENSITY_LABELS[a.intensity] }}</span>
              <span class="tag" :class="ageClass(a.age_rating)">{{ AGE_LABELS[a.age_rating] }}</span>
              <span class="small ellipsis muted" :title="a.intro || a.uploader_username">{{ a.uploader_username ? `上传者：${a.uploader_username}` : (a.intro || '—') }}</span>
              <span class="small muted">{{ fmtSize(a.file_size) }}</span>
              <span class="small muted">{{ fmtDate(a.created_at) }}</span>
              <div class="col-act">
                <button type="button" class="btn btn-sm" title="复制链接" @click="copyUrl(a)">链接</button>
                <button type="button" class="btn btn-sm" @click="openEdit(a)">编辑</button>
                <button type="button" class="btn btn-sm btn-danger" @click="onDelete(a)">删除</button>
              </div>
            </div>
            <p v-if="!items.length && !loading" class="empty-hint" style="grid-column:1/-1">暂无素材</p>
          </div>
        </div>

        <!-- 分页 -->
        <AdminPager
          :page="page"
          :total-pages="totalPages"
          :total="total"
          :page-size="pageSize"
          @prev="prevPage"
          @next="nextPage"
        />
      </div>
    </div>

    <!-- 大图预览 -->
    <Teleport to="body">
      <div v-if="previewAsset" class="preview-mask" @click.self="previewAsset = null">
        <div class="preview-box">
          <div class="preview-img-wrap">
            <img :src="previewAsset.file_url" :alt="previewAsset.name" />
          </div>
          <div class="preview-info">
            <div class="preview-title-row">
              <div class="preview-title">
                <span>{{ previewAsset.name }}</span>
                <span v-if="previewAsset.is_animated" class="badge-anim-tag">动图</span>
              </div>
              <button class="preview-close" @click="previewAsset = null">×</button>
            </div>
            <p class="preview-desc">{{ previewAsset.intro || '暂无简介' }}</p>
            <div class="preview-tags">
              <span v-for="e in previewAsset.emotions" :key="e" class="tag tag-emo">{{ EMOTION_LABELS[e] || e }}</span>
              <span class="tag" :class="intensityClass(previewAsset.intensity)">{{ INTENSITY_LABELS[previewAsset.intensity] }}</span>
              <span class="tag" :class="ageClass(previewAsset.age_rating)">{{ AGE_LABELS[previewAsset.age_rating] }}</span>
              <span class="tag tag-policy">{{ REVIEW_LABELS[previewAsset.review_status || 'ready'] }}</span>
              <span class="tag" :class="previewAsset.is_active === false ? 'tag-blocked' : 'tag-safe'">{{ previewAsset.is_active === false ? '聊天停用' : '聊天启用' }}</span>
              <span class="tag" :class="previewAsset.allow_user_save === false ? 'tag-blocked' : 'tag-safe'">{{ previewAsset.allow_user_save === false ? '禁止收藏' : '允许收藏' }}</span>
              <span v-for="t in previewAsset.custom_tags" :key="t" class="tag tag-custom">{{ t }}</span>
            </div>
            <p v-if="previewAsset.detail" class="preview-desc">详细描述：{{ previewAsset.detail }}</p>
            <p v-if="previewAsset.image_text" class="preview-desc">图中文字：{{ previewAsset.image_text }}</p>
            <div class="preview-meta-row">
              <span class="muted">{{ fmtSize(previewAsset.file_size) }}</span>
              <span class="muted">{{ fmtDate(previewAsset.created_at) }}</span>
              <span v-if="previewAsset.uploader_username" class="muted">上传者：{{ previewAsset.uploader_username }}</span>
              <span v-if="previewAsset.sha256" class="muted">SHA256：{{ previewAsset.sha256.slice(0, 12) }}…</span>
            </div>
            <div class="preview-actions">
              <button type="button" class="pa-btn" @click="copyUrl(previewAsset)">复制链接</button>
              <button type="button" class="pa-btn" @click="openEdit(previewAsset); previewAsset = null">编辑标签</button>
              <button type="button" class="pa-btn pa-btn-danger" @click="onDelete(previewAsset); previewAsset = null">删除</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 上传弹层 -->
    <Teleport to="body">
      <div v-if="uploadOpen" class="modal-mask admin-shell" @click.self="uploadOpen = false">
        <div class="modal card">
          <header class="modal-header">
            <h3 class="modal-title">上传图片素材</h3>
            <button type="button" class="modal-close" @click="uploadOpen = false">×</button>
          </header>
          <div class="modal-body">
            <!-- 拖拽区 -->
            <div
              class="drop-zone"
              :class="{ dragging: isDragging }"
              @dragover.prevent="isDragging = true"
              @dragleave="isDragging = false"
              @drop.prevent="onDrop"
              @click="uploadFileRef?.click()"
            >
              <input ref="uploadFileRef" type="file" accept="image/jpeg,image/png,image/gif,image/webp,image/apng" multiple class="hidden-input" @change="onFilePick" />
              <span v-if="!uploadQueue.length">点击或拖入图片（支持多选）</span>
              <span v-else>已选 {{ uploadQueue.length }} 个文件，点击可追加</span>
            </div>

            <!-- 批量标签表单 -->
            <div v-if="uploadQueue.length" class="batch-form">
              <p class="muted small">以下标签将统一应用于所有上传文件（可在上传后逐一编辑）</p>
              <AssetTagForm
                :modelValue="batchTags"
                @update:modelValue="val => Object.assign(batchTags, val)"
              />
            </div>

            <!-- 文件列表 -->
            <div v-if="uploadQueue.length" class="upload-list">
              <div v-for="(f, i) in uploadQueue" :key="i" class="upload-item">
                <img :src="f.previewUrl" class="upload-thumb" :alt="f.file.name" />
                <span class="upload-name">{{ f.file.name }}</span>
                <button type="button" class="btn btn-sm btn-danger" @click="removeFromQueue(i)">移除</button>
              </div>
            </div>
          </div>
          <footer class="modal-footer">
            <p v-if="uploadErr" class="err">{{ uploadErr }}</p>
            <div class="upload-progress" v-if="uploadProgress">{{ uploadProgress }}</div>
            <div class="modal-actions">
              <button type="button" class="btn" :disabled="uploading" @click="uploadOpen = false">取消</button>
              <button type="button" class="btn btn-primary" :disabled="uploading || !uploadQueue.length" @click="doUpload">
                {{ uploading ? `上传中… (${uploadDone}/${uploadQueue.length})` : '开始上传' }}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- 编辑标签弹层 -->
    <Teleport to="body">
      <div v-if="editOpen" class="modal-mask admin-shell" @click.self="closeEdit">
        <div class="modal card">
          <header class="modal-header">
            <h3 class="modal-title">编辑标签</h3>
            <button type="button" class="modal-close" @click="closeEdit">×</button>
          </header>
          <div class="modal-body">
            <label class="fld">
              <span>名称</span>
              <input v-model="editForm.name" type="text" />
            </label>
            <label class="fld">
              <span>分类</span>
              <select v-model="editForm.category">
                <option value="emoji">表情包</option>
                <option value="sticker">贴纸</option>
                <option value="user_sticker">用户上传</option>
                <option value="bg">背景图</option>
                <option value="misc">其他</option>
              </select>
            </label>
            <AssetTagForm
              :modelValue="editForm"
              @update:modelValue="val => Object.assign(editForm, val)"
            />
          </div>
          <footer class="modal-footer">
            <p v-if="editErr" class="err">{{ editErr }}</p>
            <div class="modal-actions">
              <button type="button" class="btn" :disabled="editSaving" @click="closeEdit">取消</button>
              <button type="button" class="btn btn-primary" :disabled="editSaving" @click="saveEdit">
                {{ editSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { fetchAssets, fetchAssetCategories, uploadAsset, updateAsset, deleteAsset } from '../../../api/admin'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import { useColResize } from '../../../composables/useColResize'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { fmtDateOnly } from '../../../composables/useAdminTableSort'
import AdminPager from '../../../components/admin/AdminPager.vue'
import AssetTagForm from '../../../components/admin/AssetTagForm.vue'
import '../../../styles/admin-shell.css'

const EMOTION_LABELS = {
  // 基础情绪
  happy: '开心', excited: '兴奋', laugh: '大笑', funny: '搞笑',
  shy: '害羞', cute: '撒娇', smug: '得意', neutral: '平静',
  aggrieved: '委屈', anticipate: '期待', sad: '难过', cry: '哭泣',
  angry: '生气', surprised: '惊讶', scared: '害怕', curious: '好奇',
  disgusted: '厌恶', speechless: '无语', confused: '困惑', skeptical: '怀疑',
  embarrassed: '尴尬', nervous: '紧张', disappointed: '失望', helpless: '无奈',
  touched: '感动', apologetic: '抱歉', playful: '调皮', tired: '疲惫',
  // 伴侣向
  flirty: '撩人', love: '爱意', yearning: '思念', jealous: '吃醋',
}
const AGE_LABELS = { all: '全年龄', teen: '青少年', adult: '成人' }
const INTENSITY_LABELS = { mild: '轻度', moderate: '中等', strong: '强烈' }
const REVIEW_LABELS = { draft: '草稿', ready: '可用', disabled: '停用' }

// ── 视图状态 ──────────────────────────────────────────────────────────────────

const viewMode = ref(localStorage.getItem('assets_view') || 'grid')
watch(viewMode, (v) => {
  localStorage.setItem('assets_view', v)
  nextTick(() => {
    unbindGridResizeObserver()
    measureGridPageSize()
    bindGridResizeObserver()
  })
})

// ── 列宽拖拽（列表视图）──────────────────────────────────────────────────────

const gridViewportRef = ref(null)
const listViewportRef = ref(null)
const { startResize, gridVars } = useColResize(
  { name: 180, tags: 220, desc: 300 },
  {
    min: 60,
    cssVarByKey: {
      name: '--aw-name',
      tags: '--aw-tags',
      desc: '--aw-desc',
    },
  },
)
const { pageSize: listPageSize } = useViewportPageSize(listViewportRef, {
  rowHeight: 48,
  headHeight: 40,
  minRows: 6,
  maxRows: 120,
})

// ── 数据状态 ──────────────────────────────────────────────────────────────────

const error = ref('')
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const gridPageSize = ref(24)
const pageSize = computed(() => viewMode.value === 'grid' ? gridPageSize.value : listPageSize.value)
const search = ref('')
const activeCat = ref('all')
const filterIntensity = ref('')
const filterAgeRating = ref('')
const sortBy = ref('created_at')
const sortDir = ref('desc')

// ── 自定义下拉选项常量 ─────────────────────────────────────────────────────────
const INTENSITY_OPTS = [
  { v: '', l: '强度 全部' }, { v: 'mild', l: '轻度' },
  { v: 'moderate', l: '中等' }, { v: 'strong', l: '强烈' },
]
const AGE_OPTS = [
  { v: '', l: '分级 全部' }, { v: 'all', l: '全年龄' },
  { v: 'teen', l: '青少年' }, { v: 'adult', l: '成人 R18' },
]
const SORT_OPTS = [
  { v: 'created_at', l: '排序：最新' },
  { v: 'name', l: '排序：名称' },
  { v: 'file_size', l: '排序：大小' },
]

const openDrop = ref(null)
function toggleDrop(name) { openDrop.value = openDrop.value === name ? null : name }
function pickDrop(field, val) {
  if (field === 'intensity') filterIntensity.value = val
  else if (field === 'age') filterAgeRating.value = val
  else if (field === 'sort') sortBy.value = val
  openDrop.value = null
  resetAndLoad()
}
function closeDrop() { openDrop.value = null }
onMounted(() => document.addEventListener('click', closeDrop))
onUnmounted(() => document.removeEventListener('click', closeDrop))
const hoverId = ref(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const categories = ref([{ category: 'all', label: '全部', count: 0 }])

const GRID_GAP_PX = 12
const GRID_MIN_CARD_W = 172
const GRID_META_H = 86
const GRID_MIN_ROWS = 2
const GRID_MAX_ITEMS = 80

function measureGridPageSize() {
  const el = gridViewportRef.value
  if (!el || typeof el.clientWidth !== 'number') return
  const w = el.clientWidth
  const h = el.clientHeight
  if (w < 120 || h < 120) return

  const cols = Math.max(1, Math.floor((w + GRID_GAP_PX) / (GRID_MIN_CARD_W + GRID_GAP_PX)))
  const cardW = (w - GRID_GAP_PX * (cols - 1)) / cols
  const cardH = cardW + GRID_META_H
  const rows = Math.max(GRID_MIN_ROWS, Math.floor((h + GRID_GAP_PX) / (cardH + GRID_GAP_PX)))
  const next = Math.min(GRID_MAX_ITEMS, Math.max(cols * GRID_MIN_ROWS, cols * rows))
  if (gridPageSize.value !== next) gridPageSize.value = next
}

let gridRo = null
function bindGridResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  if (!gridRo) gridRo = new ResizeObserver(() => measureGridPageSize())
  if (gridViewportRef.value) gridRo.observe(gridViewportRef.value)
}

function unbindGridResizeObserver() {
  if (gridRo) {
    gridRo.disconnect()
    gridRo = null
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function ageClass(v) {
  return v === 'all' ? 'tag-safe' : v === 'teen' ? 'tag-teen' : 'tag-adult'
}
function intensityClass(v) {
  return v === 'mild' ? 'tag-intensity-mild' : v === 'strong' ? 'tag-intensity-strong' : 'tag-intensity-mod'
}
function fmtSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
function fmtDate(s) {
  return fmtDateOnly(s) || '—'
}
async function copyUrl(a) {
  const url = location.origin + a.file_url
  try {
    await navigator.clipboard.writeText(url)
    toast.success('链接已复制')
  } catch {
    toast.error('复制失败，请手动复制')
  }
}
function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  resetAndLoad()
}

// ── 大图预览 ──────────────────────────────────────────────────────────────────

const previewAsset = ref(null)
function openPreview(a) { previewAsset.value = a }

// ── 数据加载 ──────────────────────────────────────────────────────────────────

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    if (activeCat.value && activeCat.value !== 'all') params.category = activeCat.value
    if (filterIntensity.value) params.intensity = filterIntensity.value
    if (filterAgeRating.value) params.age_rating = filterAgeRating.value
    if (search.value.trim()) params.search = search.value.trim()
    const res = await fetchAssets(params)
    items.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  try {
    categories.value = await fetchAssetCategories()
  } catch { /* ignore */ }
}

function resetAndLoad() {
  page.value = 1
  load()
}

function selectCat(cat) {
  activeCat.value = cat
  resetAndLoad()
}

function prevPage() {
  if (page.value > 1) { page.value--; load() }
}
function nextPage() {
  if (page.value < totalPages.value) { page.value++; load() }
}

watch(pageSize, (next, prev) => {
  if (next === prev) return
  page.value = 1
  load()
})

// ── 上传 ──────────────────────────────────────────────────────────────────────

const uploadOpen = ref(false)
const uploadFileRef = ref(null)
const isDragging = ref(false)
const uploadQueue = ref([])
const batchTags = reactive({
  emotions: [], intensity: 'moderate', scenes: [],
  age_rating: 'all', custom_tags: [], intro: '',
  is_active: true, review_status: 'ready', allow_user_save: true, detail: '',
  image_text: '',
})
const uploading = ref(false)
const uploadDone = ref(0)
const uploadErr = ref('')
const uploadProgress = ref('')

watch(uploadOpen, (v) => {
  if (!v) {
    uploadQueue.value.forEach(f => URL.revokeObjectURL(f.previewUrl))
    uploadQueue.value = []
    uploadErr.value = ''
    uploadProgress.value = ''
  }
})

function addFilesToQueue(files) {
  for (const f of files) {
    uploadQueue.value.push({ file: f, previewUrl: URL.createObjectURL(f) })
  }
}

function onFilePick(e) {
  if (e.target.files) addFilesToQueue([...e.target.files])
  e.target.value = ''
}

function onDrop(e) {
  isDragging.value = false
  if (e.dataTransfer?.files) addFilesToQueue([...e.dataTransfer.files])
}

function removeFromQueue(i) {
  URL.revokeObjectURL(uploadQueue.value[i].previewUrl)
  uploadQueue.value.splice(i, 1)
}

async function doUpload() {
  uploading.value = true
  uploadDone.value = 0
  uploadErr.value = ''
  let failed = 0
  for (const item of uploadQueue.value) {
    uploadProgress.value = `正在上传：${item.file.name}`
    try {
      const fd = new FormData()
      fd.append('file', item.file)
      fd.append('name', item.file.name.replace(/\.[^.]+$/, ''))
      fd.append('category', activeCat.value !== 'all' ? activeCat.value : 'emoji')
      fd.append('emotions', JSON.stringify(batchTags.emotions))
      fd.append('intensity', batchTags.intensity)
      fd.append('scenes', JSON.stringify([]))
      fd.append('age_rating', batchTags.age_rating)
      fd.append('flirt_level', '0')
      fd.append('send_policy', 'always')
      fd.append('min_relationship_stage', 'stranger')
      fd.append('sender_archetypes', JSON.stringify([]))
      fd.append('blocked_archetypes', JSON.stringify([]))
      fd.append('custom_tags', JSON.stringify(batchTags.custom_tags))
      fd.append('intro', batchTags.intro)
      fd.append('review_status', batchTags.review_status || 'ready')
      fd.append('is_active', (batchTags.review_status || 'ready') === 'ready' ? '1' : '0')
      fd.append('allow_user_save', batchTags.allow_user_save ? '1' : '0')
      fd.append('detail', batchTags.detail || '')
      fd.append('image_text', batchTags.image_text || '')
      await uploadAsset(fd)
      uploadDone.value++
    } catch (e) {
      failed++
      uploadErr.value = `${item.file.name} 上传失败：${e.message || e}`
    }
  }
  uploading.value = false
  uploadProgress.value = ''
  if (!failed) {
    toast.success(`已上传 ${uploadDone.value} 个素材`)
    uploadOpen.value = false
    await loadCategories()
    await load()
  }
}

// ── 编辑 ──────────────────────────────────────────────────────────────────────

const editOpen = ref(false)
const editSaving = ref(false)
const editErr = ref('')
const editForm = reactive({
  id: '',
  source: '',
  name: '',
  category: 'emoji',
  emotions: [],
  intensity: 'moderate',
  scenes: [],
  age_rating: 'all',
  custom_tags: [],
  intro: '',
  is_active: true,
  review_status: 'ready',
  allow_user_save: true,
  detail: '',
  image_text: '',
})

function openEdit(a) {
  editErr.value = ''
  editForm.id = a.id
  editForm.source = a.source || 'platform'
  editForm.name = a.name
  editForm.category = a.category
  editForm.emotions = [...(a.emotions || [])]
  editForm.intensity = a.intensity || 'moderate'
  editForm.scenes = []
  editForm.age_rating = a.age_rating || 'all'
  editForm.custom_tags = [...(a.custom_tags || [])]
  editForm.intro = a.intro || ''
  editForm.review_status = a.is_active === false ? 'disabled' : (a.review_status || 'ready')
  editForm.is_active = editForm.review_status === 'ready'
  editForm.allow_user_save = a.allow_user_save !== false
  editForm.detail = a.detail || ''
  editForm.image_text = a.image_text || ''
  editOpen.value = true
}

function closeEdit() { editOpen.value = false }

async function saveEdit() {
  editSaving.value = true
  editErr.value = ''
  try {
    await updateAsset(editForm.id, {
      name: editForm.name,
      category: editForm.category,
      emotions: editForm.emotions,
      intensity: editForm.intensity,
      scenes: [],
      age_rating: editForm.age_rating,
      flirt_level: 0,
      send_policy: 'always',
      min_relationship_stage: 'stranger',
      sender_archetypes: [],
      blocked_archetypes: [],
      custom_tags: editForm.custom_tags,
      intro: editForm.intro,
      review_status: editForm.review_status,
      is_active: editForm.review_status === 'ready',
      allow_user_save: editForm.allow_user_save,
      detail: editForm.detail,
      image_text: editForm.image_text,
    })
    toast.success('已保存')
    closeEdit()
    await load()
  } catch (e) {
    editErr.value = e.message || String(e)
    toast.error(editErr.value)
  } finally {
    editSaving.value = false
  }
}

// ── 删除 ──────────────────────────────────────────────────────────────────────

async function onDelete(a) {
  if (!(await confirmAsync({
    title: '删除素材',
    message: `永久删除「${a.name}」？不可恢复。`,
    danger: true,
  }))) return
  try {
    await deleteAsset(a.id)
    toast.success('已删除')
    await loadCategories()
    await load()
  } catch (e) {
    toast.error(e.message || String(e))
  }
}

onMounted(async () => {
  await nextTick()
  measureGridPageSize()
  bindGridResizeObserver()
  await loadCategories()
  await load()
})

onUnmounted(unbindGridResizeObserver)
</script>

<style scoped>
.section-root { min-height: 0; }

.assets-layout {
  display: flex;
  gap: 0;
  min-height: 0;
  height: 100%;
}

/* ── 分类侧边栏 ── */
.cat-sidebar {
  width: 120px;
  flex-shrink: 0;
  border-right: 1px solid #1e293b;
  padding: 0.5rem 0;
  overflow-y: auto;
}
.cat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  border-radius: 6px;
  margin: 0 0.25rem 0.1rem;
  font-size: 0.82rem;
  color: #94a3b8;
  transition: background 0.12s, color 0.12s;
}
.cat-item:hover { background: rgba(255,255,255,0.04); color: #e2e8f0; }
.cat-item.active { background: rgba(117,73,212,0.15); color: #c4b5fd; font-weight: 600; }
.cat-count {
  font-size: 0.72rem;
  background: #1e293b;
  border-radius: 99px;
  padding: 0.05rem 0.4rem;
  min-width: 18px;
  text-align: center;
}

/* ── 主区域 ── */
.assets-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 0 1rem 1rem;
  gap: 0.75rem;
  overflow: hidden;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding-top: 0.75rem;
}
.toolbar-right { display: flex; gap: 0.5rem; align-items: center; }
.search-input { width: 200px; }

/* ── 视图切换 ── */
.view-toggle {
  display: flex;
  height: 2rem;
  border: 1px solid rgba(148,163,184,0.2);
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
}
.view-btn {
  width: 2rem;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s, color 0.12s;
}
.view-btn:hover { background: rgba(255,255,255,0.06); color: #94a3b8; }
.view-btn.active { background: rgba(117,73,212,0.2); color: #c4b5fd; }

.filter-bar {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
  align-items: center;
}
/* ── 自定义下拉 ── */
.csel {
  position: relative;
}
.csel-trigger {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  height: 2rem;
  padding: 0 0.65rem;
  border-radius: 8px;
  border: 1px solid rgba(148,163,184,0.2);
  background: rgba(15,23,42,0.6);
  color: #cbd5e1;
  font-size: 0.82rem;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}
.csel-trigger:hover,
.csel.open .csel-trigger {
  border-color: rgba(139,92,246,0.5);
  background: rgba(139,92,246,0.1);
  color: #e2e8f0;
}
.csel-arrow {
  flex-shrink: 0;
  opacity: 0.6;
  transition: transform 0.2s;
}
.csel.open .csel-arrow { transform: rotate(180deg); }

.csel-panel {
  display: none;
  position: absolute;
  top: calc(100% + 5px);
  left: 0;
  min-width: 100%;
  background: #0f172a;
  border: 1px solid rgba(139,92,246,0.35);
  border-radius: 10px;
  padding: 0.25rem;
  z-index: 200;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5), 0 0 0 1px rgba(139,92,246,0.08);
  overflow: hidden;
}
.csel.open .csel-panel { display: flex; flex-direction: column; }

.csel-opt {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.38rem 0.65rem;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: #94a3b8;
  font-size: 0.82rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s, color 0.12s;
}
.csel-opt:hover {
  background: rgba(139,92,246,0.12);
  color: #e2e8f0;
}
.csel-opt.active {
  background: rgba(139,92,246,0.2);
  color: #c4b5fd;
  font-weight: 500;
}
.sort-dir-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border-radius: 6px;
  border: 1px solid rgba(148,163,184,0.2);
  background: rgba(15,23,42,0.6);
  color: #94a3b8;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.sort-dir-btn:hover { background: rgba(255,255,255,0.06); color: #e2e8f0; border-color: rgba(148,163,184,0.4); }

/* ── 素材网格 ── */
.asset-grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(172px, 1fr));
  gap: 0.75rem;
  align-content: start;
}
.empty-hint {
  grid-column: 1/-1;
  text-align: center;
  color: #64748b;
  padding: 2rem 0;
}

/* ── 素材卡片 ── */
.asset-card {
  position: relative;
  border-radius: 8px;
  border: 1px solid #1e293b;
  background: rgba(15,23,42,0.5);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s;
}
.asset-card:hover { border-color: rgba(148,163,184,0.35); }

.asset-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  background: #0f172a;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: pointer;
}
.asset-preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  display: block;
}
.badge-anim {
  position: absolute;
  top: 4px;
  right: 4px;
  background: rgba(99,102,241,0.85);
  color: #fff;
  font-size: 0.65rem;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
}

.asset-meta {
  padding: 0.45rem 0.5rem 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.asset-name {
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #e2e8f0;
}
.asset-tags { display: flex; flex-wrap: wrap; gap: 0.2rem; }
.tag {
  font-size: 0.62rem;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-weight: 600;
}
.tag-emo              { background: rgba(139,92,246,0.18); color: #a78bfa; }
.tag-safe             { background: rgba(61,168,130,0.14); color: #6fb894; }
.tag-teen             { background: rgba(245,158,11,0.18); color: #fbbf24; }
.tag-adult            { background: rgba(239,68,68,0.18);  color: #f87171; }
.tag-intensity-mild   { background: rgba(100,116,139,0.18); color: #94a3b8; }
.tag-intensity-mod    { background: rgba(245,158,11,0.14); color: #fbbf24; }
.tag-intensity-strong { background: rgba(239,68,68,0.18);  color: #f87171; }
.tag-policy           { background: rgba(14,165,233,0.16); color: #7dd3fc; }
.tag-blocked          { background: rgba(239,68,68,0.16); color: #fca5a5; }
.tag-custom           { background: rgba(100,116,139,0.18); color: #94a3b8; }

.asset-desc {
  font-size: 0.7rem;
  color: #64748b;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 悬停操作层 ── */
.asset-actions {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 0.3rem;
  padding: 0.4rem;
  background: rgba(15,23,42,0.88);
  justify-content: flex-end;
}
.asset-actions .btn {
  white-space: nowrap;
  flex-shrink: 0;
}

/* ── 列表视图 ── */
.asset-list-viewport {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.list-head,
.list-row {
  display: grid;
  grid-template-columns:
    48px                      /* thumb */
    var(--aw-name, 180px)     /* name */
    var(--aw-tags, 220px)     /* tags */
    64px                      /* intensity */
    64px                      /* age */
    var(--aw-desc, 300px)     /* desc */
    60px                      /* size */
    72px                      /* date */
    140px;                    /* actions */
}

.list-thumb {
  width: 38px;
  height: 38px;
  border-radius: 5px;
  overflow: hidden;
  background: #0f172a;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
}
.list-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.badge-anim-sm {
  position: absolute;
  bottom: 2px;
  right: 2px;
  background: rgba(99,102,241,0.9);
  color: #fff;
  font-size: 0.55rem;
  padding: 0.05rem 0.25rem;
  border-radius: 3px;
}
.list-tags { display: flex; flex-wrap: wrap; gap: 0.2rem; }
.col-act { display: flex; gap: 0.3rem; flex-wrap: nowrap; }
.col-act .btn { white-space: nowrap; }

/* 与角色管理共用的工具类 */
.fw      { font-weight: 600; font-size: 0.875rem; color: #e2e8f0; }
.small   { font-size: 0.78rem; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted   { color: #64748b; }

/* ── 大图预览 ── */
.preview-mask {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(7,12,24,0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.preview-box {
  display: flex;
  gap: 0;
  max-width: min(860px, 98vw);
  max-height: 90dvh;
  background: #0f172a;
  border: 1px solid rgba(148,163,184,0.18);
  border-radius: 12px;
  overflow: hidden;
}
.preview-img-wrap {
  width: 320px;
  min-width: 220px;
  max-width: 40vw;
  background: #070c18;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
}
.preview-img-wrap img {
  max-width: 100%;
  max-height: 80dvh;
  object-fit: contain;
  display: block;
}
.preview-info {
  flex: 1;
  min-width: 0;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow-y: auto;
  border-left: 1px solid rgba(148,163,184,0.1);
}
.preview-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}
.preview-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.05rem;
  font-weight: 700;
  color: #e2e8f0;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}
.preview-close {
  flex-shrink: 0;
  width: 1.8rem;
  height: 1.8rem;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: rgba(100,116,139,0.15);
  color: #94a3b8;
  font-size: 1.2rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.preview-close:hover { background: rgba(239,68,68,0.2); color: #f87171; }
.preview-desc {
  margin: 0;
  font-size: 0.875rem;
  color: #94a3b8;
  line-height: 1.5;
}
.preview-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.preview-meta-row {
  display: flex;
  gap: 1rem;
  font-size: 0.78rem;
}
.preview-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(148,163,184,0.1);
}
/* 预览弹层专用按钮，避免受全局 .btn scoped 污染 */
.pa-btn {
  padding: 0.42rem 0.9rem;
  border-radius: 6px;
  border: 1px solid rgba(148,163,184,0.25);
  background: rgba(148,163,184,0.08);
  color: #cbd5e1;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.pa-btn:hover {
  background: rgba(148,163,184,0.15);
  border-color: rgba(148,163,184,0.4);
  color: #e2e8f0;
}
.pa-btn-danger {
  border-color: rgba(239,68,68,0.3);
  background: rgba(239,68,68,0.08);
  color: #f87171;
}
.pa-btn-danger:hover {
  background: rgba(239,68,68,0.18);
  border-color: rgba(239,68,68,0.5);
  color: #fca5a5;
}

/* 预览标题内联动图角标（非绝对定位） */
.badge-anim-tag {
  display: inline-block;
  flex-shrink: 0;
  background: rgba(99,102,241,0.85);
  color: #fff;
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-weight: 600;
}

/* ── 上传弹层 ── */
.drop-zone {
  border: 2px dashed rgba(148,163,184,0.3);
  border-radius: 8px;
  padding: 2rem 1rem;
  text-align: center;
  cursor: pointer;
  color: #64748b;
  font-size: 0.875rem;
  transition: border-color 0.15s, background 0.15s;
  margin-bottom: 1rem;
}
.drop-zone:hover, .drop-zone.dragging {
  border-color: rgba(117,73,212,0.6);
  background: rgba(117,73,212,0.06);
  color: #c4b5fd;
}
.hidden-input { display: none; }

.batch-form { margin-bottom: 1rem; }

.upload-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-height: 200px;
  overflow-y: auto;
}
.upload-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
}
.upload-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}
.upload-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #cbd5e1;
}

.upload-progress {
  font-size: 0.82rem;
  color: #94a3b8;
  margin-bottom: 0.5rem;
}

/* ── 公用弹层样式 ── */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 8000;
  background: rgba(15,23,42,0.75);
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
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--stroke, rgba(148,163,184,0.18));
  flex-shrink: 0;
}
.modal-title { margin: 0; font-size: 1.1rem; font-weight: 600; }
.modal-close {
  width: 2rem; height: 2rem; padding: 0; border: none; border-radius: 6px;
  background: transparent; color: #94a3b8; font-size: 1.5rem; cursor: pointer;
  transition: background 0.15s;
}
.modal-close:hover { background: rgba(148,163,184,0.12); color: #e2e8f0; }
.modal-body {
  flex: 1; min-height: 0; overflow-y: auto;
  padding: 1.25rem; -webkit-overflow-scrolling: touch;
}
.modal-footer {
  flex-shrink: 0;
  padding: 0.85rem 1.25rem;
  border-top: 1px solid var(--stroke, rgba(148,163,184,0.18));
}
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
.fld {
  display: flex; flex-direction: column; gap: 0.4rem;
  margin-bottom: 1rem; font-size: 0.875rem;
}
.fld span { color: #cbd5e1; font-weight: 500; }
.fld input, .fld select {
  width: 100%; box-sizing: border-box;
  padding: 0.55rem 0.75rem !important;
}
.err { color: #e8a0a0; font-size: 0.85rem; margin: 0 0 0.65rem; }
</style>

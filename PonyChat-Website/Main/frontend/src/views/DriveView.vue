<template>
  <div class="bg-layer" aria-hidden="true" />

  <div v-if="!isAuthed" class="drive-login-shell">
    <section class="drive-login-panel" aria-labelledby="drive-login-title">
      <RouterLink class="brand drive-login-brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat Drive</span>
      </RouterLink>

      <form class="drive-login-form" @submit.prevent="handleLogin">
        <div>
          <p class="hero-eyebrow">drive.ponychat.org</p>
          <h1 id="drive-login-title">个人网盘</h1>
        </div>

        <label class="drive-field">
          <span>访问密码</span>
          <span class="drive-input-wrap">
            <ion-icon name="lock-closed-outline" aria-hidden="true" />
            <input
              ref="passwordInput"
              v-model="password"
              type="password"
              autocomplete="current-password"
              inputmode="numeric"
              required
            >
          </span>
        </label>

        <button class="drive-primary-btn" type="submit" :disabled="loading">
          <ion-icon name="log-in-outline" aria-hidden="true" />
          <span>{{ loading ? '登录中' : '进入 Drive' }}</span>
        </button>

        <p v-if="loginError" class="drive-error" role="alert">{{ loginError }}</p>
      </form>
    </section>
  </div>

  <div v-else class="drive-app" @dragover.prevent="handleDragOver" @dragleave="handleDragLeave" @drop.prevent="handleDrop">
    <header class="drive-titlebar">
      <RouterLink class="brand drive-brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="36" height="36" decoding="async">
        <span class="brand-text">PonyChat Drive</span>
      </RouterLink>
      <div class="drive-titlebar-actions">
        <span class="drive-storage">{{ storageLabel }}</span>
        <button class="drive-icon-btn" type="button" title="刷新" aria-label="刷新" @click="loadDrive">
          <ion-icon name="refresh-outline" aria-hidden="true" />
        </button>
        <button class="drive-icon-btn" type="button" title="退出" aria-label="退出" @click="logout">
          <ion-icon name="log-out-outline" aria-hidden="true" />
        </button>
      </div>
    </header>

    <main class="drive-frame">
      <aside class="drive-sidebar" aria-label="Drive 导航">
        <button
          class="drive-tree-root"
          type="button"
          :class="{ active: activeSpace === 'files' && currentFolderId === ROOT_ID }"
          @click="goToFilesRoot"
        >
          <ion-icon name="cloud-outline" aria-hidden="true" />
          <span>我的 Drive</span>
        </button>

        <div class="drive-tree" role="tree" aria-label="文件夹">
          <button
            v-for="folder in flatFolderTree"
            :key="folder.id"
            class="drive-tree-item"
            type="button"
            role="treeitem"
            :aria-expanded="folder.hasChildren ? folder.expanded : undefined"
            :class="{ active: activeSpace === 'files' && currentFolderId === folder.id }"
            :style="{ '--tree-level': folder.level }"
            @click="openFolderById(folder.id)"
          >
            <span class="drive-tree-spacer" />
            <ion-icon
              v-if="folder.hasChildren"
              class="drive-tree-toggle"
              :name="folder.expanded ? 'chevron-down-outline' : 'chevron-forward-outline'"
              aria-hidden="true"
              @click.stop="toggleTreeFolder(folder.id)"
            />
            <span v-else class="drive-tree-toggle" aria-hidden="true" />
            <ion-icon :name="folder.expanded ? 'folder-open-outline' : 'folder-outline'" aria-hidden="true" />
            <span>{{ folder.name }}</span>
          </button>
        </div>

        <button
          class="drive-tree-root drive-trash-root"
          type="button"
          :class="{ active: activeSpace === 'trash' }"
          @click="openTrash"
        >
          <ion-icon name="trash-outline" aria-hidden="true" />
          <span>回收站</span>
          <span v-if="trashCount" class="drive-tree-count">{{ trashCount }}</span>
        </button>
      </aside>

      <section class="drive-workbench" @click="clearSelection">
        <div class="drive-toolbar" @click.stop>
          <div class="drive-toolbar-left">
            <div class="drive-command-group">
              <button class="drive-command-btn drive-command-primary" type="button" title="上传文件" :disabled="activeSpace === 'trash' || loading" @click="openFilePicker">
                <ion-icon name="cloud-upload-outline" aria-hidden="true" />
                <span>上传</span>
              </button>
              <button class="drive-command-btn" type="button" title="上传文件夹" :disabled="activeSpace === 'trash' || loading" @click="openFolderPicker">
                <ion-icon name="folder-open-outline" aria-hidden="true" />
                <span>上传文件夹</span>
              </button>
              <button class="drive-command-btn" type="button" title="新建文件夹" :disabled="activeSpace === 'trash' || loading" @click="openCreateFolderDialog">
                <ion-icon name="add-outline" aria-hidden="true" />
                <span>新建</span>
              </button>
              <button v-if="uploadState.active" class="drive-command-btn drive-upload-cancel-btn danger" type="button" title="取消上传" @click="cancelUpload">
                <ion-icon name="close-circle-outline" aria-hidden="true" />
                <span>取消</span>
              </button>
            </div>

            <div v-if="uploadProgressVisible" class="drive-upload-progress" aria-live="polite">
              <div class="drive-upload-line" :title="uploadProgressTitle">
                <span class="drive-upload-name">{{ uploadProgressTitle }}</span>
                <span class="drive-upload-detail">
                  <span>总数{{ uploadState.totalCount }}/剩余{{ uploadRemainingCount }}</span>
                  <span>速度{{ uploadSpeedLabel }}</span>
                  <span>总进度{{ uploadProgressPercent }}%</span>
                </span>
              </div>
              <div class="drive-upload-track" aria-hidden="true">
                <span :style="{ width: uploadProgressPercent + '%' }" />
              </div>
            </div>
          </div>

          <div class="drive-command-group">
            <button class="drive-command-btn" type="button" title="重命名" :disabled="selectedIds.length !== 1 || activeSpace === 'trash' || loading" @click="openRenameDialog">
              <ion-icon name="create-outline" aria-hidden="true" />
              <span>重命名</span>
            </button>
            <button class="drive-command-btn" type="button" title="下载" :disabled="!selectedFiles.length || loading" @click="downloadSelected">
              <ion-icon name="download-outline" aria-hidden="true" />
              <span>下载</span>
            </button>
            <button v-if="activeSpace === 'files'" class="drive-command-btn danger" type="button" title="删除" :disabled="!selectedIds.length || loading" @click="moveSelectedToTrash">
              <ion-icon name="trash-outline" aria-hidden="true" />
              <span>删除</span>
            </button>
            <button v-else class="drive-command-btn" type="button" title="还原" :disabled="!selectedIds.length || loading" @click="restoreSelected">
              <ion-icon name="arrow-undo-outline" aria-hidden="true" />
              <span>还原</span>
            </button>
            <button v-if="activeSpace === 'trash'" class="drive-command-btn danger" type="button" title="永久删除" :disabled="!selectedIds.length || loading" @click="deleteSelectedPermanently">
              <ion-icon name="close-circle-outline" aria-hidden="true" />
              <span>永久删除</span>
            </button>
          </div>

          <input ref="fileInput" class="drive-hidden-input" type="file" multiple @change="handleFileInput">
          <input ref="folderInput" class="drive-hidden-input" type="file" webkitdirectory directory multiple @change="handleFolderInput">
        </div>

        <div class="drive-address-row" @click.stop>
          <nav v-if="activeSpace === 'files'" class="drive-breadcrumb" aria-label="路径">
            <button
              v-for="(crumb, index) in breadcrumbs"
              :key="crumb.id"
              type="button"
              class="drive-crumb"
              @click="openFolderById(crumb.id)"
            >
              <ion-icon v-if="index === 0" name="home-outline" aria-hidden="true" />
              <span>{{ crumb.name }}</span>
              <ion-icon v-if="index < breadcrumbs.length - 1" name="chevron-forward-outline" aria-hidden="true" />
            </button>
          </nav>
          <div v-else class="drive-breadcrumb drive-trash-title">
            <ion-icon name="trash-outline" aria-hidden="true" />
            <span>回收站</span>
          </div>

          <label class="drive-search">
            <ion-icon name="search-outline" aria-hidden="true" />
            <input v-model.trim="query" type="search" placeholder="搜索当前视图">
          </label>
        </div>

        <div class="drive-viewbar" @click.stop>
          <div class="drive-summary">
            <strong>{{ currentTitle }}</strong>
            <span>{{ visibleEntries.length }} 项</span>
            <span v-if="selectedIds.length">{{ selectedIds.length }} 已选</span>
          </div>
          <div class="drive-view-controls">
            <label class="drive-select-label">
              <span>排序</span>
              <select v-model="sortKey">
                <option value="name">名称</option>
                <option value="kind">类型</option>
                <option value="size">大小</option>
                <option value="updatedAt">修改时间</option>
              </select>
            </label>
            <button class="drive-icon-btn" type="button" :title="sortDir === 'asc' ? '升序' : '降序'" :aria-label="sortDir === 'asc' ? '升序' : '降序'" @click="toggleSortDir">
              <ion-icon :name="sortDir === 'asc' ? 'arrow-up-outline' : 'arrow-down-outline'" aria-hidden="true" />
            </button>
            <div class="drive-segmented" role="group" aria-label="视图">
              <button type="button" title="详细信息" :class="{ active: viewMode === 'details' }" @click="viewMode = 'details'">
                <ion-icon name="list-outline" aria-hidden="true" />
              </button>
              <button type="button" title="大图标" :class="{ active: viewMode === 'grid' }" @click="viewMode = 'grid'">
                <ion-icon name="grid-outline" aria-hidden="true" />
              </button>
            </div>
            <button class="drive-icon-btn" type="button" title="详情窗格" aria-label="详情窗格" :class="{ active: inspectorOpen }" @click="inspectorOpen = !inspectorOpen">
              <ion-icon name="information-circle-outline" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div
          class="drive-content"
          :class="{ 'drive-content-grid': viewMode === 'grid', 'drive-content-details': viewMode === 'details' }"
          tabindex="0"
          @keydown="handleWorkspaceKeydown"
        >
          <template v-if="visibleEntries.length">
            <div v-if="viewMode === 'details'" class="drive-table-wrap">
              <table class="drive-table" aria-label="文件列表">
                <thead>
                  <tr>
                    <th><button type="button" @click="setSort('name')">名称</button></th>
                    <th><button type="button" @click="setSort('kind')">类型</button></th>
                    <th><button type="button" @click="setSort('size')">大小</button></th>
                    <th><button type="button" @click="setSort('updatedAt')">修改时间</button></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(entry, index) in visibleEntries"
                    :key="entry.id"
                    :class="{ selected: selectedIdSet.has(entry.id) }"
                    @click.stop="selectEntry(entry, index, $event)"
                    @dblclick.stop="activateEntry(entry)"
                    @contextmenu.prevent.stop="openContextMenu(entry, index, $event)"
                  >
                    <td>
                      <span class="drive-name-cell">
                        <DriveEntryIcon :entry="entry" />
                        <span>{{ entry.name }}</span>
                      </span>
                    </td>
                    <td>{{ labelForEntry(entry) }}</td>
                    <td>{{ entry.type === 'folder' ? '-' : formatBytes(entry.size) }}</td>
                    <td>{{ formatDate(entry.updatedAt || entry.deletedAt) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-else class="drive-grid" aria-label="文件网格">
              <button
                v-for="(entry, index) in visibleEntries"
                :key="entry.id"
                class="drive-grid-item"
                type="button"
                :class="{ selected: selectedIdSet.has(entry.id) }"
                @click.stop="selectEntry(entry, index, $event)"
                @dblclick.stop="activateEntry(entry)"
                @contextmenu.prevent.stop="openContextMenu(entry, index, $event)"
              >
                <span class="drive-grid-icon">
                  <DriveEntryIcon :entry="entry" />
                </span>
                <span class="drive-grid-name">{{ entry.name }}</span>
                <span class="drive-grid-meta">{{ entry.type === 'folder' ? folderChildCount(entry) + ' 项' : formatBytes(entry.size) }}</span>
              </button>
            </div>
          </template>

          <div v-else class="drive-empty">
            <ion-icon :name="activeSpace === 'trash' ? 'trash-outline' : 'folder-open-outline'" aria-hidden="true" />
            <strong>{{ emptyTitle }}</strong>
          </div>
        </div>

        <div class="drive-statusbar" @click.stop>
          <span>{{ statusMessage || '就绪' }}</span>
          <button v-if="activeSpace === 'trash' && trashCount" class="drive-text-btn danger" type="button" :disabled="loading" @click="emptyTrash">
            清空回收站
          </button>
        </div>
      </section>

      <aside v-if="inspectorOpen" class="drive-inspector" aria-label="详情窗格">
        <template v-if="singleSelectedEntry">
          <div class="drive-preview">
            <img v-if="previewKind === 'image'" :src="previewUrl" alt="">
            <video v-else-if="previewKind === 'video'" :src="previewUrl" controls />
            <audio v-else-if="previewKind === 'audio'" :src="previewUrl" controls />
            <iframe v-else-if="previewKind === 'pdf'" :src="previewUrl" title="PDF 预览" />
            <textarea
              v-else-if="editableTextEntry"
              ref="textEditor"
              class="drive-text-editor"
              :value="textPreview"
              aria-label="文本编辑器"
              spellcheck="false"
              @input="handleTextEditorInput"
              @blur="saveTextPreviewIfNeeded({ silent: true })"
              @keydown.stop
              @copy.stop
              @cut.stop
              @paste.stop
            />
            <pre v-else-if="previewKind === 'text'">{{ textPreview }}</pre>
            <div v-else class="drive-preview-placeholder">
              <DriveEntryIcon :entry="singleSelectedEntry" />
            </div>
          </div>

          <div class="drive-info-block">
            <h2>{{ singleSelectedEntry.name }}</h2>
            <dl>
              <div>
                <dt>类型</dt>
                <dd>{{ labelForEntry(singleSelectedEntry) }}</dd>
              </div>
              <div v-if="singleSelectedEntry.type === 'file'">
                <dt>大小</dt>
                <dd>{{ formatBytes(singleSelectedEntry.size) }}</dd>
              </div>
              <div v-if="singleSelectedEntry.deletedAt">
                <dt>删除时间</dt>
                <dd>{{ formatDate(singleSelectedEntry.deletedAt) }}</dd>
              </div>
              <div>
                <dt>修改时间</dt>
                <dd>{{ formatDate(singleSelectedEntry.updatedAt) }}</dd>
              </div>
              <div>
                <dt>路径</dt>
                <dd>{{ singleSelectedEntry.path }}</dd>
              </div>
              <div v-if="editableTextEntry">
                <dt>保存状态</dt>
                <dd :class="{ 'drive-save-error': textSaveError }">{{ textEditorStatus }}</dd>
              </div>
            </dl>
          </div>
        </template>

        <template v-else>
          <div class="drive-preview-placeholder drive-preview-wide">
            <ion-icon name="cloud-outline" aria-hidden="true" />
          </div>
          <div class="drive-info-block">
            <h2>{{ currentTitle }}</h2>
            <dl>
              <div>
                <dt>项目</dt>
                <dd>{{ visibleEntries.length }}</dd>
              </div>
              <div>
                <dt>文件</dt>
                <dd>{{ activeFilesCount }}</dd>
              </div>
              <div>
                <dt>文件夹</dt>
                <dd>{{ activeFoldersCount }}</dd>
              </div>
            </dl>
          </div>
        </template>
      </aside>
    </main>

    <div v-if="dragActive" class="drive-drop-overlay" aria-hidden="true">
      <div>
        <ion-icon name="cloud-upload-outline" aria-hidden="true" />
        <span>松开以上传到当前文件夹</span>
      </div>
    </div>

    <div v-if="dialogMode" class="drive-modal-backdrop" @click.self="closeDialog">
      <form class="drive-dialog" @submit.prevent="submitDialog">
        <h2>{{ dialogMode === 'create-folder' ? '新建文件夹' : '重命名' }}</h2>
        <label class="drive-field">
          <span>名称</span>
          <input ref="dialogInput" v-model.trim="dialogValue" type="text" required>
        </label>
        <p v-if="dialogError" class="drive-error" role="alert">{{ dialogError }}</p>
        <div class="drive-dialog-actions">
          <button class="drive-command-btn" type="button" @click="closeDialog">取消</button>
          <button class="drive-primary-btn" type="submit" :disabled="loading">确定</button>
        </div>
      </form>
    </div>

    <div
      v-if="contextMenu.open"
      class="drive-context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <button v-if="contextEntry?.type === 'folder' && activeSpace === 'files'" type="button" @click="activateContextEntry">
        <ion-icon name="open-outline" aria-hidden="true" />
        <span>打开</span>
      </button>
      <button type="button" :disabled="!selectedFiles.length" @click="downloadSelectedFromMenu">
        <ion-icon name="download-outline" aria-hidden="true" />
        <span>下载</span>
      </button>
      <button v-if="activeSpace === 'files'" type="button" :disabled="!selectedIds.length" @click="copySelectedFromMenu">
        <ion-icon name="copy-outline" aria-hidden="true" />
        <span>复制</span>
      </button>
      <button type="button" :disabled="activeSpace === 'trash' || selectedIds.length !== 1" @click="openRenameDialogFromMenu">
        <ion-icon name="create-outline" aria-hidden="true" />
        <span>重命名</span>
      </button>
      <button v-if="activeSpace === 'files'" type="button" class="danger" @click="moveSelectedToTrashFromMenu">
        <ion-icon name="trash-outline" aria-hidden="true" />
        <span>删除</span>
      </button>
      <button v-else type="button" @click="restoreSelectedFromMenu">
        <ion-icon name="arrow-undo-outline" aria-hidden="true" />
        <span>还原</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { usePublicUrl } from '../composables/usePublicUrl.js'

const ROOT_ID = '/'
const TOKEN_KEY = 'ponychat-drive-token'
const AUTO_REFRESH_MS = 10000
const TEXT_AUTOSAVE_MS = 10000

const DOCUMENT_ICON_RULES = [
  {
    exts: ['doc', 'docx', 'docm', 'dot', 'dotx', 'dotm', 'odt', 'rtf'],
    label: 'Word 文档',
    badge: 'W',
    className: 'drive-file-word',
  },
  {
    exts: ['xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'ods', 'numbers'],
    label: 'Excel 表格',
    badge: 'X',
    className: 'drive-file-excel',
  },
  {
    exts: ['ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'odp', 'key'],
    label: 'PowerPoint 演示文稿',
    badge: 'P',
    className: 'drive-file-powerpoint',
  },
  {
    exts: ['pdf'],
    label: 'PDF 文档',
    badge: 'PDF',
    className: 'drive-file-pdf',
  },
  {
    exts: ['pages'],
    label: 'Pages 文档',
    badge: 'Pg',
    className: 'drive-file-pages',
  },
  {
    exts: ['csv', 'tsv'],
    label: '表格数据',
    badge: 'CSV',
    className: 'drive-file-csv',
  },
  {
    exts: ['txt', 'md', 'markdown', 'log'],
    label: '文本',
    badge: 'TXT',
    className: 'drive-file-text',
  },
  {
    exts: ['js', 'jsx', 'ts', 'tsx', 'vue', 'py', 'java', 'kt', 'cs', 'cpp', 'c', 'h', 'go', 'rs', 'php', 'rb', 'sh', 'ps1', 'bat', 'cmd', 'html', 'css', 'scss', 'json', 'xml', 'yaml', 'yml', 'sql'],
    label: '代码文件',
    badge: '</>',
    className: 'drive-file-code',
  },
]

const ARCHIVE_EXTS = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz']

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

const driveToken = ref(localStorage.getItem(TOKEN_KEY) || '')
const isAuthed = computed(() => Boolean(driveToken.value))
const password = ref('')
const loginError = ref('')
const passwordInput = ref(null)
const fileInput = ref(null)
const folderInput = ref(null)
const dialogInput = ref(null)
const textEditor = ref(null)

const entries = ref([])
const folderTree = ref([])
const currentFolderId = ref(ROOT_ID)
const activeSpace = ref('files')
const selectedIds = ref([])
const lastSelectedIndex = ref(-1)
const query = ref('')
const sortKey = ref('name')
const sortDir = ref('asc')
const viewMode = ref(localStorage.getItem('ponychat-drive-view') || 'details')
const inspectorOpen = ref(localStorage.getItem('ponychat-drive-inspector') !== '0')
const statusMessage = ref('')
const storageLabel = ref('')
const trashCount = ref(0)
const loading = ref(false)
const dragActive = ref(false)
const uploadState = reactive({
  active: false,
  currentName: '',
  totalCount: 0,
  completedCount: 0,
  failedCount: 0,
  totalBytes: 0,
  completedBytes: 0,
  currentLoaded: 0,
  startedAt: 0,
  speedBps: 0,
  error: '',
})
const driveClipboard = ref({ entries: [] })
const expandedFolderIds = ref(new Set([ROOT_ID]))
const previewUrl = ref('')
const previewKind = ref('none')
const textPreview = ref('')
const textDirty = ref(false)
const textSaving = ref(false)
const textSaveError = ref('')
const textSavedAt = ref('')
const textEditPath = ref('')
let previewNonce = 0
let lastSavedText = ''
let autoRefreshTimer = null
let autoSaveTimer = null
let uploadHideTimer = null
let currentUploadXhr = null
let uploadCancelRequested = false
const uploadQueue = []

const dialogMode = ref('')
const dialogValue = ref('')
const dialogError = ref('')

const contextMenu = reactive({
  open: false,
  x: 0,
  y: 0,
  entryId: '',
})

const selectedIdSet = computed(() => new Set(selectedIds.value))
const selectedEntries = computed(() => selectedIds.value.map((id) => entryById(id)).filter(Boolean))
const singleSelectedEntry = computed(() => selectedEntries.value.length === 1 ? selectedEntries.value[0] : null)
const selectedFiles = computed(() => activeSpace.value === 'files' ? selectedEntries.value.filter((entry) => entry.type === 'file') : [])
const contextEntry = computed(() => contextMenu.entryId ? entryById(contextMenu.entryId) : null)
const uploadProgressVisible = computed(() => uploadState.active || uploadState.totalCount > 0)
const uploadRemainingCount = computed(() => Math.max(0, uploadState.totalCount - uploadState.completedCount - uploadState.failedCount))
const uploadProgressPercent = computed(() => {
  if (!uploadState.totalCount) return 0
  if (!uploadState.totalBytes) return Math.min(100, Math.round(((uploadState.completedCount + (uploadState.active ? 0.25 : 0)) / uploadState.totalCount) * 100))
  const done = Math.min(uploadState.totalBytes, uploadState.completedBytes + uploadState.currentLoaded)
  return Math.max(0, Math.min(100, Math.round((done / uploadState.totalBytes) * 100)))
})
const uploadSpeedLabel = computed(() => `${(uploadState.speedBps / 1024 / 1024).toFixed(1)} MB/s`)
const uploadProgressTitle = computed(() => {
  if (uploadState.active && uploadState.currentName) return uploadState.currentName
  if (uploadState.error) return uploadState.error
  if (uploadState.totalCount && uploadRemainingCount.value === 0) return '上传完成'
  return '准备上传'
})
const editableTextEntry = computed(() => {
  const entry = singleSelectedEntry.value
  return Boolean(previewKind.value === 'text' && activeSpace.value === 'files' && isEditableTxtEntry(entry) && textEditPath.value === entry.path)
})
const textEditorStatus = computed(() => {
  if (!editableTextEntry.value) return ''
  if (textSaving.value) return '保存中'
  if (textSaveError.value) return textSaveError.value
  if (textDirty.value) return '有未保存修改'
  if (textSavedAt.value) return `已保存 ${formatTime(textSavedAt.value)}`
  return '已加载'
})

const DriveEntryIcon = (props) => {
  const meta = iconMetaForEntry(props.entry)
  if (meta.badge) {
    return h(
      'span',
      { class: ['drive-entry-icon', 'drive-file-badge', meta.className], title: meta.title },
      [
        h('span', { class: 'drive-file-badge-mark', 'aria-hidden': 'true' }, meta.badge),
        h('span', { class: 'drive-file-badge-fold', 'aria-hidden': 'true' }),
      ],
    )
  }
  return h(
    'span',
    { class: ['drive-entry-icon', 'drive-file-symbol', meta.className], title: meta.title },
    [h('ion-icon', { name: meta.icon, 'aria-hidden': 'true' })],
  )
}

const currentTitle = computed(() => activeSpace.value === 'trash' ? '回收站' : folderNameFromPath(currentFolderId.value))
const activeFilesCount = computed(() => visibleEntries.value.filter((entry) => entry.type === 'file').length)
const activeFoldersCount = computed(() => visibleEntries.value.filter((entry) => entry.type === 'folder').length)

const breadcrumbs = computed(() => {
  const parts = currentFolderId.value.split('/').filter(Boolean)
  const chain = [{ id: ROOT_ID, name: 'PonyDrive' }]
  let path = ''
  for (const part of parts) {
    path += `/${part}`
    chain.push({ id: path, name: part })
  }
  return chain
})

const visibleEntries = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const filtered = needle
    ? entries.value.filter((entry) => entry.name.toLowerCase().includes(needle) || labelForEntry(entry).toLowerCase().includes(needle))
    : entries.value
  return sortEntries(filtered)
})

const emptyTitle = computed(() => {
  if (activeSpace.value === 'trash') return query.value ? '没有匹配的已删除项目' : '回收站是空的'
  return query.value ? '没有匹配项目' : '这个文件夹是空的'
})

const previewEntryKey = computed(() => {
  const entry = singleSelectedEntry.value
  if (!entry) return `${activeSpace.value}:none`
  return [activeSpace.value, entry.id, entry.path, entry.updatedAt || '', entry.size || 0].join(':')
})

const flatFolderTree = computed(() => {
  const byParent = new Map()
  for (const folder of folderTree.value) {
    const list = byParent.get(folder.parentId) || []
    list.push(folder)
    byParent.set(folder.parentId, list)
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN', { numeric: true }))
  }

  const rows = []
  const walk = (parentId, level) => {
    const children = byParent.get(parentId) || []
    for (const folder of children) {
      const hasChildren = (byParent.get(folder.id) || []).length > 0
      const expanded = expandedFolderIds.value.has(folder.id)
      rows.push({ ...folder, level, hasChildren, expanded })
      if (expanded) walk(folder.id, level + 1)
    }
  }
  walk(ROOT_ID, 0)
  return rows
})

watch(viewMode, (value) => localStorage.setItem('ponychat-drive-view', value))
watch(inspectorOpen, (value) => localStorage.setItem('ponychat-drive-inspector', value ? '1' : '0'))
watch(previewEntryKey, () => updatePreview(singleSelectedEntry.value), { immediate: true })

onMounted(async () => {
  document.addEventListener('click', closeContextMenu)
  document.addEventListener('keydown', handleGlobalKeydown)
  document.addEventListener('copy', handleGlobalCopy)
  document.addEventListener('paste', handleGlobalPaste)
  if (!isAuthed.value) {
    await nextTick()
    passwordInput.value?.focus()
    return
  }
  await loadDrive()
  startDriveTimers()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeContextMenu)
  document.removeEventListener('keydown', handleGlobalKeydown)
  document.removeEventListener('copy', handleGlobalCopy)
  document.removeEventListener('paste', handleGlobalPaste)
  stopDriveTimers()
  window.clearTimeout(uploadHideTimer)
  revokePreview()
})

async function driveRequest(endpoint, options = {}) {
  const headers = new Headers(options.headers || {})
  if (driveToken.value) headers.set('Authorization', `Bearer ${driveToken.value}`)

  let body = options.body
  if (body && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(body)
  }

  const response = await fetch(`/api/drive${endpoint}`, {
    method: options.method || 'GET',
    headers,
    body,
  })

  if (response.status === 401 && endpoint !== '/login') {
    logout(false)
    throw new Error('Drive 登录已过期')
  }
  const responseText = options.blob ? '' : await response.text()
  if (!response.ok) {
    throw new Error(parseDriveError(response.status, responseText))
  }
  if (options.blob) return response.blob()
  return responseText ? JSON.parse(responseText) : {}
}

function parseDriveError(status, text) {
  if (text) {
    try {
      const data = JSON.parse(text)
      return data.detail || data.message || `操作失败 (${status})`
    } catch (_) {
      return readableResponseError(status, text)
    }
  }
  return `操作失败 (${status})`
}

function readableResponseError(status, text) {
  if (status === 413) return '文件太大，服务器拒绝了本次上传'
  const compact = String(text || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return compact || `操作失败 (${status})`
}

async function handleLogin() {
  loginError.value = ''
  loading.value = true
  try {
    const data = await driveRequest('/login', {
      method: 'POST',
      body: { password: password.value },
    })
    driveToken.value = data.token
    localStorage.setItem(TOKEN_KEY, data.token)
    password.value = ''
    await nextTick()
    await loadDrive()
    startDriveTimers()
  } catch (error) {
    loginError.value = error instanceof Error ? error.message : '登录失败'
    password.value = ''
    await nextTick()
    passwordInput.value?.focus()
  } finally {
    loading.value = false
  }
}

function logout(clearMessage = true) {
  stopDriveTimers()
  window.clearTimeout(uploadHideTimer)
  localStorage.removeItem(TOKEN_KEY)
  driveToken.value = ''
  entries.value = []
  folderTree.value = []
  resetTextEditorState()
  resetUploadProgress()
  clearSelection()
  if (clearMessage) statusMessage.value = ''
  nextTick(() => passwordInput.value?.focus())
}

function startDriveTimers() {
  stopDriveTimers()
  if (!driveToken.value) return
  autoRefreshTimer = window.setInterval(() => {
    autoRefreshDriveData()
  }, AUTO_REFRESH_MS)
  autoSaveTimer = window.setInterval(() => {
    saveTextPreviewIfNeeded({ silent: true, auto: true })
  }, TEXT_AUTOSAVE_MS)
}

function stopDriveTimers() {
  if (autoRefreshTimer) window.clearInterval(autoRefreshTimer)
  if (autoSaveTimer) window.clearInterval(autoSaveTimer)
  autoRefreshTimer = null
  autoSaveTimer = null
}

async function autoRefreshDriveData() {
  if (!driveToken.value || loading.value || dialogMode.value) return
  await loadDrive({ preserveSelection: true, silent: true, showLoading: false })
}

function replaceIfChanged(targetRef, nextValue) {
  if (JSON.stringify(targetRef.value) === JSON.stringify(nextValue)) return false
  targetRef.value = nextValue
  return true
}

function sameStringArray(a, b) {
  if (a.length !== b.length) return false
  return a.every((value, index) => value === b[index])
}

function restoreSelection(previousIds) {
  const validIds = new Set(entries.value.map((entry) => entry.id))
  const nextIds = previousIds.filter((id) => validIds.has(id))
  if (!sameStringArray(selectedIds.value, nextIds)) selectedIds.value = nextIds
  if (!nextIds.length) {
    lastSelectedIndex.value = -1
    return
  }
  const index = visibleEntries.value.findIndex((entry) => entry.id === nextIds[nextIds.length - 1])
  lastSelectedIndex.value = index >= 0 ? index : -1
}

async function loadDrive(options = {}) {
  if (!driveToken.value) return
  const { preserveSelection = false, silent = false, showLoading = true } = options
  if (showLoading) loading.value = true
  try {
    await loadTree()
    if (activeSpace.value === 'trash') await loadTrash({ preserveSelection })
    else await loadList(currentFolderId.value, { preserveSelection })
    if (!silent) statusMessage.value = '已刷新'
  } catch (error) {
    if (!silent) setStatusError(error)
  } finally {
    if (showLoading) loading.value = false
  }
}

async function loadTree() {
  const data = await driveRequest('/tree')
  replaceIfChanged(folderTree, (data.folders || []).map(normalizeEntry))
}

async function loadList(path = ROOT_ID, options = {}) {
  const previousIds = selectedIds.value.slice()
  const data = await driveRequest(`/list?path=${encodeURIComponent(path)}`)
  currentFolderId.value = data.path || path
  activeSpace.value = 'files'
  replaceIfChanged(entries, (data.items || []).map(normalizeEntry))
  applyUsage(data)
  if (options.preserveSelection) restoreSelection(previousIds)
  else clearSelection()
}

async function loadTrash(options = {}) {
  const previousIds = selectedIds.value.slice()
  const data = await driveRequest('/trash')
  activeSpace.value = 'trash'
  replaceIfChanged(entries, (data.items || []).map(normalizeEntry))
  applyUsage(data)
  if (options.preserveSelection) restoreSelection(previousIds)
  else clearSelection()
}

function normalizeEntry(entry) {
  const path = entry.path || entry.id || ROOT_ID
  return {
    ...entry,
    id: entry.trashId || entry.id || path,
    path,
    parentId: entry.parentId || parentPath(path),
    size: Number(entry.size || 0),
    totalSize: Number(entry.totalSize || entry.size || 0),
    childCount: Number(entry.childCount || 0),
    mime: entry.mime || '',
  }
}

function applyUsage(data) {
  trashCount.value = Number(data.trashCount || 0)
  const used = Number(data.usage?.usedBytes || 0)
  const trash = Number(data.usage?.trashBytes || 0)
  storageLabel.value = trash > 0 ? `${formatBytes(used)} 已使用 · 回收站 ${formatBytes(trash)}` : `${formatBytes(used)} 已使用`
}

function setStatusError(error) {
  statusMessage.value = error instanceof Error ? error.message : String(error || '操作失败')
}

function goToFilesRoot() {
  query.value = ''
  openFolderById(ROOT_ID)
}

async function openFolderById(id) {
  activeSpace.value = 'files'
  query.value = ''
  expandFolder(id || ROOT_ID)
  await loadList(id || ROOT_ID)
}

async function openTrash() {
  query.value = ''
  await loadTrash()
}

function openFilePicker() {
  if (activeSpace.value === 'trash') return
  fileInput.value?.click()
}

function openFolderPicker() {
  if (activeSpace.value === 'trash') return
  folderInput.value?.click()
}

function handleFileInput(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  uploadFiles(files, false)
}

function handleFolderInput(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  uploadFiles(files, true)
}

function uploadFiles(files, preserveFolders) {
  if (!files.length || activeSpace.value === 'trash') return
  const targetPath = currentFolderId.value
  window.clearTimeout(uploadHideTimer)
  if (!uploadState.active && !uploadQueue.length && uploadState.totalCount) {
    resetUploadProgress()
  }

  const jobs = files.map((file) => ({
    file,
    name: file.name || '未命名文件',
    relativePath: preserveFolders ? (file.webkitRelativePath || file.name) : '',
    targetPath,
    sizeWork: Math.max(Number(file.size || 0), 1),
  }))
  uploadQueue.push(...jobs)
  uploadState.totalCount += jobs.length
  uploadState.totalBytes += jobs.reduce((sum, job) => sum + job.sizeWork, 0)
  if (!uploadState.startedAt) uploadState.startedAt = performance.now()
  uploadState.error = ''
  statusMessage.value = `已加入上传队列 ${jobs.length} 个文件`
  processUploadQueue()
}

function resetUploadProgress() {
  uploadCancelRequested = false
  uploadState.active = false
  uploadState.currentName = ''
  uploadState.totalCount = 0
  uploadState.completedCount = 0
  uploadState.failedCount = 0
  uploadState.totalBytes = 0
  uploadState.completedBytes = 0
  uploadState.currentLoaded = 0
  uploadState.startedAt = 0
  uploadState.speedBps = 0
  uploadState.error = ''
}

function cancelUpload() {
  if (!uploadState.active && !uploadQueue.length) return
  uploadCancelRequested = true
  uploadQueue.splice(0)
  uploadState.currentName = '上传已取消'
  uploadState.error = '上传已取消'
  statusMessage.value = '正在取消上传...'
  currentUploadXhr?.abort()
}

async function processUploadQueue() {
  if (uploadState.active) return
  uploadCancelRequested = false
  uploadState.active = true
  if (!uploadState.startedAt) uploadState.startedAt = performance.now()
  try {
    while (uploadQueue.length && !uploadCancelRequested) {
      const job = uploadQueue.shift()
      uploadState.currentName = job.name
      uploadState.currentLoaded = 0
      uploadState.error = ''
      const form = new FormData()
      form.append('path', job.targetPath)
      form.append('files', job.file, job.name)
      form.append('relative_paths', job.relativePath)

      try {
        await driveUploadRequest(form, (event) => {
          if (!event.lengthComputable || !event.total) return
          uploadState.currentLoaded = Math.min(job.sizeWork, (event.loaded / event.total) * job.sizeWork)
          updateUploadSpeed()
        })
        uploadState.completedCount += 1
        uploadState.completedBytes = Math.min(uploadState.totalBytes, uploadState.completedBytes + job.sizeWork)
      } catch (error) {
        if (uploadCancelRequested || isUploadCancelError(error)) {
          uploadState.error = '上传已取消'
          statusMessage.value = '上传已取消'
          break
        }
        uploadState.failedCount += 1
        uploadState.error = error instanceof Error ? error.message : '上传失败'
        statusMessage.value = uploadState.error
        uploadState.completedBytes = Math.min(uploadState.totalBytes, uploadState.completedBytes + job.sizeWork)
      } finally {
        uploadState.currentLoaded = 0
        updateUploadSpeed()
      }
    }
  } finally {
    const wasCancelled = uploadCancelRequested
    if (wasCancelled) uploadQueue.splice(0)
    uploadState.active = false
    if (wasCancelled) {
      uploadState.currentName = '上传已取消'
      uploadState.error = '上传已取消'
      statusMessage.value = uploadState.completedCount
        ? `已取消上传，已完成 ${uploadState.completedCount} 个文件`
        : '上传已取消'
    } else {
      uploadState.currentName = uploadState.failedCount ? `${uploadState.failedCount} 个文件上传失败` : '上传完成'
      statusMessage.value = uploadState.failedCount
        ? `上传完成，失败 ${uploadState.failedCount} 个`
        : `已上传 ${uploadState.completedCount} 个文件`
    }
    await loadTree()
    if (activeSpace.value === 'files') await loadList(currentFolderId.value, { preserveSelection: true })
    else if (activeSpace.value === 'trash') await loadTrash({ preserveSelection: true })
    uploadHideTimer = window.setTimeout(() => {
      if (!uploadState.active && !uploadQueue.length) resetUploadProgress()
    }, 6000)
  }
}

function updateUploadSpeed() {
  if (!uploadState.startedAt) return
  const elapsedSeconds = Math.max((performance.now() - uploadState.startedAt) / 1000, 0.1)
  uploadState.speedBps = Math.max(0, (uploadState.completedBytes + uploadState.currentLoaded) / elapsedSeconds)
}

function isUploadCancelError(error) {
  return error instanceof Error && error.message === '上传已取消'
}

function driveUploadRequest(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    let settled = false
    const settle = (callback) => {
      if (settled) return
      settled = true
      if (currentUploadXhr === xhr) currentUploadXhr = null
      callback()
    }
    currentUploadXhr = xhr
    xhr.open('POST', '/api/drive/upload')
    if (driveToken.value) xhr.setRequestHeader('Authorization', `Bearer ${driveToken.value}`)
    xhr.upload.onprogress = onProgress
    xhr.onabort = () => settle(() => reject(new Error('上传已取消')))
    xhr.onerror = () => settle(() => reject(new Error('网络中断，上传失败')))
    xhr.onload = () => {
      if (xhr.status === 401) {
        logout(false)
        settle(() => reject(new Error('Drive 登录已过期')))
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        settle(() => reject(new Error(parseDriveError(xhr.status, xhr.responseText))))
        return
      }
      let response
      try {
        response = xhr.responseText ? JSON.parse(xhr.responseText) : {}
      } catch (_) {
        settle(() => reject(new Error('上传响应解析失败')))
        return
      }
      settle(() => resolve(response))
    }
    xhr.send(form)
  })
}

function openCreateFolderDialog() {
  if (activeSpace.value === 'trash') return
  dialogMode.value = 'create-folder'
  dialogValue.value = '新建文件夹'
  dialogError.value = ''
  nextTick(() => {
    dialogInput.value?.focus()
    dialogInput.value?.select()
  })
}

function openRenameDialog() {
  if (selectedIds.value.length !== 1 || activeSpace.value === 'trash') return
  dialogMode.value = 'rename'
  dialogValue.value = selectedEntries.value[0]?.name || ''
  dialogError.value = ''
  nextTick(() => {
    dialogInput.value?.focus()
    dialogInput.value?.select()
  })
}

function openRenameDialogFromMenu() {
  closeContextMenu()
  openRenameDialog()
}

function closeDialog() {
  dialogMode.value = ''
  dialogValue.value = ''
  dialogError.value = ''
}

async function submitDialog() {
  const name = sanitizeName(dialogValue.value)
  if (!name) {
    dialogError.value = '名称不能为空'
    return
  }

  loading.value = true
  try {
    if (dialogMode.value === 'create-folder') {
      await driveRequest('/folder', {
        method: 'POST',
        body: { path: currentFolderId.value, name },
      })
      statusMessage.value = `已新建 ${name}`
    } else if (dialogMode.value === 'rename') {
      const entry = selectedEntries.value[0]
      if (!entry) return
      await driveRequest('/rename', {
        method: 'POST',
        body: { path: entry.path, name },
      })
      statusMessage.value = `已重命名为 ${name}`
    }
    closeDialog()
    await loadTree()
    await loadList(currentFolderId.value)
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    loading.value = false
  }
}

async function moveSelectedToTrash() {
  if (!selectedIds.value.length || activeSpace.value !== 'files') return
  loading.value = true
  try {
    await driveRequest('/delete', {
      method: 'POST',
      body: { paths: selectedEntries.value.map((entry) => entry.path) },
    })
    statusMessage.value = `已移入回收站 ${selectedIds.value.length} 项`
    await loadTree()
    await loadList(currentFolderId.value)
  } catch (error) {
    setStatusError(error)
  } finally {
    loading.value = false
  }
}

async function moveSelectedToTrashFromMenu() {
  closeContextMenu()
  await moveSelectedToTrash()
}

async function restoreSelected() {
  if (!selectedIds.value.length || activeSpace.value !== 'trash') return
  loading.value = true
  try {
    await driveRequest('/restore', {
      method: 'POST',
      body: { ids: selectedIds.value },
    })
    statusMessage.value = `已还原 ${selectedIds.value.length} 项`
    await loadTree()
    await loadTrash()
  } catch (error) {
    setStatusError(error)
  } finally {
    loading.value = false
  }
}

async function restoreSelectedFromMenu() {
  closeContextMenu()
  await restoreSelected()
}

async function deleteSelectedPermanently() {
  if (!selectedIds.value.length || activeSpace.value !== 'trash') return
  if (!window.confirm('永久删除选中的项目？')) return
  loading.value = true
  try {
    await driveRequest('/permanent-delete', {
      method: 'POST',
      body: { ids: selectedIds.value },
    })
    statusMessage.value = `已永久删除 ${selectedIds.value.length} 项`
    await loadTrash()
  } catch (error) {
    setStatusError(error)
  } finally {
    loading.value = false
  }
}

async function emptyTrash() {
  if (!trashCount.value) return
  if (!window.confirm('清空回收站？')) return
  loading.value = true
  try {
    await driveRequest('/empty-trash', { method: 'POST' })
    statusMessage.value = '回收站已清空'
    await loadTrash()
  } catch (error) {
    setStatusError(error)
  } finally {
    loading.value = false
  }
}

async function downloadSelected() {
  for (const entry of selectedFiles.value) {
    const blob = await fetchFileBlob(entry)
    triggerDownload(blob, entry.name)
  }
}

function downloadSelectedFromMenu() {
  closeContextMenu()
  downloadSelected()
}

function copySelectedFromMenu() {
  closeContextMenu()
  copySelectedToDriveClipboard()
}

function copySelectedToDriveClipboard(event = null) {
  if (activeSpace.value !== 'files' || !selectedEntries.value.length || loading.value) return false
  const entriesToCopy = selectedEntries.value.map((entry) => ({
    id: entry.id,
    path: entry.path,
    name: entry.name,
    type: entry.type,
  }))
  driveClipboard.value = {
    entries: entriesToCopy,
    copiedAt: Date.now(),
  }

  const textValue = entriesToCopy.map((entry) => entry.path).join('\n')
  if (event?.clipboardData) {
    event.clipboardData.setData('text/plain', textValue)
  } else if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(textValue).catch(() => {})
  }
  statusMessage.value = `已复制 ${entriesToCopy.length} 项，Ctrl+V 可在 Drive 内粘贴`
  return true
}

async function pasteDriveClipboard() {
  if (activeSpace.value !== 'files' || loading.value) return false
  const entriesToPaste = driveClipboard.value.entries || []
  if (!entriesToPaste.length) return false
  loading.value = true
  try {
    const data = await driveRequest('/copy', {
      method: 'POST',
      body: {
        paths: entriesToPaste.map((entry) => entry.path),
        target_path: currentFolderId.value,
      },
    })
    statusMessage.value = `已粘贴 ${data.items?.length || entriesToPaste.length} 项`
    await loadTree()
    await loadList(currentFolderId.value)
  } catch (error) {
    setStatusError(error)
  } finally {
    loading.value = false
  }
  return true
}

function resetTextEditorState() {
  textDirty.value = false
  textSaving.value = false
  textSaveError.value = ''
  textSavedAt.value = ''
  textEditPath.value = ''
  lastSavedText = ''
}

function handleTextEditorInput(event) {
  const value = event.target?.value || ''
  textPreview.value = value
  textDirty.value = value !== lastSavedText
  if (textSaveError.value) textSaveError.value = ''
}

function filenameFromPath(path) {
  const parts = String(path || '').split('/').filter(Boolean)
  return parts[parts.length - 1] || '文本文件'
}

function updateEntryInList(item) {
  if (!item) return
  const normalized = normalizeEntry(item)
  const index = entries.value.findIndex((entry) => entry.path === normalized.path)
  if (index < 0) return
  const next = entries.value.slice()
  next[index] = { ...next[index], ...normalized }
  replaceIfChanged(entries, next)
}

async function saveTextPreviewIfNeeded(options = {}) {
  const { silent = false, auto = false } = options
  if (!textEditPath.value || !textDirty.value || textSaving.value) return false
  const path = textEditPath.value
  const content = textPreview.value
  textSaving.value = true
  textSaveError.value = ''
  try {
    const data = await driveRequest('/text', {
      method: 'POST',
      body: { path, content },
    })
    if (textEditPath.value === path) {
      lastSavedText = content
      textDirty.value = textPreview.value !== lastSavedText
      textSavedAt.value = data.saved_at || new Date().toISOString()
      textSaveError.value = ''
    }
    updateEntryInList(data.item)
    applyUsage(data)
    if (auto) statusMessage.value = `已自动保存 ${filenameFromPath(path)}`
    else if (!silent) statusMessage.value = `已保存 ${filenameFromPath(path)}`
    return true
  } catch (error) {
    const message = error instanceof Error ? error.message : '保存失败'
    textSaveError.value = message
    if (!silent || auto) statusMessage.value = message
    return false
  } finally {
    textSaving.value = false
  }
}

async function fetchFileBlob(entry) {
  return driveRequest(`/download?path=${encodeURIComponent(entry.path)}`, { blob: true })
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 500)
}

function selectEntry(entry, index, event) {
  const id = entry.id
  if (event.shiftKey && lastSelectedIndex.value >= 0) {
    const start = Math.min(lastSelectedIndex.value, index)
    const end = Math.max(lastSelectedIndex.value, index)
    selectedIds.value = visibleEntries.value.slice(start, end + 1).map((item) => item.id)
    return
  }
  if (event.ctrlKey || event.metaKey) {
    const next = new Set(selectedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selectedIds.value = Array.from(next)
    lastSelectedIndex.value = index
    return
  }
  selectedIds.value = [id]
  lastSelectedIndex.value = index
}

function clearSelection() {
  selectedIds.value = []
  lastSelectedIndex.value = -1
}

function activateEntry(entry) {
  if (activeSpace.value !== 'files') return
  if (entry.type === 'folder') openFolderById(entry.path)
}

function activateContextEntry() {
  const entry = contextEntry.value
  closeContextMenu()
  if (entry) activateEntry(entry)
}

function toggleTreeFolder(id) {
  const next = new Set(expandedFolderIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedFolderIds.value = next
}

function expandFolder(id) {
  const next = new Set(expandedFolderIds.value)
  next.add(id)
  expandedFolderIds.value = next
}

function openContextMenu(entry, index, event) {
  if (!selectedIdSet.value.has(entry.id)) selectEntry(entry, index, event)
  contextMenu.open = true
  contextMenu.entryId = entry.id
  contextMenu.x = Math.min(event.clientX, window.innerWidth - 190)
  contextMenu.y = Math.min(event.clientY, window.innerHeight - 210)
}

function closeContextMenu() {
  contextMenu.open = false
  contextMenu.entryId = ''
}

function isEditableTarget(target) {
  const element = target instanceof HTMLElement ? target : null
  return Boolean(element?.closest('input, textarea, select, [contenteditable="true"]'))
}

function handleGlobalCopy(event) {
  if (isEditableTarget(event.target) || dialogMode.value) return
  if (copySelectedToDriveClipboard(event)) {
    event.preventDefault()
  }
}

async function handleGlobalPaste(event) {
  if (isEditableTarget(event.target) || dialogMode.value || !isAuthed.value) return
  const files = Array.from(event.clipboardData?.files || [])
  if (files.length) {
    event.preventDefault()
    closeContextMenu()
    if (activeSpace.value === 'trash') {
      statusMessage.value = '回收站中不能粘贴上传'
      return
    }
    await uploadFiles(files, false)
    return
  }
  if (driveClipboard.value.entries?.length) {
    event.preventDefault()
    closeContextMenu()
    await pasteDriveClipboard()
  }
}

function handleGlobalKeydown(event) {
  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'c' && !isEditableTarget(event.target) && !dialogMode.value) {
    if (copySelectedToDriveClipboard()) event.preventDefault()
    return
  }
  if (event.key === 'Escape') {
    closeContextMenu()
    if (dialogMode.value) closeDialog()
  }
}

function handleWorkspaceKeydown(event) {
  if (dialogMode.value || loading.value) return
  if (event.key === 'Delete') {
    event.preventDefault()
    if (activeSpace.value === 'trash') deleteSelectedPermanently()
    else moveSelectedToTrash()
  } else if (event.key === 'F2') {
    event.preventDefault()
    openRenameDialog()
  } else if (event.key === 'Enter' && singleSelectedEntry.value) {
    event.preventDefault()
    activateEntry(singleSelectedEntry.value)
  }
}

function handleDragOver() {
  if (activeSpace.value !== 'trash') dragActive.value = true
}

function handleDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) dragActive.value = false
}

async function handleDrop(event) {
  dragActive.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  await uploadFiles(files, false)
}

async function updatePreview(entry) {
  if (entry?.path && previewKind.value === 'text' && textEditPath.value === entry.path && activeSpace.value === 'files') {
    return
  }
  if (textDirty.value) {
    await saveTextPreviewIfNeeded({ silent: true })
  }
  const nonce = ++previewNonce
  revokePreview()
  textPreview.value = ''
  resetTextEditorState()
  previewKind.value = 'none'
  if (!entry || entry.type !== 'file' || activeSpace.value !== 'files') return

  if (entry.mime?.startsWith('image/')) previewKind.value = 'image'
  else if (entry.mime?.startsWith('video/')) previewKind.value = 'video'
  else if (entry.mime?.startsWith('audio/')) previewKind.value = 'audio'
  else if (entry.mime === 'application/pdf') previewKind.value = 'pdf'
  else if (entry.mime?.startsWith('text/') || /\.(md|txt|log|json|csv|xml|html|css|js)$/i.test(entry.name)) previewKind.value = 'text'
  else return

  try {
    const blob = await fetchFileBlob(entry)
    if (nonce !== previewNonce) return
    previewUrl.value = URL.createObjectURL(blob)
    if (previewKind.value === 'text') {
      const editable = isEditableTxtEntry(entry)
      const content = editable ? await blob.text() : await blob.slice(0, 12000).text()
      if (nonce !== previewNonce) return
      textPreview.value = content
      if (editable) {
        textEditPath.value = entry.path
        lastSavedText = content
        textDirty.value = false
        await nextTick()
        textEditor.value?.focus()
      }
    }
  } catch (_) {
    if (nonce === previewNonce) previewKind.value = 'none'
  }
}

function revokePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

function entryById(id) {
  return entries.value.find((entry) => entry.id === id) || folderTree.value.find((entry) => entry.id === id) || null
}

function sortEntries(items) {
  const copy = items.slice()
  copy.sort((a, b) => {
    if (a.type !== b.type && sortKey.value === 'name') return a.type === 'folder' ? -1 : 1
    let value = 0
    if (sortKey.value === 'name') value = a.name.localeCompare(b.name, 'zh-Hans-CN', { numeric: true })
    else if (sortKey.value === 'kind') value = labelForEntry(a).localeCompare(labelForEntry(b), 'zh-Hans-CN', { numeric: true })
    else if (sortKey.value === 'size') value = Number(a.size || 0) - Number(b.size || 0)
    else value = new Date(a.updatedAt || a.deletedAt || 0).getTime() - new Date(b.updatedAt || b.deletedAt || 0).getTime()
    return sortDir.value === 'asc' ? value : -value
  })
  return copy
}

function setSort(key) {
  if (sortKey.value === key) toggleSortDir()
  else sortKey.value = key
}

function toggleSortDir() {
  sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
}

function labelForEntry(entry) {
  if (entry.type === 'folder') return '文件夹'
  const documentRule = documentRuleForEntry(entry)
  if (documentRule) return documentRule.label
  if (entry.mime?.startsWith('image/')) return '图片'
  if (entry.mime?.startsWith('video/')) return '视频'
  if (entry.mime?.startsWith('audio/')) return '音频'
  if (entry.mime?.includes('zip') || ARCHIVE_EXTS.includes(extensionOf(entry.name))) return '压缩包'
  if (entry.mime?.startsWith('text/')) return '文本'
  const ext = extensionOf(entry.name)
  return ext ? `${ext.toUpperCase()} 文件` : '文件'
}

function iconMetaForEntry(entry) {
  if (entry.type === 'folder') {
    return { icon: 'folder-outline', className: 'drive-file-folder', title: '文件夹' }
  }
  const documentRule = documentRuleForEntry(entry)
  if (documentRule) {
    return { badge: documentRule.badge, className: documentRule.className, title: documentRule.label }
  }
  if (entry.mime?.startsWith('image/')) {
    return { icon: 'image-outline', className: 'drive-file-image', title: '图片' }
  }
  if (entry.mime?.startsWith('video/')) {
    return { icon: 'videocam-outline', className: 'drive-file-video', title: '视频' }
  }
  if (entry.mime?.startsWith('audio/')) {
    return { icon: 'musical-notes-outline', className: 'drive-file-audio', title: '音频' }
  }
  if (entry.mime?.includes('zip') || ARCHIVE_EXTS.includes(extensionOf(entry.name))) {
    return { icon: 'archive-outline', className: 'drive-file-archive', title: '压缩包' }
  }
  return { icon: 'document-outline', className: 'drive-file-generic', title: '文件' }
}

function documentRuleForEntry(entry) {
  const ext = extensionOf(entry.name)
  return DOCUMENT_ICON_RULES.find((rule) => rule.exts.includes(ext))
}

function isEditableTxtEntry(entry) {
  return Boolean(entry?.type === 'file' && extensionOf(entry.name) === 'txt')
}

function extensionOf(name) {
  const index = String(name || '').lastIndexOf('.')
  return index > 0 ? name.slice(index + 1).toLowerCase() : ''
}

function folderChildCount(entry) {
  if (typeof entry.childCount === 'number') return entry.childCount
  return folderTree.value.filter((folder) => folder.parentId === entry.path).length
}

function sanitizeName(value) {
  return String(value || '').trim().replace(/[\\/:*?"<>|]/g, '-')
}

function parentPath(path) {
  const parts = String(path || ROOT_ID).split('/').filter(Boolean)
  if (parts.length <= 1) return ROOT_ID
  return `/${parts.slice(0, -1).join('/')}`
}

function folderNameFromPath(path) {
  if (!path || path === ROOT_ID) return 'PonyDrive'
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] || 'PonyDrive'
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let unit = units.shift()
  while (size >= 1024 && units.length) {
    size /= 1024
    unit = units.shift()
  }
  return `${size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${unit}`
}

function formatDate(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}
</script>

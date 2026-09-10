export const ROOT_ID = '/'
export const TOKEN_KEY = 'ponychat-drive-token'
export const AUTO_REFRESH_MS = 10000
export const TEXT_AUTOSAVE_MS = 10000

const DOCUMENT_ICON_RULES = [
  { exts: ['doc', 'docx', 'docm', 'dot', 'dotx', 'dotm', 'odt', 'rtf'], label: 'Word 文档', badge: 'W', className: 'drive-file-word' },
  { exts: ['xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'ods', 'numbers'], label: 'Excel 表格', badge: 'X', className: 'drive-file-excel' },
  { exts: ['ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'odp', 'key'], label: 'PowerPoint 演示文稿', badge: 'P', className: 'drive-file-powerpoint' },
  { exts: ['pdf'], label: 'PDF 文档', badge: 'PDF', className: 'drive-file-pdf' },
  { exts: ['pages'], label: 'Pages 文档', badge: 'Pg', className: 'drive-file-pages' },
  { exts: ['csv', 'tsv'], label: '表格数据', badge: 'CSV', className: 'drive-file-csv' },
  { exts: ['txt', 'md', 'markdown', 'log'], label: '文本', badge: 'TXT', className: 'drive-file-text' },
  {
    exts: ['js', 'jsx', 'ts', 'tsx', 'vue', 'py', 'java', 'kt', 'cs', 'cpp', 'c', 'h', 'go', 'rs', 'php', 'rb', 'sh', 'ps1', 'bat', 'cmd', 'html', 'css', 'scss', 'json', 'xml', 'yaml', 'yml', 'sql'],
    label: '代码文件', badge: '</>', className: 'drive-file-code',
  },
]

const ARCHIVE_EXTS = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz']

export function extensionOf(name) {
  const index = String(name || '').lastIndexOf('.')
  return index > 0 ? name.slice(index + 1).toLowerCase() : ''
}

export function documentRuleForEntry(entry) {
  const ext = extensionOf(entry.name)
  return DOCUMENT_ICON_RULES.find((rule) => rule.exts.includes(ext))
}

export function labelForEntry(entry) {
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

export function iconMetaForEntry(entry) {
  if (entry.type === 'folder') return { icon: 'folder-outline', className: 'drive-file-folder', title: '文件夹' }
  const documentRule = documentRuleForEntry(entry)
  if (documentRule) return { badge: documentRule.badge, className: documentRule.className, title: documentRule.label }
  if (entry.mime?.startsWith('image/')) return { icon: 'image-outline', className: 'drive-file-image', title: '图片' }
  if (entry.mime?.startsWith('video/')) return { icon: 'videocam-outline', className: 'drive-file-video', title: '视频' }
  if (entry.mime?.startsWith('audio/')) return { icon: 'musical-notes-outline', className: 'drive-file-audio', title: '音频' }
  if (entry.mime?.includes('zip') || ARCHIVE_EXTS.includes(extensionOf(entry.name))) {
    return { icon: 'archive-outline', className: 'drive-file-archive', title: '压缩包' }
  }
  return { icon: 'document-outline', className: 'drive-file-generic', title: '文件' }
}

export function isEditableTxtEntry(entry) {
  return Boolean(entry?.type === 'file' && extensionOf(entry.name) === 'txt')
}

export function sanitizeName(value) {
  return String(value || '').trim().replace(/[\\/:*?"<>|]/g, '-')
}

export function parentPath(path) {
  const parts = String(path || ROOT_ID).split('/').filter(Boolean)
  if (parts.length <= 1) return ROOT_ID
  return `/${parts.slice(0, -1).join('/')}`
}

export function folderNameFromPath(path) {
  if (!path || path === ROOT_ID) return 'PonyDrive'
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] || 'PonyDrive'
}

export function formatBytes(value) {
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

export function formatDate(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

export function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(value))
}

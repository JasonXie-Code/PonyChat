import { ref } from 'vue'

export function useDriveDataLoader({ isAuthed, loading, loadTree, loadFiles, setStatus }) {
  const loadError = ref('')
  const dataLoaded = ref(false)
  let pending = null
  let generation = 0

  function resetLoadState() {
    generation += 1
    pending = null
    loading.value = false
    loadError.value = ''
    dataLoaded.value = false
  }

  function loadDrive(options = {}) {
    if (!isAuthed()) return Promise.resolve(false)
    if (pending) return pending
    const session = generation
    const recovering = Boolean(loadError.value)
    const { preserveSelection = false, silent = false, showLoading = true } = options
    if (showLoading) loading.value = true
    if (!dataLoaded.value) setStatus('正在加载文件…')
    pending = (async () => {
      try {
        // A stalled folder tree must not prevent the actual file list from loading.
        const results = await Promise.allSettled([
          Promise.resolve().then(() => loadFiles({ preserveSelection })),
          Promise.resolve().then(loadTree),
        ])
        if (session !== generation) return false
        if (results[0].status === 'rejected') throw results[0].reason
        dataLoaded.value = true
        loadError.value = ''
        if (results[1].status === 'rejected') setStatus('文件已加载，目录树暂不可用，将自动重试')
        else if (!silent || recovering) setStatus('已刷新')
        return true
      } catch (error) {
        if (session !== generation) return false
        loadError.value = error instanceof Error ? error.message : '文件加载失败'
        setStatus(`文件加载失败，将自动重试：${loadError.value}`)
        return false
      } finally {
        if (session === generation) {
          if (showLoading) loading.value = false
          pending = null
        }
      }
    })()
    return pending
  }

  return { loadDrive, loadError, dataLoaded, resetLoadState }
}

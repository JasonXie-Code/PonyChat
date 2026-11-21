import { ref } from 'vue'

export const TEXT_SAVE_DELAY_MS = 350
export const TEXT_MAX_WAIT_MS = 1200
export const TEXT_SYNC_INTERVAL_MS = 1000

// The text channel is independent of the slower folder/usage refresh.
export function useDriveTextSync({ request, onSaved = () => {}, onError = () => {}, now = Date.now }) {
  const textPreview = ref('')
  const textDirty = ref(false)
  const textSaving = ref(false)
  const textSaveError = ref('')
  const textSavedAt = ref('')
  const textEditPath = ref('')
  let savedText = ''
  let generation = 0
  let editVersion = 0
  let saveTimer = null
  let dirtySince = null
  let saving = null
  let refreshing = false
  let composing = false

  function cancelScheduledSave() {
    clearTimeout(saveTimer)
    saveTimer = null
  }

  function resetTextEditorState() {
    cancelScheduledSave()
    generation += 1
    editVersion += 1
    savedText = ''
    dirtySince = null
    composing = false
    textEditPath.value = ''
    textDirty.value = textSaving.value = false
    textSaveError.value = textSavedAt.value = ''
  }

  function openText(path, content) {
    resetTextEditorState()
    textEditPath.value = path
    textPreview.value = savedText = content
  }

  function scheduleSave() {
    cancelScheduledSave()
    if (!textDirty.value || composing) return
    dirtySince ??= now()
    const delay = Math.max(0, Math.min(TEXT_SAVE_DELAY_MS, TEXT_MAX_WAIT_MS - (now() - dirtySince)))
    saveTimer = setTimeout(() => saveTextPreviewIfNeeded({ silent: true, auto: true }), delay)
  }

  function handleTextEditorInput(event) {
    editVersion += 1
    textPreview.value = event.target?.value || ''
    textDirty.value = textPreview.value !== savedText
    textSaveError.value = ''
    composing = Boolean(event.isComposing)
    if (!textDirty.value) dirtySince = null
    scheduleSave()
  }

  function finishTextComposition() {
    composing = false
    scheduleSave()
  }

  async function saveTextPreviewIfNeeded(options = {}) {
    cancelScheduledSave()
    // Serialize writes, including edits made while a previous save is in flight.
    while (saving) await saving
    if (!textEditPath.value || !textDirty.value || composing) return !textDirty.value
    const path = textEditPath.value
    const content = textPreview.value
    const session = generation
    textSaving.value = true
    textSaveError.value = ''
    dirtySince = null
    const pending = (async () => {
      try {
        const data = await request('/text', { method: 'POST', body: { path, content }, timeoutMs: 10000 })
        if (session !== generation) return true
        savedText = content
        textDirty.value = textPreview.value !== savedText
        textSavedAt.value = data.saved_at || new Date().toISOString()
        onSaved(data, path, options)
        return true
      } catch (error) {
        if (session === generation) {
          textSaveError.value = error instanceof Error ? error.message : '保存失败'
          onError(textSaveError.value)
        }
        return false
      } finally {
        if (session === generation) textSaving.value = false
      }
    })()
    saving = pending
    const success = await pending
    if (saving === pending) saving = null
    if (session === generation && textDirty.value && success) scheduleSave()
    return success
  }

  async function refreshTextPreview() {
    if (!textEditPath.value || textDirty.value || textSaving.value || refreshing || composing) return
    const path = textEditPath.value
    const session = generation
    const version = editVersion
    refreshing = true
    try {
      const blob = await request(`/download?path=${encodeURIComponent(path)}&_sync=${now()}`, {
        blob: true, cache: 'no-store', timeoutMs: 10000,
      })
      const content = await blob.text()
      // An older download must never replace new typing, even if that typing was already saved.
      if (session !== generation || version !== editVersion || textDirty.value || textSaving.value) return
      if (content !== savedText) {
        textPreview.value = savedText = content
        textSavedAt.value = new Date().toISOString()
      }
      textSaveError.value = ''
    } catch (error) {
      if (session === generation && version === editVersion) {
        textSaveError.value = `同步失败，将自动重试：${error instanceof Error ? error.message : '网络异常'}`
      }
    } finally {
      refreshing = false
    }
  }

  return {
    textPreview, textDirty, textSaving, textSaveError, textSavedAt, textEditPath,
    openText, resetTextEditorState, handleTextEditorInput, finishTextComposition,
    saveTextPreviewIfNeeded, refreshTextPreview, cancelScheduledSave,
  }
}

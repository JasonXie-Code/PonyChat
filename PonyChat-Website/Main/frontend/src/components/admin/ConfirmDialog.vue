<template>
  <Teleport to="body">
    <div
      v-if="state.open"
      class="confirm-mask admin-shell"
      role="presentation"
      @mousedown="onBackdropMouseDown"
      @click.self="onBackdropClickSelf"
    >
      <div class="confirm-box card" role="dialog" aria-modal="true" :aria-labelledby="uid">
        <header class="confirm-header">
          <h3 :id="uid" class="confirm-title">{{ state.title }}</h3>
        </header>
        <div class="confirm-body">
          <p class="confirm-msg">{{ state.message }}</p>
        </div>
        <footer class="confirm-footer">
          <div class="confirm-actions">
            <button type="button" class="btn" @click="cancel">{{ state.cancelText }}</button>
            <button
              type="button"
              class="btn"
              :class="state.danger ? 'btn-danger' : 'btn-primary'"
              @click="ok"
            >
              {{ state.confirmText }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useConfirmState, resolveConfirm } from '../../composables/useConfirm'
import { useModalBackdropDismiss } from '../../composables/useModalBackdropDismiss'
import '../../styles/admin-shell.css'

const state = useConfirmState()
const uid = 'admin-confirm-title'
const { onBackdropMouseDown, onBackdropClickSelf } = useModalBackdropDismiss(cancel)

function ok() {
  resolveConfirm(true)
}
function cancel() {
  resolveConfirm(false)
}
</script>

<style scoped>
.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 9998;
  background: rgba(15, 23, 42, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.confirm-box {
  width: min(480px, 100%);
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.confirm-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  flex-shrink: 0;
}
.confirm-title {
  margin: 0;
  font-size: 1.05rem;
  font-family: var(--font-display, inherit);
  font-weight: 600;
  line-height: 1.3;
}
.confirm-body {
  padding: 1rem 1.25rem;
  flex: 1;
  min-height: 0;
}
.confirm-msg {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted, #94a3b8);
  white-space: pre-wrap;
  line-height: 1.5;
}
.confirm-footer {
  padding: 0.85rem 1.25rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  flex-shrink: 0;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>

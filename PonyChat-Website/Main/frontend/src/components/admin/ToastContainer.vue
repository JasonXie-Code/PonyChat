<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="t in items"
          :key="t.id"
          class="toast-item"
          :class="'toast-' + t.type"
          role="status"
        >
          <span class="toast-msg">{{ t.message }}</span>
          <button type="button" class="toast-close" aria-label="关闭" @click="remove(t.id)">×</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../../composables/useToast'

const { items, remove } = useToast()
</script>

<style scoped>
.toast-stack {
  position: fixed;
  right: 1.25rem;
  bottom: 1.25rem;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: min(420px, calc(100vw - 2.5rem));
  pointer-events: none;
}
.toast-item {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-radius: var(--radius-md, 10px);
  border: 1px solid var(--stroke, #334155);
  background: rgba(15, 23, 42, 0.95);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  font-size: 0.875rem;
  color: var(--text, #e2e8f0);
}
.toast-success {
  border-color: rgba(61, 168, 130, 0.4);
}
.toast-error {
  border-color: rgba(224, 112, 112, 0.48);
  color: #e8c4c4;
}
.toast-info {
  border-color: rgba(78, 191, 207, 0.42);
}
.toast-msg {
  flex: 1;
  min-width: 0;
  line-height: 1.4;
}
.toast-close {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0 0.15rem;
}
.toast-close:hover {
  color: var(--text, #e2e8f0);
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>

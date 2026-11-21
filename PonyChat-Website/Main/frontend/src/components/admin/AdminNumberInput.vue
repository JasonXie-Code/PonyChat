<script setup>
import { computed } from 'vue'

defineOptions({ inheritAttrs: false })

const model = defineModel({ default: null })

const props = defineProps({
  min: Number,
  max: Number,
  step: { type: Number, default: 1 },
  placeholder: String,
  /** md：默认高度；sm：更紧凑（月/日） */
  size: { type: String, default: 'md' },
  /** 到期日等居中 */
  align: { type: String, default: 'start' },
})

const inputValue = computed(() => {
  const v = model.value
  if (v === undefined || v === null || v === '' || Number.isNaN(Number(v))) return ''
  return String(v)
})

/** 按数字位数变宽，默认至少 minChars（约两位数） */
const inputWidthCh = computed(() => {
  const minChars = 2
  let len = minChars
  const s = inputValue.value
  if (s.length > 0) len = Math.max(len, s.length)
  else if (props.placeholder) len = Math.max(len, [...props.placeholder].length)
  if (props.max != null && Number.isFinite(props.max)) {
    len = Math.max(len, String(Math.trunc(Math.abs(props.max))).length)
  }
  if (props.min != null && Number.isFinite(props.min)) {
    len = Math.max(len, String(Math.trunc(props.min)).length)
  }
  return Math.min(Math.max(len, minChars), 14)
})

function clamp(n) {
  let v = Number(n)
  if (Number.isNaN(v)) return props.min ?? 0
  if (props.min != null && v < props.min) v = props.min
  if (props.max != null && v > props.max) v = props.max
  return v
}

function onInput(e) {
  const raw = e.target.value
  if (raw === '' || raw === '-') {
    model.value = null
    return
  }
  const n = Number(raw)
  if (Number.isNaN(n)) return
  model.value = clamp(n)
}

function currentNum() {
  const v = model.value
  if (v === undefined || v === null) return props.min ?? 0
  const n = Number(v)
  return Number.isNaN(n) ? props.min ?? 0 : n
}

function step(delta) {
  model.value = clamp(currentNum() + delta * props.step)
}
</script>

<template>
  <div
    class="admin-num-wrap"
    :class="[`admin-num-wrap--${props.size}`, align === 'center' ? 'admin-num-wrap--center' : '']"
  >
    <input
      class="admin-num-input"
      type="number"
      :value="inputValue"
      :style="{ width: inputWidthCh + 'ch' }"
      :placeholder="placeholder"
      :min="min"
      :max="max"
      :step="step"
      v-bind="$attrs"
      @input="onInput"
    />
    <div class="admin-num-spin">
      <button
        type="button"
        class="admin-num-btn admin-num-btn-up"
        aria-label="增加"
        tabindex="-1"
        @mousedown.prevent
        @click.prevent="step(1)"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="8" height="5" viewBox="0 0 10 6" fill="none" aria-hidden="true">
          <path d="M5 0L9.33 6H0.67L5 0Z" fill="currentColor" />
        </svg>
      </button>
      <button
        type="button"
        class="admin-num-btn admin-num-btn-down"
        aria-label="减少"
        tabindex="-1"
        @mousedown.prevent
        @click.prevent="step(-1)"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="8" height="5" viewBox="0 0 10 6" fill="none" aria-hidden="true">
          <path d="M5 6L0.67 0H9.33L5 6Z" fill="currentColor" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.admin-num-wrap {
  display: inline-flex;
  align-items: stretch;
  max-width: 100%;
  border-radius: var(--radius-sm, 12px);
  border: 1px solid var(--stroke-strong, rgba(148, 163, 184, 0.28));
  background: var(--bg-deep, #0f172a);
  overflow: hidden;
  box-sizing: border-box;
  vertical-align: middle;
}

.admin-num-wrap--center .admin-num-input {
  text-align: center;
}

.admin-num-input {
  flex: 0 0 auto;
  min-width: 2ch;
  margin: 0;
  /* 与 .admin-shell input 一致：0.4rem 0.6rem；右侧略收给箭头列 */
  padding: 0.4rem 0.25rem 0.4rem 0.6rem;
  border: none !important;
  border-radius: 0 !important;
  background: transparent !important;
  color: var(--text, #e2e8f0);
  font-size: 0.875rem;
  font-family: var(--font-body, system-ui, sans-serif);
  /* 不设 1.5：与原生单行 input 同高，避免整体高于相邻「备注」框 */
  line-height: normal;
  box-sizing: content-box;
  -moz-appearance: textfield;
  appearance: textfield;
}

.admin-num-input::placeholder {
  color: var(--text-muted, #94a3b8);
  opacity: 0.85;
}

.admin-num-input:focus {
  outline: none;
}

.admin-num-wrap:focus-within {
  border-color: var(--accent-from, #9f86d6);
  box-shadow: 0 0 0 1px rgba(159, 134, 214, 0.22);
}

.admin-num-input::-webkit-outer-spin-button,
.admin-num-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.admin-num-spin {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 1.5rem;
  border-left: 1px solid var(--stroke-strong, rgba(148, 163, 184, 0.22));
  background: rgba(15, 23, 42, 0.65);
}

.admin-num-btn {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  color: rgba(159, 134, 214, 0.88);
  cursor: pointer;
  line-height: 0;
  transition: background 0.12s, color 0.12s;
}

.admin-num-btn:hover {
  background: rgba(159, 134, 214, 0.12);
  color: var(--accent-mid, #bbb0ea);
}

.admin-num-btn:active {
  background: rgba(159, 134, 214, 0.18);
}

.admin-num-btn-up {
  border-bottom: 1px solid var(--stroke-strong, rgba(148, 163, 184, 0.18));
}

.admin-num-wrap--sm .admin-num-input {
  padding-left: 0.6rem;
  padding-right: 0.2rem;
  font-size: 0.875rem;
}

.admin-num-wrap--sm .admin-num-spin {
  width: 1.35rem;
}
</style>

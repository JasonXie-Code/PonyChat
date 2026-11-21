<script setup>
import { computed, ref, useAttrs } from 'vue'

defineOptions({ inheritAttrs: false })

const model = defineModel({ default: '' })
const attrs = useAttrs()
const showPassword = ref(false)

const hasValue = computed(() => String(model.value ?? '').length > 0)
const isDisabled = computed(() => attrs.disabled !== undefined && attrs.disabled !== false)
const inputAttrs = computed(() => {
  const { class: _class, style: _style, type: _type, ...rest } = attrs
  return rest
})

function onInput(e) {
  model.value = e.target.value
  if (!hasValue.value) showPassword.value = false
}
</script>

<template>
  <div
    class="admin-pwd-wrap"
    :class="[attrs.class, { 'admin-pwd-wrap--empty': !hasValue }]"
    :style="attrs.style"
  >
    <input
      v-bind="inputAttrs"
      class="admin-pwd-input"
      :type="showPassword ? 'text' : 'password'"
      :value="model ?? ''"
      @input="onInput"
    />
    <button
      v-if="hasValue"
      type="button"
      class="admin-pwd-toggle"
      :disabled="isDisabled"
      :aria-pressed="showPassword"
      :aria-label="showPassword ? '隐藏密码' : '显示密码'"
      @click="showPassword = !showPassword"
    >
      <svg
        v-if="!showPassword"
        class="admin-pwd-eye"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 0 1-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
      </svg>
      <svg
        v-else
        class="admin-pwd-eye"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
        <path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.admin-pwd-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 100%;
  min-width: 0;
  vertical-align: middle;
}

.admin-pwd-wrap.inp {
  width: auto;
  min-width: 160px;
}

.admin-pwd-input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding-right: 2.45rem !important;
}

.admin-pwd-wrap.inp .admin-pwd-input {
  min-width: 160px;
}

.admin-pwd-toggle {
  position: absolute;
  right: 0.18rem;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.92);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.admin-pwd-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.admin-pwd-toggle:focus-visible {
  outline: 2px solid rgba(255, 255, 255, 0.36);
  outline-offset: 1px;
}

.admin-pwd-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.admin-pwd-eye {
  display: block;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.admin-pwd-input::-ms-reveal,
.admin-pwd-input::-ms-clear {
  display: none;
  width: 0;
  height: 0;
}

.admin-pwd-input[type='password']::-webkit-credentials-auto-fill-button {
  visibility: hidden;
  display: none;
  pointer-events: none;
  height: 0;
  width: 0;
  margin: 0;
}

.admin-pwd-input[type='password']::-webkit-textfield-decoration-container {
  display: none !important;
}
</style>

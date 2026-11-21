<template>
  <label class="pony-checkbox" :class="{ 'pony-checkbox--disabled': disabled }">
    <input
      class="pony-checkbox-input"
      type="checkbox"
      :checked="isChecked"
      :disabled="disabled"
      @change="handleChange"
    >
    <span class="pony-checkbox-box" aria-hidden="true" />
    <span v-if="$slots.default || label" class="pony-checkbox-label">
      <slot>{{ label }}</slot>
    </span>
  </label>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: [Boolean, Array], default: undefined },
  checked: { type: Boolean, default: undefined },
  value: { type: [String, Number, Boolean], default: true },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const isChecked = computed(() => {
  if (Array.isArray(props.modelValue)) {
    return props.modelValue.includes(props.value)
  }
  if (typeof props.modelValue === 'boolean') {
    return props.modelValue
  }
  return Boolean(props.checked)
})

function handleChange(event) {
  const checked = event.target.checked
  if (Array.isArray(props.modelValue)) {
    const next = checked
      ? [...props.modelValue, props.value]
      : props.modelValue.filter((item) => item !== props.value)
    emit('update:modelValue', next)
  } else if (typeof props.modelValue === 'boolean') {
    emit('update:modelValue', checked)
  }
  emit('change', checked, event)
}
</script>

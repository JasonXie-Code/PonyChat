<template>
  <div ref="root" class="site-language" @keydown="onKeydown" @focusout="onFocusOut">
    <button
      :id="triggerId" ref="trigger" class="language-trigger" type="button"
      :aria-label="t('language') + ': ' + selectedLabel"
      aria-haspopup="menu" :aria-expanded="open" :aria-controls="menuId"
      @click="toggleMenu"
    >
      <span>{{ selectedLabel }}</span>
      <svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true" :class="{ 'is-open': open }"><path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg>
    </button>
    <div v-if="open" :id="menuId" class="language-menu" role="menu" :aria-labelledby="triggerId">
      <button
        v-for="(option, index) in options" :key="option.value"
        :ref="el => { optionElements[index] = el }"
        class="language-option" :class="{ 'is-selected': selection === option.value }"
        type="button" role="menuitemradio" :aria-checked="selection === option.value"
        :tabindex="activeIndex === index ? 0 : -1" @focus="activeIndex = index"
        @click="changeLanguage(option.value)"
      >
        <span>{{ option.label }}</span>
        <svg v-if="selection === option.value" viewBox="0 0 20 20" width="17" height="17" fill="none" aria-hidden="true"><path d="m4 10 4 4 8-8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </button>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, useId } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSiteI18n, selectLocale } from '../i18n/index.js'
const { t, selection, languageOptions } = useSiteI18n()
const route = useRoute()
const router = useRouter()
const root = ref(null)
const trigger = ref(null)
const open = ref(false)
const activeIndex = ref(0)
const optionElements = []
const id = useId()
const triggerId = `language-trigger-${id}`
const menuId = `language-menu-${id}`
const options = computed(() => [{ value: 'auto', label: t('auto') }, ...languageOptions])
const selectedLabel = computed(() => options.value.find(option => option.value === selection.value)?.label || t('auto'))

async function openMenu(index = options.value.findIndex(option => option.value === selection.value)) {
  activeIndex.value = Math.max(0, index)
  open.value = true
  await nextTick()
  optionElements[activeIndex.value]?.focus()
}
function toggleMenu() {
  if (open.value) open.value = false
  else openMenu()
}
function closeMenu(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
function onKeydown(event) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    closeMenu(true)
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  if (!open.value) {
    openMenu(event.key === 'End' ? options.value.length - 1 : event.key === 'Home' ? 0 : undefined)
    return
  }
  const count = options.value.length
  activeIndex.value = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (activeIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count
  optionElements[activeIndex.value]?.focus()
}
function onFocusOut(event) {
  if (!root.value?.contains(event.relatedTarget)) closeMenu()
}
function onOutsidePointer(event) {
  if (!root.value?.contains(event.target)) closeMenu()
}
onMounted(() => document.addEventListener('pointerdown', onOutsidePointer))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutsidePointer))
function changeLanguage(value) {
  selectLocale(value)
  closeMenu(true)
  const query = { ...route.query }
  if (value === 'auto') delete query.lang
  else query.lang = value
  router.replace({ path: route.path, hash: route.hash, query })
}
</script>

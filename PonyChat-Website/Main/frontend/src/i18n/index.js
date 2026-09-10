import { computed, ref } from 'vue'
import zhCN from './zh-CN.json'
import zhTW from './zh-TW.json'
import en from './en.json'
import ru from './ru.json'
import { languageOptions, resolveLocale, supportedLocales } from './locale.js'

export { languageOptions, supportedLocales }
export const messages = { 'zh-CN': zhCN, 'zh-TW': zhTW, en, ru }
const storageKey = 'ponychat.website.language'

function browserPreference() {
  let timeZone = ''
  let region = ''
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
    region = new Intl.Locale(navigator.language).region || ''
  } catch { /* A browser may omit locale or timezone information. */ }
  return { languages: navigator.languages?.length ? navigator.languages : [navigator.language], region, timeZone }
}

function readSaved() {
  try { return localStorage.getItem(storageKey) } catch { return null }
}

const initialQuery = new URLSearchParams(window.location.search).get('lang')
const saved = readSaved()
export const selection = ref(supportedLocales.includes(initialQuery) ? initialQuery : supportedLocales.includes(saved) ? saved : 'auto')
export const locale = ref(resolveLocale({ ...browserPreference(), explicit: initialQuery, saved }))

export function useSiteI18n() {
  const copy = computed(() => messages[locale.value])
  const t = (key) => copy.value[key] ?? en[key] ?? key
  return { locale, selection, t, copy, languageOptions }
}

export function selectLocale(value) {
  selection.value = supportedLocales.includes(value) ? value : 'auto'
  try {
    if (selection.value === 'auto') localStorage.removeItem(storageKey)
    else localStorage.setItem(storageKey, selection.value)
  } catch { /* Manual switching still works with storage disabled. */ }
  locale.value = resolveLocale({ ...browserPreference(), explicit: selection.value })
}

export function syncLocaleQuery(value) {
  if (supportedLocales.includes(value)) {
    selection.value = value
    locale.value = value
  } else {
    locale.value = resolveLocale({ ...browserPreference(), saved: selection.value })
  }
}

window.addEventListener('languagechange', () => {
  if (selection.value === 'auto') locale.value = resolveLocale(browserPreference())
})

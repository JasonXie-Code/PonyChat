import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/fonts/fonts.css'
import './styles/landing.css'
import './styles/showcase.css'
import './styles/checkbox.css'
import './styles/drive.css'
import './styles/international.css'
import { locale, messages, syncLocaleQuery } from './i18n/index.js'

const app = createApp(App)
app.use(createPinia())
app.use(router)
const localizedRoutes = {
  home: ['hero', 'intro'],
  detail: ['detailTitle', 'detailLead'],
  archive: ['updatesTitle', 'updatesLead'],
  'mbti-choice': ['mbtiTitle', 'mbtiLead'],
  'character-hall': ['hall', 'profilesDesc'],
  'data-export': ['export', 'export'],
  'chat-app': ['chat', 'intro2'],
}
function updateMetadata(to) {
  const isDrive = window.location.hostname === 'drive.ponychat.org'
  const keys = isDrive ? null : localizedRoutes[to.name]
  const copy = messages[locale.value]
  const title = keys ? 'PonyChat — ' + copy[keys[0]] : to.meta.title
  const desc = keys ? copy[keys[1]] : to.meta.description
  document.documentElement.lang = keys ? locale.value : 'zh-CN'
  if (title) document.title = title
  if (typeof desc === 'string') {
    let el = document.querySelector('meta[name="description"]')
    if (!el) {
      el = document.createElement('meta')
      el.setAttribute('name', 'description')
      document.head.appendChild(el)
    }
    el.setAttribute('content', desc)
  }
}
router.afterEach((to) => {
  syncLocaleQuery(to.query.lang)
  updateMetadata(to)
})
watch(locale, () => updateMetadata(router.currentRoute.value))
app.mount('#app')

// ionicons 在 mount 之后插入，避免先于 Vue 的 module 在内置浏览器里卡住导致整页空白（不用动态 import，以免 build 时 Rollup 解析失败）
if (typeof document !== 'undefined' && !document.querySelector('script[data-ionicons]')) {
  const s = document.createElement('script')
  s.type = 'module'
  s.src = '/js/ionicons/ionicons.esm.js'
  s.setAttribute('data-ionicons', '1')
  document.head.appendChild(s)
}

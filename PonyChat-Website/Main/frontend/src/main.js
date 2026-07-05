import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/fonts/fonts.css'
import './styles/landing.css'
import './styles/showcase.css'
import './styles/checkbox.css'
import './styles/drive.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
router.afterEach((to) => {
  const last = to.matched[to.matched.length - 1]
  const title = (last && last.meta && last.meta.title) || to.meta.title
  if (title) {
    document.title = title
  }
  const desc = (last && last.meta && last.meta.description) || to.meta.description
  if (typeof desc === 'string') {
    let el = document.querySelector('meta[name="description"]')
    if (!el) {
      el = document.createElement('meta')
      el.setAttribute('name', 'description')
      document.head.appendChild(el)
    }
    el.setAttribute('content', desc)
  }
})
app.mount('#app')

// ionicons 在 mount 之后插入，避免先于 Vue 的 module 在内置浏览器里卡住导致整页空白（不用动态 import，以免 build 时 Rollup 解析失败）
if (typeof document !== 'undefined' && !document.querySelector('script[data-ionicons]')) {
  const s = document.createElement('script')
  s.type = 'module'
  s.src = '/js/ionicons/ionicons.esm.js'
  s.setAttribute('data-ionicons', '1')
  document.head.appendChild(s)
}

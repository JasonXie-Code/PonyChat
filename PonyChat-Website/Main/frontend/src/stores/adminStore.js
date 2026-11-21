import { defineStore } from 'pinia'

function safeSessionGet(key) {
  try {
    return typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(key) : null
  } catch {
    return null
  }
}

function safeSessionSet(key, value) {
  try {
    if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, value)
  } catch {
    // Ignore storage failures in embedded browsers; in-memory Pinia state still works.
  }
}

function safeSessionRemove(key) {
  try {
    if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(key)
  } catch {
    // Ignore storage failures in embedded browsers.
  }
}

export const useAdminStore = defineStore('admin', {
  state: () => ({
    user: null,
    /** 与旧版一致：供邀请码等接口使用 */
    adminPassword: '',
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    username: (s) => s.user?.username || '',
    token: (s) => s.user?.token || 'admin_token_placeholder',
  },
  actions: {
    hydrate() {
      try {
        const raw = safeSessionGet('adminUser')
        this.user = raw ? JSON.parse(raw) : null
      } catch {
        this.user = null
      }
      this.adminPassword = safeSessionGet('admin_password') || ''
    },
    setSession(user, password) {
      this.user = user
      safeSessionSet('adminUser', JSON.stringify(user))
      if (password != null) {
        safeSessionSet('admin_password', password)
        this.adminPassword = password
      }
    },
    logout() {
      this.user = null
      this.adminPassword = ''
      safeSessionRemove('adminUser')
      safeSessionRemove('admin_password')
    },
  },
})

<template>
  <div class="login-page admin-shell">
    <!-- 背景装饰光球 -->
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>

    <div class="login-card">
      <!-- Logo + 标题 -->
      <div class="brand">
        <div class="logo-wrap">
          <img :src="logo" alt="PonyChat" class="logo" />
        </div>
        <h1 class="title">管理控制台</h1>
        <p class="subtitle">PonyChat · Admin Panel</p>
      </div>

      <div class="divider"></div>

      <!-- 表单 -->
      <form class="form" @submit.prevent="onSubmit">
        <div class="field">
          <span class="field-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
          </span>
          <input v-model="username" type="text" placeholder="管理员账号"
            autocomplete="username" required class="input" />
        </div>
        <div class="field field-password">
          <span class="field-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          </span>
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            placeholder="密码"
            autocomplete="current-password"
            required
            class="input"
            :class="{ 'input-with-toggle': password.length > 0 }"
          />
          <button
            v-if="password.length > 0"
            type="button"
            class="pwd-toggle"
            :aria-pressed="showPassword"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            tabindex="0"
            @click="showPassword = !showPassword"
          >
            <svg v-if="!showPassword" class="pwd-toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 0 1-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
            </svg>
            <svg v-else class="pwd-toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
              <path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z" />
            </svg>
          </button>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
        <button type="submit" class="btn-login" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" class="btn-icon"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
          {{ loading ? '登录中…' : '登录' }}
        </button>
      </form>

      <RouterLink to="/" class="back-link">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="back-icon"><polyline points="15 18 9 12 15 6"/></svg>
        返回 PonyChat 主页
      </RouterLink>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAdminStore } from '../../stores/adminStore'
import { adminLogin } from '../../api/admin'
import { usePublicUrl } from '../../composables/usePublicUrl'
import '../../styles/admin-shell.css'

const router = useRouter()
const route = useRoute()
const adminStore = useAdminStore()
const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

const username = ref('')
const password = ref('')
const showPassword = ref(false)
watch(password, (v) => {
  if (!v) showPassword.value = false
})
const error = ref('')
const loading = ref(false)

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    const res = await adminLogin(username.value.trim(), password.value)
    if (res.success) {
      adminStore.setSession(
        { username: username.value.trim(), role: 'administrator', token: res.token },
        password.value,
      )
      const redir = route.query.redirect || '/admin/overview'
      router.replace(typeof redir === 'string' ? redir : '/admin/overview')
    } else {
      error.value = res.message || '登录失败'
    }
  } catch (e) {
    error.value = e.message || '连接失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ── 全屏背景 ── */
.login-page {
  position: relative;
  min-width: 0 !important;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #0d0e1a;
  overflow: hidden;
  padding: 2rem;
}

/* 装饰光球 */
.orb {
  position: fixed;
  border-radius: 50%;
  filter: blur(70px);
  pointer-events: none;
  z-index: 0;
}
.orb-1 {
  width: 500px; height: 500px;
  top: -150px; left: -100px;
  background: radial-gradient(circle, rgba(117, 73, 212, 0.22) 0%, transparent 70%);
  animation: orbFloat 9s ease-in-out infinite alternate;
}
.orb-2 {
  width: 380px; height: 380px;
  bottom: -100px; right: -80px;
  background: radial-gradient(circle, rgba(78, 191, 207, 0.14) 0%, transparent 70%);
  animation: orbFloat 11s ease-in-out infinite alternate-reverse;
}
.orb-3 {
  width: 260px; height: 260px;
  top: 55%; left: 60%;
  background: radial-gradient(circle, rgba(159, 134, 214, 0.1) 0%, transparent 70%);
  animation: orbFloat 13s ease-in-out infinite alternate;
}
@keyframes orbFloat {
  from { transform: translate(0, 0) scale(1); }
  to   { transform: translate(28px, 18px) scale(1.1); }
}

/* ── 登录卡片 ── */
.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 390px;
  background: rgba(20, 22, 38, 0.78);
  backdrop-filter: blur(24px) saturate(150%);
  border: 1px solid rgba(159, 134, 214, 0.18);
  border-radius: 1.75rem;
  padding: 2.5rem 2.5rem 2rem;
  box-shadow:
    0 32px 64px rgba(0,0,0,0.55),
    inset 0 1px 0 rgba(255,255,255,0.06);
  animation: cardIn 0.55s cubic-bezier(0.34,1.56,0.64,1) both;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(24px) scale(0.97); }
  to   { opacity: 1; transform: none; }
}

/* ── 品牌区 ── */
.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 1.75rem;
}
.logo-wrap {
  position: relative;
  width: 76px; height: 76px;
  margin-bottom: 1rem;
}
.logo-wrap::before {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 22px;
  background: var(--cta-gradient, linear-gradient(135deg, #7549d4, #4ebfcf));
  z-index: 0;
  opacity: 0.65;
  filter: blur(2px);
}
.logo {
  position: relative;
  z-index: 1;
  width: 76px; height: 76px;
  border-radius: 18px;
  display: block;
}
.title {
  font-size: 1.45rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 0.3rem;
  letter-spacing: 0.01em;
}
.subtitle {
  font-size: 0.78rem;
  color: rgba(148,163,184,0.6);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 0;
}

/* 分隔线 */
.divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(159, 134, 214, 0.2), transparent);
  margin-bottom: 1.75rem;
}

/* ── 输入框 ── */
.form {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.field {
  position: relative;
  display: flex;
  align-items: center;
}
.field-icon {
  position: absolute;
  left: 13px;
  display: flex;
  align-items: center;
  color: rgba(148,163,184,0.45);
  pointer-events: none;
  transition: color 0.2s;
}
.field-icon svg {
  width: 17px; height: 17px;
}
.field:focus-within .field-icon {
  color: var(--accent-from, #9f86d6);
}

/* 浅色眼睛；显隐两种图标共用同一套颜色，不因状态/焦点改变样式 */
.pwd-toggle {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: rgba(226, 232, 240, 0.9);
  cursor: pointer;
  overflow: visible;
}
.pwd-toggle:hover {
  color: rgba(226, 232, 240, 0.9);
  background: transparent;
}
.pwd-toggle:focus-visible {
  outline: 2px solid rgba(226, 232, 240, 0.35);
  outline-offset: 2px;
}
.pwd-toggle-icon {
  width: 19px;
  height: 19px;
  flex-shrink: 0;
  display: block;
  overflow: visible;
}

.input {
  width: 100%;
  padding: 0.78rem 1rem 0.78rem 2.6rem !important;
  background: rgba(12, 14, 26, 0.7);
  border: 1px solid rgba(148,163,184,0.1);
  border-radius: 0.75rem;
  color: #f1f5f9;
  font-size: 0.92rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-sizing: border-box;
  font-family: inherit;
}
.input::placeholder { color: rgba(148,163,184,0.38); }
.input:focus {
  border-color: rgba(159, 134, 214, 0.45);
  box-shadow: 0 0 0 3px rgba(117, 73, 212, 0.14);
}
.input.input-with-toggle {
  padding-right: 2.85rem !important;
}

/* 隐藏浏览器自带「显示密码」，避免与自定义眼睛重复（Edge / Chromium / WebKit） */
.input.input-with-toggle::-ms-reveal,
.input.input-with-toggle::-ms-clear {
  display: none;
  width: 0;
  height: 0;
}
.input.input-with-toggle[type="password"]::-webkit-credentials-auto-fill-button {
  visibility: hidden;
  display: none;
  pointer-events: none;
  height: 0;
  width: 0;
  margin: 0;
}
.input.input-with-toggle[type="password"]::-webkit-textfield-decoration-container {
  display: none !important;
}

/* 错误 */
.err {
  color: #d88080;
  font-size: 0.82rem;
  margin: 0;
  padding-left: 2px;
}

/* ── 登录按钮 ── */
.btn-login {
  margin-top: 0.2rem;
  width: 100%;
  padding: 0.82rem 1rem;
  background: var(--btn-primary, #7549d4);
  border: none;
  border-radius: 0.875rem;
  color: #fff;
  font-size: 0.97rem;
  font-weight: 700;
  letter-spacing: 0.035em;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  box-shadow: 0 4px 20px var(--btn-primary-shadow, rgba(117, 73, 212, 0.35));
  transition: background 0.2s, transform 0.2s, box-shadow 0.2s;
  font-family: inherit;
}
.btn-login:hover:not(:disabled) {
  background: var(--btn-primary-hover, #663cc4);
  transform: translateY(-1px);
  box-shadow: 0 8px 28px rgba(117, 73, 212, 0.42);
}
.btn-login:active:not(:disabled) { transform: none; opacity: 1; }
.btn-login:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-icon { width: 17px; height: 17px; }

/* 加载转圈 */
.spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 返回链接 ── */
.back-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  margin-top: 1.5rem;
  color: rgba(148,163,184,0.5);
  font-size: 0.8rem;
  text-decoration: none;
  transition: color 0.2s;
  letter-spacing: 0.02em;
}
.back-link:hover { color: var(--accent-from, #9f86d6); }
.back-icon { width: 15px; height: 15px; }
</style>

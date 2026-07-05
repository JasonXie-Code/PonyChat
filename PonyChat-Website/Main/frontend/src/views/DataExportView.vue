<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-data-export">
    <header class="site-header">
      <RouterLink class="brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat</span>
      </RouterLink>
      <nav class="header-nav" aria-label="页面导航">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/detail">了解产品</RouterLink>
        <RouterLink to="/archive">项目近况</RouterLink>
      </nav>
    </header>

    <main class="data-export-main" :class="{ 'data-export-main--login': !token }">
      <section class="data-export-panel" aria-labelledby="export-title">
        <div class="data-export-head">
          <p class="hero-eyebrow">个人数据导出</p>
          <h1 id="export-title">导出聊天记录</h1>
          <p>登录后选择角色和模式，导出为 TXT 文本文件。</p>
        </div>

        <form v-if="!token" class="export-login-form" @submit.prevent="handleLogin">
          <label>
            <span>账号</span>
            <input v-model.trim="loginForm.username" autocomplete="username" type="text" required>
          </label>
          <label>
            <span>密码</span>
            <input v-model="loginForm.password" autocomplete="current-password" type="password" required>
          </label>
          <button class="export-primary-btn" type="submit" :disabled="loading">
            {{ loading ? '登录中...' : '登录并查看可导出数据' }}
          </button>
        </form>

        <div v-else class="export-workspace">
          <div class="export-account-row">
            <div>
              <span class="export-label">当前账号</span>
              <strong>{{ username }}</strong>
            </div>
            <button class="export-ghost-btn" type="button" @click="resetSession">退出</button>
          </div>

          <section class="export-section" aria-labelledby="mode-title">
            <div class="export-section-title">
              <h2 id="mode-title">选择模式</h2>
              <button class="export-text-btn" type="button" @click="toggleAllModes">
                {{ allModesSelected ? '取消全选' : '全选模式' }}
              </button>
            </div>
            <div class="export-mode-grid">
              <div v-for="mode in modes" :key="mode.id" class="export-check-option">
                <PonyCheckbox v-model="selectedModes" :value="mode.id">
                  {{ mode.label }}
                </PonyCheckbox>
              </div>
            </div>
          </section>

          <section class="export-section" aria-labelledby="character-title">
            <div class="export-section-title">
              <h2 id="character-title">选择角色</h2>
              <button class="export-text-btn" type="button" @click="toggleAllCharacters">
                {{ allCharactersSelected ? '取消全选' : '全选角色' }}
              </button>
            </div>

            <div v-if="characters.length" class="export-character-list">
              <div v-for="character in characters" :key="character.id" class="export-character-row">
                <PonyCheckbox v-model="selectedCharacterIds" :value="character.id" class="export-character-name">
                  {{ character.name }}
                </PonyCheckbox>
                <span class="export-character-count">{{ countForSelectedModes(character) }} 条</span>
              </div>
            </div>
            <p v-else class="export-empty">这个账号下暂时没有可导出的角色。</p>
          </section>

          <div class="export-actions">
            <button class="export-primary-btn" type="button" :disabled="!canDownload || loading" @click="handleDownload">
              {{ loading ? '正在生成...' : '导出 TXT' }}
            </button>
            <button class="export-ghost-btn" type="button" :disabled="loading" @click="loadOptions">刷新数据</button>
          </div>
        </div>

        <p v-if="statusMessage" class="export-status" role="status">{{ statusMessage }}</p>
        <p v-if="errorMessage" class="export-error" role="alert">{{ errorMessage }}</p>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-links">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/app">网页版聊天</RouterLink>
        <RouterLink to="/detail">了解产品</RouterLink>
        <RouterLink to="/archive">项目近况</RouterLink>
        <RouterLink to="/data-export">个人数据导出</RouterLink>
      </div>
      <p>PonyChat · 与小马角色的 AI 陪伴</p>
    </footer>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import PonyCheckbox from '../components/PonyCheckbox.vue'
import { downloadExportText, exportLogin, fetchExportOptions } from '../api/web'
import { usePublicUrl } from '../composables/usePublicUrl.js'

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

const loginForm = reactive({ username: '', password: '' })
const token = ref('')
const username = ref('')
const modes = ref([])
const characters = ref([])
const selectedModes = ref([])
const selectedCharacterIds = ref([])
const loading = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')

const allModesSelected = computed(() => modes.value.length > 0 && selectedModes.value.length === modes.value.length)
const allCharactersSelected = computed(
  () => characters.value.length > 0 && selectedCharacterIds.value.length === characters.value.length,
)
const canDownload = computed(() => selectedModes.value.length > 0 && selectedCharacterIds.value.length > 0)

function setError(error) {
  errorMessage.value = error instanceof Error ? error.message : String(error || '操作失败')
}

async function handleLogin() {
  errorMessage.value = ''
  statusMessage.value = ''
  loading.value = true
  try {
    const data = await exportLogin(loginForm.username, loginForm.password)
    token.value = data.token
    username.value = data.username
    loginForm.password = ''
    await loadOptions()
  } catch (error) {
    setError(error)
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  if (!token.value) return
  errorMessage.value = ''
  statusMessage.value = ''
  loading.value = true
  try {
    const data = await fetchExportOptions(token.value)
    modes.value = data.modes || []
    characters.value = data.characters || []
    selectedModes.value = modes.value.map((mode) => mode.id)
    selectedCharacterIds.value = characters.value
      .filter((character) => Number(character.total || 0) > 0)
      .map((character) => character.id)
    if (!selectedCharacterIds.value.length) {
      selectedCharacterIds.value = characters.value.map((character) => character.id)
    }
    statusMessage.value = `已加载 ${characters.value.length} 个角色。`
  } catch (error) {
    setError(error)
    if (/过期|登录|401/.test(error?.message || '')) resetSession(false)
  } finally {
    loading.value = false
  }
}

function resetSession(clearMessage = true) {
  token.value = ''
  username.value = ''
  modes.value = []
  characters.value = []
  selectedModes.value = []
  selectedCharacterIds.value = []
  if (clearMessage) {
    statusMessage.value = ''
    errorMessage.value = ''
  }
}

function toggleAllModes() {
  selectedModes.value = allModesSelected.value ? [] : modes.value.map((mode) => mode.id)
}

function toggleAllCharacters() {
  selectedCharacterIds.value = allCharactersSelected.value ? [] : characters.value.map((character) => character.id)
}

function countForSelectedModes(character) {
  const counts = character.counts || {}
  return selectedModes.value.reduce((sum, mode) => sum + Number(counts[mode] || 0), 0)
}

async function handleDownload() {
  if (!canDownload.value) return
  errorMessage.value = ''
  statusMessage.value = ''
  loading.value = true
  try {
    const { blob, filename } = await downloadExportText(token.value, {
      characterIds: selectedCharacterIds.value,
      modes: selectedModes.value,
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    statusMessage.value = '导出文件已生成。'
  } catch (error) {
    setError(error)
  } finally {
    loading.value = false
  }
}
</script>

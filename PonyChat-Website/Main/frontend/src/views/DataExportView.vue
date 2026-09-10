<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-data-export">
    <SiteHeader />

    <main class="data-export-main" :class="{ 'data-export-main--login': !token }">
      <section class="data-export-panel" aria-labelledby="export-title">
        <div class="data-export-head">
          <p class="hero-eyebrow">{{ t('export') }}</p>
          <h1 id="export-title">{{ t('exportTitle') }}</h1>
          <p>{{ t('exportLead') }}</p>
        </div>

        <form v-if="!token" class="export-login-form" @submit.prevent="handleLogin">
          <label>
            <span>{{ t('account') }}</span>
            <input v-model.trim="loginForm.username" autocomplete="username" type="text" required>
          </label>
          <label>
            <span>{{ t('password') }}</span>
            <input v-model="loginForm.password" autocomplete="current-password" type="password" required>
          </label>
          <button class="export-primary-btn" type="submit" :disabled="loading">
            {{ loading ? t('signingIn') : t('exportLogin') }}
          </button>
        </form>

        <div v-else class="export-workspace">
          <div class="export-account-row">
            <div>
              <span class="export-label">{{ t('currentAccount') }}</span>
              <strong>{{ username }}</strong>
            </div>
            <button class="export-ghost-btn" type="button" @click="resetSession">{{ t('logout') }}</button>
          </div>

          <section class="export-section" aria-labelledby="mode-title">
            <div class="export-section-title">
              <h2 id="mode-title">{{ t('selectModes') }}</h2>
              <button class="export-text-btn" type="button" @click="toggleAllModes">
                {{ allModesSelected ? t('deselectAll') : t('allModes') }}
              </button>
            </div>
            <div class="export-mode-grid">
              <div v-for="mode in modes" :key="mode.id" class="export-check-option">
                <PonyCheckbox v-model="selectedModes" :value="mode.id">
                  {{ mode.id === 'normal' ? t('normalMode') : mode.id === 'galgame_lock' ? t('lockMode') : t('gameMode') }}
                </PonyCheckbox>
              </div>
            </div>
          </section>

          <section class="export-section" aria-labelledby="character-title">
            <div class="export-section-title">
              <h2 id="character-title">{{ t('selectCharacters') }}</h2>
              <button class="export-text-btn" type="button" @click="toggleAllCharacters">
                {{ allCharactersSelected ? t('deselectAll') : t('allCharacters') }}
              </button>
            </div>

            <div v-if="characters.length" class="export-character-list">
              <div v-for="character in characters" :key="character.id" class="export-character-row">
                <PonyCheckbox v-model="selectedCharacterIds" :value="character.id" class="export-character-name">
                  {{ character.name }}
                </PonyCheckbox>
                <span class="export-character-count">{{ countForSelectedModes(character) }} {{ t('messagesCount') }}</span>
              </div>
            </div>
            <p v-else class="export-empty">{{ t('exportEmpty') }}</p>
          </section>

          <div class="export-actions">
            <button class="export-primary-btn" type="button" :disabled="!canDownload || loading" @click="handleDownload">
              {{ loading ? t('generating') : t('exportTxt') }}
            </button>
            <button class="export-ghost-btn" type="button" :disabled="loading" @click="loadOptions">{{ t('refresh') }}</button>
          </div>
        </div>

        <p v-if="statusMessage" class="export-status" role="status">{{ statusMessage }}</p>
        <p v-if="errorMessage" class="export-error" role="alert">{{ errorMessage }}</p>
      </section>
    </main>

    <SiteFooter />
  </div>
</template>

<script setup>
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
const { t } = useSiteI18n()
import { computed, reactive, ref } from 'vue'
import PonyCheckbox from '../components/PonyCheckbox.vue'
import { downloadExportText, exportLogin, fetchExportOptions } from '../api/web'




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
  errorMessage.value = error instanceof Error ? error.message : String(error || t('operationFailed'))
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
    statusMessage.value = `${t('charactersLoaded')} ${characters.value.length}`
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
    statusMessage.value = t('exportReady')
  } catch (error) {
    setError(error)
  } finally {
    loading.value = false
  }
}
</script>

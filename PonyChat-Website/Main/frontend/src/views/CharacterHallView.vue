<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-character-hall">
    <SiteHeader />

    <main class="character-hall-main">
      <section class="character-hall-head" aria-labelledby="character-hall-title">
        <p class="hero-eyebrow">PonyChat · {{ t('hall') }}</p>
        <h1 id="character-hall-title" class="character-hall-title">{{ t('hallTitle') }}</h1>
        <p class="character-hall-lead">
          {{ t('hallLead') }}
        </p>
      <p class="international-note">{{ t('originalProfiles') }}</p></section>

      <div v-if="loading" class="character-hall-state">{{ t('loading') }}</div>
      <div v-else-if="error" class="character-hall-state character-hall-state-error">{{ t('hallError') }}</div>
      <div v-else-if="certifiedCharacters.length === 0" class="character-hall-state">{{ t('hallEmpty') }}</div>

      <section v-else class="character-grid" :aria-label="t('hall')">
        <article
          v-for="character in certifiedCharacters"
          :key="character.id"
          class="character-card"
        >
          <div
            v-if="coverUrl(character) && !coverFailed[character.id]"
            class="character-cover"
          >
            <img
              :src="coverUrl(character)"
              :alt="displayName(character)"
              loading="lazy"
              decoding="async"
              @error="coverFailed[character.id] = true"
            >
          </div>
          <div class="character-card-top">
            <div class="character-avatar-wrap">
              <img
                v-if="avatarUrl(character.avatar) && !avatarFailed[character.id]"
                :src="avatarUrl(character.avatar)"
                :alt="displayName(character)"
                class="character-avatar"
                loading="lazy"
                decoding="async"
                @error="avatarFailed[character.id] = true"
              >
              <span v-else class="character-avatar-fallback">{{ displayName(character).slice(0, 1) || '?' }}</span>
            </div>
            <div class="character-title-block">
              <div class="character-name-row">
                <h2>{{ displayName(character) }}</h2>
                <span class="certified-badge">{{ t('certified') }}</span>
              </div>
              <p class="character-signature">{{ signature(character) }}</p>
            </div>
          </div>

          <dl class="character-metrics" :aria-label="t('profile')">
            <div>
              <dt>MBTI</dt>
              <dd>
                <span class="mbti-code">{{ field(character, 'profileMbti') || t('notFilled') }}</span>
                <span v-if="mbtiMeaning(character)" class="mbti-meaning">{{ mbtiMeaning(character) }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('likes') }}</dt>
              <dd>{{ compactNumber(character.likeCount) }}</dd>
            </div>
            <div>
              <dt>{{ t('added') }}</dt>
              <dd>{{ compactNumber(character.timesAdded) }}</dd>
            </div>
            <div>
              <dt>{{ t('updated') }}</dt>
              <dd>{{ formatDate(character.updatedAt || character.publishedAt) }}</dd>
            </div>
          </dl>

          <div class="character-profile">
            <h3>{{ t('profile') }}</h3>
            <p>{{ profileIntro(character) }}</p>
            <ul class="profile-facts" :aria-label="t('profile')">
              <li v-if="field(character, 'profileSpecies')"><span>{{ t('species') }}</span>{{ field(character, 'profileSpecies') }}</li>
              <li v-if="field(character, 'profileAge')"><span>{{ t('age') }}</span>{{ field(character, 'profileAge') }}</li>
              <li v-if="field(character, 'profilePersonality')"><span>{{ t('personality') }}</span>{{ field(character, 'profilePersonality') }}</li>
              <li v-if="field(character, 'profileInterests')"><span>{{ t('interests') }}</span>{{ field(character, 'profileInterests') }}</li>
            </ul>
          </div>
        </article>
      </section>
    </main>

    <SiteFooter />
  </div>
</template>

<script setup>
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
const { t, locale } = useSiteI18n()
import { computed, onMounted, reactive, ref } from 'vue'




const loading = ref(true)
const error = ref('')
const characters = ref([])
const avatarFailed = reactive({})
const coverFailed = reactive({})

const certifiedCharacters = computed(() =>
  characters.value
    .filter((c) => c?.isCertified || isSystemPublished(c))
    .sort((a, b) => dateValue(b.updatedAt || b.publishedAt) - dateValue(a.updatedAt || a.publishedAt)),
)

onMounted(async () => {
  try {
    const res = await fetch('/api/character-hall')
    if (!res.ok) throw new Error(`角色大厅暂时不可用 (${res.status})`)
    const data = await res.json()
    characters.value = Array.isArray(data) ? data : []
  } catch (err) {
    error.value = err?.message || '角色大厅暂时不可用'
  } finally {
    loading.value = false
  }
})

function isSystemPublished(character) {
  return [character.owner, character.owner_raw, character.publicOwner, character.addedFrom]
    .some((value) => String(value || '').trim().toLowerCase() === 'system')
}

function displayName(character) {
  return field(character, 'name') || t('unnamed')
}

function field(character, key) {
  const value = character?.[key]
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  return String(value || '').trim()
}

function signature(character) {
  return field(character, 'profileIntro') || field(character, 'bio') || field(character, 'description') || t('noSignature')
}

function profileIntro(character) {
  return field(character, 'description') || field(character, 'bio') || field(character, 'profileIntro') || t('noProfile')
}

function avatarUrl(avatar) {
  if (!avatar || typeof avatar !== 'string') return ''
  const a = avatar.trim()
  if (a.startsWith('http') || a.startsWith('data:')) return a
  if (a.startsWith('/')) return a
  return `/${a.replace(/^\/+/, '')}`
}

function coverUrl(character) {
  const cover = field(character, 'profileCover')
  return avatarUrl(cover)
}

const mbtiCodes = new Set(["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP", "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"])

function mbtiMeaning(character) {
  const code = field(character, 'profileMbti').toUpperCase()
  return mbtiCodes.has(code) ? t('mbti' + code) : ''
}

function compactNumber(value) {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '0'
  return new Intl.NumberFormat(locale.value, { notation: 'compact' }).format(Math.max(0, Math.trunc(n)))
}

function dateValue(value) {
  const t = Date.parse(value || '')
  return Number.isFinite(t) ? t : 0
}

function formatDate(value) {
  const timestamp = dateValue(value)
  if (!timestamp) return t('notFilled')
  return new Intl.DateTimeFormat(locale.value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(timestamp))
}
</script>

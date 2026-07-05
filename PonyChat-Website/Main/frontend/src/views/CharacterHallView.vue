<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-character-hall">
    <header class="site-header">
      <RouterLink class="brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat</span>
      </RouterLink>
      <nav class="header-nav" aria-label="页面导航">
        <RouterLink to="/app">网页版聊天</RouterLink>
        <RouterLink to="/character-hall">角色大厅</RouterLink>
        <RouterLink to="/mbti">MBTI测试</RouterLink>
        <a href="https://music.ponychat.org/" target="_blank" rel="noopener noreferrer">MLP音乐</a>
        <RouterLink to="/detail">了解产品</RouterLink>
      </nav>
    </header>

    <main class="character-hall-main">
      <section class="character-hall-head" aria-labelledby="character-hall-title">
        <p class="hero-eyebrow">PonyChat · 认证角色大厅</p>
        <h1 id="character-hall-title" class="character-hall-title">已经发布的认证角色</h1>
        <p class="character-hall-lead">
          这里展示 PonyChat 大厅中由官方认证发布的角色。你可以先看看头像、签名、MBTI、人气和角色档案，再到 Android 客户端里添加她们开始聊天。
        </p>
      </section>

      <div v-if="loading" class="character-hall-state">正在加载角色大厅...</div>
      <div v-else-if="error" class="character-hall-state character-hall-state-error">{{ error }}</div>
      <div v-else-if="certifiedCharacters.length === 0" class="character-hall-state">暂时没有已发布的认证角色。</div>

      <section v-else class="character-grid" aria-label="认证角色列表">
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
              :alt="`${displayName(character)} 的主页封面`"
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
                :alt="`${displayName(character)} 的头像`"
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
                <span class="certified-badge">认证角色</span>
              </div>
              <p class="character-signature">{{ signature(character) }}</p>
            </div>
          </div>

          <dl class="character-metrics" aria-label="角色数据">
            <div>
              <dt>MBTI</dt>
              <dd>
                <span class="mbti-code">{{ field(character, 'profileMbti') || '未填写' }}</span>
                <span v-if="mbtiMeaning(character)" class="mbti-meaning">{{ mbtiMeaning(character) }}</span>
              </dd>
            </div>
            <div>
              <dt>喜欢</dt>
              <dd>{{ compactNumber(character.likeCount) }}</dd>
            </div>
            <div>
              <dt>添加</dt>
              <dd>{{ compactNumber(character.timesAdded) }}</dd>
            </div>
            <div>
              <dt>更新</dt>
              <dd>{{ formatDate(character.updatedAt || character.publishedAt) }}</dd>
            </div>
          </dl>

          <div class="character-profile">
            <h3>角色档案</h3>
            <p>{{ profileIntro(character) }}</p>
            <ul class="profile-facts" aria-label="档案字段">
              <li v-if="field(character, 'profileSpecies')"><span>种族</span>{{ field(character, 'profileSpecies') }}</li>
              <li v-if="field(character, 'profileAge')"><span>年龄</span>{{ field(character, 'profileAge') }}</li>
              <li v-if="field(character, 'profilePersonality')"><span>性格</span>{{ field(character, 'profilePersonality') }}</li>
              <li v-if="field(character, 'profileInterests')"><span>兴趣</span>{{ field(character, 'profileInterests') }}</li>
            </ul>
          </div>
        </article>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-links">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/app">网页版聊天</RouterLink>
        <RouterLink to="/character-hall">角色大厅</RouterLink>
        <RouterLink to="/detail">了解产品</RouterLink>
        <a href="/download/apk" download>下载 APK</a>
      </div>
      <p>PonyChat · 与小马角色的 AI 陪伴</p>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { usePublicUrl } from '../composables/usePublicUrl.js'

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

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
  return field(character, 'name') || '未命名角色'
}

function field(character, key) {
  const value = character?.[key]
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  return String(value || '').trim()
}

function signature(character) {
  return field(character, 'profileIntro') || field(character, 'bio') || field(character, 'description') || '还没有留下签名。'
}

function profileIntro(character) {
  return field(character, 'description') || field(character, 'bio') || field(character, 'profileIntro') || '这个角色还没有补充公开档案。'
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

const mbtiMeanings = {
  INTJ: '战略型，重规划与长期目标',
  INTP: '分析型，重逻辑与好奇心',
  ENTJ: '指挥型，果断且目标感强',
  ENTP: '辩论型，灵活、有点子',
  INFJ: '提倡型，敏锐、理想主义',
  INFP: '调停型，温柔且重内心价值',
  ENFJ: '主人公型，善共情与带动他人',
  ENFP: '竞选者型，热情、想象力强',
  ISTJ: '物流师型，可靠、守秩序',
  ISFJ: '守护者型，体贴、愿意照顾他人',
  ESTJ: '总经理型，务实、重执行',
  ESFJ: '执政官型，亲和、重关系',
  ISTP: '鉴赏家型，冷静、擅长动手',
  ISFP: '探险家型，温和、感受细腻',
  ESTP: '企业家型，行动快、爱挑战',
  ESFP: '表演者型，活泼、享受当下',
}

function mbtiMeaning(character) {
  const code = field(character, 'profileMbti').toUpperCase()
  return mbtiMeanings[code] || ''
}

function compactNumber(value) {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '0'
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}万`
  return String(Math.max(0, Math.trunc(n)))
}

function dateValue(value) {
  const t = Date.parse(value || '')
  return Number.isFinite(t) ? t : 0
}

function formatDate(value) {
  const t = dateValue(value)
  if (!t) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(t))
}
</script>

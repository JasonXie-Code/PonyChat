<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="shell shell-home">
    <SiteHeader />
    <main class="home-main">
      <div class="home-hero">
        <p class="hero-eyebrow">{{ t('tagline') }}</p>
        <h1 class="home-title">{{ t('hero') }}</h1>
        <p class="home-intro home-intro-lead-first">{{ t('intro') }}</p>
        <p class="home-intro">{{ t('intro2') }}</p>
        <div id="download" class="hero-cta">
          <p v-if="appVersion" class="hero-version-tag">{{ t('android') }} · v{{ appVersion }}</p>
          <a class="hero-download-btn" href="/download/apk" download>
            <span class="hero-apk-badge" aria-hidden="true">APK</span>
            <span>{{ t('download') }}</span>
            <svg class="hero-download-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </a>
          <div class="hero-action-grid" :aria-label="t('nav')">
            <RouterLink v-for="item in actions" :key="item[0]" class="hero-action-link" :to="item[0]">{{ t(item[1]) }}</RouterLink>
          </div>
          <p class="international-note">{{ t('international') }}</p>
        </div>
      </div>
      <section class="home-showcase" aria-labelledby="showcase-heading">
        <div class="home-showcase-head"><h2 id="showcase-heading" class="home-showcase-title">{{ t('showcase') }}</h2></div>
        <ul class="home-showcase-grid">
          <li v-for="(file, index) in photos" :key="file" class="home-showcase-card">
            <figure class="home-showcase-figure">
              <div class="home-showcase-frame"><img :src="pub('Photos/' + file)" :alt="t('shot' + (index + 1))" class="home-showcase-img" loading="lazy" decoding="async"></div>
              <figcaption class="home-showcase-caption">
                <span class="home-showcase-badge" aria-hidden="true">{{ index + 1 }}</span>
                <h3 class="home-showcase-card-title">{{ t('shot' + (index + 1)) }}</h3>
                <p class="home-showcase-card-desc">{{ t('shot' + (index + 1) + 'desc') }}</p>
              </figcaption>
            </figure>
          </li>
        </ul>
        <p class="international-note">{{ t('screenshotNote') }}</p>
      </section>
      <section class="home-differentiator" aria-labelledby="differentiator-heading">
        <div class="home-differentiator-head">
          <p class="home-differentiator-kicker">{{ t('international') }}</p>
          <h2 id="differentiator-heading" class="home-differentiator-title">{{ t('unique') }}</h2>
          <p class="home-differentiator-lead">{{ t('uniqueLead') }}</p>
        </div>
        <div class="investor-metrics">
          <div v-for="(symbol, index) in ['IM', '∞', '3']" :key="symbol" class="investor-metric">
            <span class="investor-metric-value">{{ symbol }}</span>
            <span class="investor-metric-label">{{ t('metric' + (index + 1)) }}</span>
            <p>{{ t('metric' + (index + 1) + 'desc') }}</p>
          </div>
        </div>
        <div class="comparison-wrap" :aria-label="t('compare')" tabindex="0">
          <table class="comparison-table">
            <thead><tr><th v-for="key in ['compareHead', 'compareLLM', 'compareRP']" :key="key" scope="col">{{ t(key) }}</th><th scope="col">PonyChat</th></tr></thead>
            <tbody><tr v-for="n in 4" :key="n"><th scope="row">{{ t('row' + n) }}</th><td v-for="suffix in ['a', 'b', 'c']" :key="suffix" :data-label="suffix === 'a' ? t('compareLLM') : suffix === 'b' ? t('compareRP') : 'PonyChat'">{{ t('row' + n + suffix) }}</td></tr></tbody>
          </table>
        </div>
        <p class="international-note">{{ t('compareNote') }}</p>
        <div class="play-tier-grid">
          <article v-for="n in 3" :key="n" class="play-tier-card" :class="{ 'play-tier-card-primary': n === 3 }">
            <div class="play-tier-top"><span class="play-tier-index">0{{ n }}</span><span class="play-tier-status">{{ t('tier' + n + 'status') }}</span></div>
            <h3>{{ t('tier' + n) }}</h3><p>{{ t('tier' + n + 'desc') }}</p>
          </article>
        </div>
      </section>
    </main>
    <SiteFooter />
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
import { usePublicUrl } from '../composables/usePublicUrl.js'
const { t } = useSiteI18n()
const pub = usePublicUrl()
const actions = [['/character-hall', 'hall'], ['/app', 'chat'], ['/detail', 'detail'], ['/archive', 'archive']]
const photos = ['236b8c5f657546eb74ff634b8e962ad9.jpg', 'b2853e1bce4c23f0b7ab84c4ac7297b9.jpg', '0c258ba573e4fe20a95324f534ec97a4.jpg']
const appVersion = ref('')
onMounted(async () => {
  try {
    const response = await fetch('/api/app/version', { signal: AbortSignal.timeout(8000) })
    if (response.ok) {
      const data = await response.json()
      if (typeof data.version_name === 'string') appVersion.value = data.version_name
    }
  } catch { /* The direct download stays available if the version lookup fails. */ }
})
</script>

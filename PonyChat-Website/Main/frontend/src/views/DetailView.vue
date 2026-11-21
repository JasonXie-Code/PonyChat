<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="shell">
    <SiteHeader />
    <main>
      <div class="detail-page-head"><h1 class="detail-page-title">{{ t('detailTitle') }}</h1><p class="detail-page-lead">{{ t('detailLead') }}</p></div>
      <section id="positioning" class="section-block">
        <div class="section-head"><h2>{{ t('position') }}</h2></div><div class="cap-md"><p>{{ t('positionText') }}</p></div>
      </section>
      <section id="capabilities" class="section-block">
        <div class="section-head"><h2>{{ t('capabilities') }}</h2></div>
        <div class="international-card-grid"><article v-for="key in capabilities" :key="key" class="international-card"><h3>{{ t(key) }}</h3><p>{{ t(key + 'Desc') }}</p></article></div>
      </section>
      <section id="play" class="section-block">
        <div class="section-head"><h2>{{ t('play') }}</h2></div>
        <div class="play-grid"><article v-for="n in 3" :key="n" class="play-item"><span class="play-index">0{{ n }}</span><h3>{{ t('play' + n) }}</h3><p>{{ t('play' + n + 'desc') }}</p></article></div>
      </section>
      <section id="roadmap" class="section-block">
        <div class="section-head"><h2>{{ t('roadmap') }}</h2><p class="section-lead">{{ t('roadmapText') }}</p></div>
        <div class="play-tier-grid"><article v-for="n in 3" :key="n" class="play-tier-card"><div class="play-tier-top"><span class="play-tier-index">0{{ n }}</span><span class="play-tier-status">{{ t('tier' + n + 'status') }}</span></div><h3>{{ t('tier' + n) }}</h3><p>{{ t('tier' + n + 'desc') }}</p></article></div>
      </section>
      <section id="web-scope" class="section-block"><div class="section-head"><h2>{{ t('webScope') }}</h2><p class="section-lead">{{ t('webScopeText') }}</p></div><a class="hero-download-btn" href="/download/apk" download>{{ t('download') }}</a></section>
    </main>
    <SiteFooter />
  </div>
</template>
<script setup>
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
const { t } = useSiteI18n()
const capabilities = ['memory', 'proactive', 'voice', 'profiles', 'knowledge', 'models']
</script>

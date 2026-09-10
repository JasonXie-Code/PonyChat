<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="shell shell-archive">
    <SiteHeader />
    <main class="archive-main">
      <article class="archive-md">
        <h1>{{ t('updatesTitle') }}</h1><p><time datetime="2026-09-06">{{ t('updatesDate') }}</time></p>
        <p>{{ t('updatesLead') }}</p>
        <section v-for="n in 3" :key="n"><h2>{{ t('update' + n) }}</h2><p>{{ t('update' + n + 'desc') }}</p></section>
        <h2>{{ t('roadmap') }}</h2><p>{{ t('roadmapText') }}</p>
        <a class="hero-download-btn" href="/download/apk" download>{{ t('download') }}</a>
      </article>
    </main>
    <SiteFooter />
  </div>
</template>
<script setup>
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
const { t } = useSiteI18n()
</script>

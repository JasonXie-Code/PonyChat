<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="shell shell-mbti-choice">
    <SiteHeader />
    <main class="mbti-choice-main">
      <div class="mbti-choice-head"><p class="hero-eyebrow">{{ t('mbti') }}</p><h1 class="mbti-choice-title">{{ t('mbtiTitle') }}</h1><p class="mbti-choice-lead">{{ t('mbtiLead') }}</p></div>
      <div class="mbti-choice-grid" role="navigation" :aria-label="t('mbti')">
        <a v-for="item in quizzes" :key="item.key" class="mbti-choice-card" :href="item.url" target="_blank" rel="noopener noreferrer"><h2 class="mbti-choice-card-title">{{ t(item.key) }}</h2><p class="mbti-choice-card-desc">{{ t(item.key + 'Desc') }}</p><span class="mbti-choice-card-cta">{{ t('openQuiz') }}</span></a>
      </div>
      <p class="mbti-choice-footnote">{{ t('externalNote') }}</p>
    </main>
    <SiteFooter />
  </div>
</template>
<script setup>
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
const { t } = useSiteI18n()
const quizzes = [{ key: 'mbtiStandard', url: 'https://standard-mbti.ponychat.org/' }, { key: 'mbtiPony', url: 'https://mbti.ponychat.org/' }]
</script>

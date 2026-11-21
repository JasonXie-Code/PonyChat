<template>
  <header class="site-header international-header">
    <RouterLink class="brand" to="/">
      <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
      <span class="brand-text">PonyChat</span>
    </RouterLink>
    <nav class="header-nav" :aria-label="t('nav')">
      <RouterLink v-if="route.name !== 'home'" to="/">{{ t('home') }}</RouterLink>
      <RouterLink to="/app">{{ t('chat') }}</RouterLink>
      <RouterLink v-if="route.name === 'home'" to="/mbti">{{ t('mbti') }}</RouterLink>
      <a v-if="route.name === 'home'" href="https://music.ponychat.org/" target="_blank" rel="noopener noreferrer">{{ t('music') }}</a>
      <RouterLink to="/detail">{{ t('detail') }}</RouterLink>
      <RouterLink to="/archive">{{ t('archive') }}</RouterLink>
    </nav>
    <LanguageSwitcher />
  </header>
</template>

<script setup>
import { useRoute } from 'vue-router'
import LanguageSwitcher from './LanguageSwitcher.vue'
import { useSiteI18n } from '../i18n/index.js'
import { usePublicUrl } from '../composables/usePublicUrl.js'
const { t } = useSiteI18n()
const logo = usePublicUrl()('logo/logoBK512.png')
const route = useRoute()
</script>

<template>
  <footer class="site-footer">
    <div class="footer-links">
      <RouterLink v-for="item in links" :key="item[0]" :to="item[0]">{{ t(item[1]) }}</RouterLink>
      <a href="/download/apk" download>{{ t('download') }}</a>
    </div>
    <p>{{ t('tagline') }}</p>
  </footer>
</template>
<script setup>
import { useSiteI18n } from '../i18n/index.js'
const { t } = useSiteI18n()
const links = [['/', 'home'], ['/app', 'chat'], ['/character-hall', 'hall'], ['/detail', 'detail'], ['/archive', 'archive'], ['/data-export', 'export']]
</script>

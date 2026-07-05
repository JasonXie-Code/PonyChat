<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-archive">
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

    <main class="archive-main">
      <article class="archive-md" v-html="html" />
    </main>

    <footer class="site-footer">
      <div class="footer-links">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/detail">了解产品</RouterLink>
        <RouterLink to="/archive">项目近况</RouterLink>
        <RouterLink to="/data-export">个人数据导出</RouterLink>
      </div>
      <p>PonyChat · 与小马角色的 AI 陪伴</p>
    </footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import archiveMd from '../content/archive-2026-03-28.md?raw'
import { usePublicUrl } from '../composables/usePublicUrl.js'

marked.setOptions({
  gfm: true,
  breaks: true,
})

const html = computed(() => marked.parse(archiveMd))

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')
</script>

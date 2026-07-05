<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-mbti-choice">
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

    <main class="mbti-choice-main">
      <div class="mbti-choice-head">
        <p class="hero-eyebrow">人格类型测验</p>
        <h1 class="mbti-choice-title">请选择测验类型</h1>
        <p class="mbti-choice-lead">
          标准版为通用情境自测；小马版为 MLP 同人情境娱乐测验。二者题库与说明不同，均在浏览器本地作答。
        </p>
      </div>

      <div class="mbti-choice-grid" role="navigation" aria-label="MBTI 测验入口">
        <a
          class="mbti-choice-card"
          href="https://standard-mbti.ponychat.org/"
          target="_blank"
          rel="noopener noreferrer"
        >
          <h2 class="mbti-choice-card-title">标准 MBTI 测试</h2>
          <p class="mbti-choice-card-desc">
            标准情境、十六型说明与百科；适合自我了解与职业规划参考（非临床测评）。
          </p>
          <span class="mbti-choice-card-cta">打开标准站</span>
        </a>
        <a
          class="mbti-choice-card mbti-choice-card--accent"
          href="https://mbti.ponychat.org/"
          target="_blank"
          rel="noopener noreferrer"
        >
          <h2 class="mbti-choice-card-title">MLP MBTI 测试</h2>
          <p class="mbti-choice-card-desc">
            小马情境同人题库与典型角色参考；娱乐向，与官方 MBTI 及作品版权方无关。
          </p>
          <span class="mbti-choice-card-cta">打开小马站</span>
        </a>
      </div>

      <p class="mbti-choice-footnote">
        测验页将在新标签页打开。返回本站请切换回本标签，或从
        <RouterLink to="/">首页</RouterLink>
        重新进入。
      </p>
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
import { usePublicUrl } from '../composables/usePublicUrl.js'

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')
</script>

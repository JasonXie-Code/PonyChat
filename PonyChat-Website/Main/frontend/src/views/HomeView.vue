<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell shell-home">
    <header class="site-header">
      <RouterLink class="brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat</span>
      </RouterLink>
      <nav class="header-nav" aria-label="页面导航">
        <RouterLink to="/app">网页版聊天</RouterLink>
        <RouterLink to="/mbti">MBTI测试</RouterLink>
        <a href="https://music.ponychat.org/" target="_blank" rel="noopener noreferrer">MLP音乐</a>
        <RouterLink to="/detail">了解产品</RouterLink>
        <RouterLink to="/archive">项目近况</RouterLink>
      </nav>
    </header>

    <main class="home-main">
      <div class="home-hero">
        <p class="hero-eyebrow">PonyChat · 与小马角色的 AI 陪伴</p>
        <h1 class="home-title">把对话交给记忆，把陪伴交给时间。</h1>
        <p class="home-intro home-intro-lead-first">
          PonyChat 想做的是和<strong>小马角色</strong>长期相处的 AI 陪伴：一对一聊天、持续记忆、主动问候，慢慢把角色从「会回复的人设」变成真的熟悉你、记得你的存在。
        </p>
        <p class="home-intro">
          你可以先用 <RouterLink to="/app"><strong>网页版聊天</strong></RouterLink> 试试普通对话；更完整的角色主页、语音消息、长期关系和陪玩相关体验，主要放在 <strong>Android 客户端</strong> 里。
        </p>
        <div class="hero-cta" id="download">
          <template v-if="showHomeActions">
            <p v-if="appVersion" class="hero-version-tag">
              Android 客户端 · v{{ appVersion }}<span v-if="appSizeMb"> · {{ appSizeMb }} MB</span>
            </p>
            <a class="hero-download-btn" :href="apkUrl" download>
              <span class="hero-apk-badge" aria-hidden="true">APK</span>
              <span>下载安装包</span>
              <svg class="hero-download-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </a>
            <div class="hero-action-grid" aria-label="PonyChat 入口">
              <RouterLink class="hero-action-link" to="/character-hall">查看角色大厅</RouterLink>
              <RouterLink class="hero-action-link" to="/app">打开网页版聊天</RouterLink>
              <RouterLink class="hero-action-link" to="/detail">看看 PonyChat 能做什么</RouterLink>
              <RouterLink class="hero-action-link" to="/archive">看看最近做到了哪一步</RouterLink>
            </div>
          </template>
          <section class="home-service-notice" aria-labelledby="service-notice-title">
            <p class="home-service-notice-kicker">重要公告</p>
            <h2 id="service-notice-title">PonyChat 停更通知</h2>
            <div class="home-service-notice-body">
              <p>亲爱的用户：</p>
              <p>
                感谢大家一直以来对 PonyChat 的支持。由于《人工智能拟人化互动服务管理暂行办法》将于 2026 年 7 月 15 日起施行，AI 陪伴、虚拟角色、情感互动类产品将面临更明确的合规要求，包括未成年人保护、虚拟亲密关系限制、用户身份识别、现实提醒、使用时长限制、数据安全与交互内容管理等要求。
              </p>
              <p>
                PonyChat 目前的角色聊天、长期记忆、主动陪伴等功能，属于拟人化互动服务范围。受上述法规影响，我们需要暂停产品更新，并对现有功能进行合规评估与调整。在此期间，PonyChat 将不再新增角色、玩法或情感陪伴功能，部分功能后续也可能下线、限制或重新设计。
              </p>
              <p>我们会尽力妥善处理用户数据，并在有明确方案后同步后续安排。感谢理解与陪伴。</p>
            </div>
          </section>
        </div>
      </div>

      <section class="home-showcase" aria-labelledby="showcase-heading">
        <div class="home-showcase-head">
          <h2 id="showcase-heading" class="home-showcase-title">客户端界面展示</h2>
        </div>
        <ul class="home-showcase-grid">
          <li
            v-for="(item, index) in showcaseItems"
            :key="item.file"
            class="home-showcase-card"
          >
            <figure class="home-showcase-figure">
              <div class="home-showcase-frame">
                <img
                  :src="item.src"
                  :alt="item.alt"
                  class="home-showcase-img"
                  loading="lazy"
                  decoding="async"
                >
              </div>
              <figcaption class="home-showcase-caption">
                <span class="home-showcase-badge" aria-hidden="true">{{ index + 1 }}</span>
                <h3 class="home-showcase-card-title">{{ item.title }}</h3>
                <p class="home-showcase-card-desc">{{ item.desc }}</p>
              </figcaption>
            </figure>
          </li>
        </ul>
      </section>

      <section class="home-differentiator" aria-labelledby="differentiator-heading">
        <div class="home-differentiator-head">
          <p class="home-differentiator-kicker">面向长期陪伴场景的产品差异</p>
          <h2 id="differentiator-heading" class="home-differentiator-title">PonyChat 独特在哪里</h2>
          <p class="home-differentiator-lead">
            PonyChat 不是把角色提示词塞进普通大模型对话框，也不是只做短上下文的角色扮演。它把即时通讯界面、长期记忆、主动消息和陪玩能力组合成一条完整关系链，让角色从“能演”走向“能陪你一起做事”。
          </p>
        </div>

        <div class="investor-metrics" aria-label="PonyChat 差异化指标">
          <div class="investor-metric">
            <span class="investor-metric-value">IM</span>
            <span class="investor-metric-label">产品形态</span>
            <p>消息列表、气泡、语音、转文字、通知和历史分页，更接近真实即时通讯软件。</p>
          </div>
          <div class="investor-metric">
            <span class="investor-metric-value">∞</span>
            <span class="investor-metric-label">关系连续性</span>
            <p>记忆会自动压缩、沉淀和衰减，重要性与时间共同决定保留强度，产品体验上没有对话上下文长度限制。</p>
          </div>
          <div class="investor-metric">
            <span class="investor-metric-value">3</span>
            <span class="investor-metric-label">陪玩档位</span>
            <p>聊天陪玩、操作陪玩、游戏陪玩逐级抬升，从“陪你聊”走向“陪你玩”。</p>
          </div>
        </div>

        <div class="comparison-wrap" aria-label="PonyChat 与常见方案对比">
          <table class="comparison-table">
            <thead>
              <tr>
                <th>对比维度</th>
                <th>大模型聊天框</th>
                <th>常规角色扮演软件</th>
                <th>PonyChat</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>交互界面</td>
                <td>单线程问答，工具感强</td>
                <td>偏剧情框或卡片流</td>
                <td>即时通讯式聊天，支持语音气泡、历史分页、主动消息与多端通知</td>
              </tr>
              <tr>
                <td>关系记忆</td>
                <td>主要依赖当前上下文</td>
                <td>常受上下文窗口和会话切分影响</td>
                <td>服务端权威历史 + 自动压缩摘要 + 长期记忆，让角色持续记住用户偏好与共同经历；不重要的记忆会按重要性和时间衰减</td>
              </tr>
              <tr>
                <td>角色主动性</td>
                <td>通常等待用户输入</td>
                <td>少量脚本或固定触发</td>
                <td>可主动问候、定时 follow-up，并按关系状态延续话题</td>
              </tr>
              <tr>
                <td>陪玩边界</td>
                <td>多停留在建议和文字陪聊</td>
                <td>多停留在角色扮演剧情</td>
                <td>规划为聊天、操作、游戏三档递进：后一档继承前一档能力，并提升可行动性与反应频率</td>
              </tr>
              <tr>
                <td>手机任务</td>
                <td>通常只能给步骤说明</td>
                <td>很少真正进入用户设备工作流</td>
                <td>操作陪玩可发展为带角色风格和用户记忆的手机 Agent，帮用户找内容、点外卖、处理日常任务</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="play-tier-grid" aria-label="PonyChat 陪玩模式三个档位">
          <article class="play-tier-card">
            <div class="play-tier-top">
              <span class="play-tier-index">01</span>
              <span class="play-tier-status">基础能力</span>
            </div>
            <h3>聊天陪玩</h3>
            <p>
              角色围绕你正在做的事进行实时陪聊，可以用文字、语音和主动消息保持陪伴感。这一档解决的是“有人一直在旁边”的问题，是后续操作陪玩和游戏陪玩的情感底座。
            </p>
            <div class="tier-chart" aria-label="聊天陪玩能力成熟度 70%">
              <span style="width: 70%" />
            </div>
          </article>

          <article class="play-tier-card">
            <div class="play-tier-top">
              <span class="play-tier-index">02</span>
              <span class="play-tier-status">手机 Agent</span>
            </div>
            <h3>操作陪玩</h3>
            <p>
              操作陪玩继承聊天陪玩的全部能力，但不局限于游戏。它更像一个带角色风格、并且了解用户长期偏好的手机 Agent：可以理解屏幕，替用户找想看的内容，按口味点外卖，整理信息，处理日常手机任务，并在执行过程中保持角色化陪伴。
            </p>
            <div class="tier-chart" aria-label="操作陪玩能力成熟度 42%">
              <span style="width: 42%" />
            </div>
          </article>

          <article class="play-tier-card play-tier-card-primary">
            <div class="play-tier-top">
              <span class="play-tier-index">03</span>
              <span class="play-tier-status">高频升级</span>
            </div>
            <h3>游戏陪玩</h3>
            <p>
              游戏陪玩继承操作陪玩的全部能力，并把反应频率提升到竞技游戏所需的级别：看懂牌局、战斗、队友状态和目标，在极短时间内给出建议或执行操作。短期可从棋牌等低频场景验证，长期扩展到动作游戏和第二台设备控制，是 PonyChat 最大的产品卖点。
            </p>
            <div class="tier-chart" aria-label="游戏陪玩战略价值 92%">
              <span style="width: 92%" />
            </div>
          </article>
        </div>

        <div class="investment-note" role="note">
          <strong>投资视角</strong>：PonyChat 的机会不只在“更会说话的角色”，而在把聊天、类人记忆、语音、主动触达和手机 Agent 串成关系型产品。三档陪玩是递进结构：操作陪玩继承聊天陪玩，游戏陪玩继承操作陪玩，并把任务执行频率推到竞技场景。记忆系统模仿人类的沉淀方式：重要的事会留下，不重要的事会随时间变淡。一旦陪玩链路跑通，角色留存、付费档位和内容供给都会有更清晰的增长抓手。
        </div>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-links">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/app">网页版聊天</RouterLink>
        <RouterLink to="/character-hall">角色大厅</RouterLink>
        <RouterLink to="/detail">了解产品</RouterLink>
        <RouterLink to="/archive">项目近况</RouterLink>
        <RouterLink to="/data-export">个人数据导出</RouterLink>
        <a :href="apkUrl" download>下载 APK</a>
      </div>
      <p>PonyChat · 与小马角色的 AI 陪伴</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { usePublicUrl } from '../composables/usePublicUrl.js'

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')
/** 与后端 /download/apk 同域；开发环境由 Vite 代理到后端 */
const apkUrl = '/download/apk'
const showHomeActions = false

const appVersion = ref('')
const appSizeMb = ref(0)
onMounted(async () => {
  if (!showHomeActions) return
  try {
    const res = await fetch('/api/app-version')
    if (res.ok) {
      const data = await res.json()
      if (data.available && data.version_name) {
        appVersion.value = data.version_name
        appSizeMb.value = data.size_mb ?? 0
      }
    }
  } catch (_) { /* 网络异常时静默忽略，不影响页面渲染 */ }
})

/** 首页展示图：文件位于 public/Photos，顺序为「列表 → 对话 → 分层叙事」 */
const showcaseItems = [
  {
    file: '236b8c5f657546eb74ff634b8e962ad9.jpg',
    title: '角色列表与搜索',
    desc: '常聊角色、搜索和最近会话放在同一个列表里，想继续找谁聊天，一眼就能回去。',
    alt: 'PonyChat 客户端聊天列表界面：搜索栏与多个小马角色条目',
  },
  {
    file: 'b2853e1bce4c23f0b7ab84c4ac7297b9.jpg',
    title: '一对一聊天与快捷操作',
    desc: '日常私聊支持复制、重试、编辑和语音相关操作，普通聊天历史以服务端记录为准。',
    alt: 'PonyChat 与「紫悦」的对话界面：消息气泡与底部输入区',
  },
  {
    file: '0c258ba573e4fe20a95324f534ec97a4.jpg',
    title: '分层呈现的长回复',
    desc: '剧情向回复会把环境、身体、心理等内容分层展示，适合慢慢读、慢慢推进的沉浸式节奏。',
    alt: 'PonyChat 分步叙事式界面：环境描写、身体描写等彩色区块',
  },
].map((item) => ({ ...item, src: pub(`Photos/${item.file}`) }))
</script>

<template>
  <div class="bg-layer" aria-hidden="true" />

  <div class="shell">
    <header class="site-header">
      <RouterLink class="brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat</span>
      </RouterLink>
      <nav class="header-nav" aria-label="页面导航">
        <RouterLink to="/">首页</RouterLink>
        <a href="#capabilities">能做什么</a>
        <a href="#play">怎么玩</a>
        <a href="#roadmap">进展</a>
        <a href="#web-scope">关于本站</a>
        <RouterLink to="/archive">项目近况</RouterLink>
      </nav>
    </header>

    <main>
      <div class="detail-page-head">
        <h1 class="detail-page-title">了解 PonyChat</h1>
        <p class="detail-page-lead">
          这里用比较直接的话说明 PonyChat 现在能做什么、适合怎么玩，以及哪些方向还在继续开发。具体体验会跟随客户端版本和服务端配置变化。
        </p>
      </div>

      <section id="positioning" class="section-block" aria-labelledby="positioning-heading">
        <div class="section-head">
          <h2 id="positioning-heading">我们想带给您什么</h2>
          <p class="section-lead">一句话与几句心里话。</p>
        </div>
        <div class="cap-md">
          <p><strong>一句话</strong>：接入智能对话，开启您的故事。</p>
          <p>
            <strong>我们想做的体验</strong>：她记得你说过的话，记得你输掉的那一局，也记得你不太开心的那天。很多时候，她不必等你先开口。角色是虚拟的，但陪伴不该只是一次性的问答。
          </p>
          <p>
            <strong>方向</strong>：PonyChat 更在意<strong>你和角色</strong>之间的长期关系，而不是把所有人拉进同一个社交广场。角色大厅、关注、素材和公开档案，都是为了让你更容易发现角色、理解角色、开始一段关系。
          </p>
        </div>
      </section>

      <section id="capabilities" class="section-block" aria-labelledby="capabilities-heading">
        <div class="section-head">
          <h2 id="capabilities-heading">现在能体验到什么</h2>
          <p class="section-lead">按实际使用感受来写，细节会随版本继续调整。</p>
        </div>
        <div class="cap-md">
          <h3>一对一，聊出连续感</h3>
          <p>每个角色都有自己的聊天线和关系线，设定、历史和记忆围绕你们两边展开。适合慢慢聊，慢慢养出只属于你们的默契。</p>
          <h3>长期记忆</h3>
          <p>系统会整理摘要，并在需要时把过去的约定、偏好和情绪线索带回对话里。相关能力可按设置开关，请在合法合规的前提下使用。</p>
          <h3>主动消息</h3>
          <p>在规则允许时，角色可以主动问候、提起约定，或者抛一个小话题，让关系不总是停在“等你先开口”。</p>
          <h3>语音消息</h3>
          <p>普通聊天已经接入角色语音回复链路：语音脚本、情绪提示、TTS 合成、音频缓存和转文字回退都会尽量按消息顺序处理。</p>
          <h3>模型大厅</h3>
          <p>模型大厅用于管理不同供应商、模型和参数。普通用户的日常聊天会走默认轻量模型，开发者或管理员可在普通模式里使用所选模型。</p>
          <h3>小马世界知识（日常聊天）</h3>
          <p>合适的日常聊天场景会检索小马主题知识库，让对话更贴世界观；摘要类请求和游戏/锁分模式不会走这条检索链路。</p>
          <h3>语音与陪玩</h3>
          <p>经典陪玩接口、ASR/TTS WebSocket 已在后端保留并持续维护；Android 侧的 Omni 实时桥接代码存在，但对应实时后端路由仍未正式挂载。</p>
          <h3>角色大厅</h3>
          <p>可以浏览公开角色、进入角色主页、查看头像封面、相册、16 人格和角色档案，也可以给喜欢的角色点喜欢。这里的重点是发现角色，不是刷陌生人动态。</p>
        </div>
      </section>

      <section id="play" class="section-block" aria-labelledby="play-heading">
        <div class="section-head">
          <h2 id="play-heading">可以怎么用</h2>
          <p class="section-lead">不一定要有固定剧本，几种玩法可以单独用，也可以混在一起。</p>
        </div>
        <div class="play-grid">
          <div class="play-item">
            <span class="play-index">01</span>
            <h3>日常陪伴</h3>
            <p>闲聊、吐槽、道晚安早安；记忆会帮你记下偏好和重要的小节点。</p>
          </div>
          <div class="play-item">
            <span class="play-index">02</span>
            <h3>深度角色扮演</h3>
            <p>用设定和长期对话，慢慢堆出只属于你们的小马世界观，越聊越细。</p>
          </div>
          <div class="play-item">
            <span class="play-index">03</span>
            <h3>学习与创作</h3>
            <p>在角色人格下练外语、脑暴剧情；开发者或管理员也可以按需要切换更擅长推理或文笔的模型。</p>
          </div>
          <div class="play-item">
            <span class="play-index">04</span>
            <h3>语音与陪玩</h3>
            <p>用语音少打字；在支持的玩法里，和角色边玩边聊，具体以客户端版本与权限为准。</p>
          </div>
        </div>
      </section>

      <section id="roadmap" class="section-block" aria-labelledby="roadmap-heading">
        <div class="section-head">
          <h2 id="roadmap-heading">进展与规划</h2>
          <p class="section-lead">方便判断现在有哪些能力，哪些仍在路上。</p>
        </div>
        <div class="stage-table-wrap">
          <table class="stage-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>方向</th>
                <th>状态</th>
                <th>大致意味着什么</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>—</td>
                <td>基础能力</td>
                <td>已完成</td>
                <td>后端、Android、角色和基础聊天链路已打通</td>
              </tr>
              <tr>
                <td>一</td>
                <td>长期记忆与合规基础</td>
                <td>已完成</td>
                <td>记忆可提取、可注入，并与设置开关联动</td>
              </tr>
              <tr>
                <td>二</td>
                <td>主动消息</td>
                <td>已完成</td>
                <td>角色可以主动找你聊天，定时消息和多段推送也在迭代</td>
              </tr>
              <tr>
                <td>三</td>
                <td>聊天陪玩与语音</td>
                <td>进行中</td>
                <td>普通聊天语音消息已接入；经典陪玩可用，实时操作陪玩仍在攻关</td>
              </tr>
              <tr>
                <td>四</td>
                <td>音乐共同欣赏</td>
                <td>待开始</td>
                <td>未来计划结合音乐状态、记忆和主动消息</td>
              </tr>
              <tr>
                <td>五</td>
                <td>视频共同讨论</td>
                <td>待开始</td>
                <td>未来计划围绕链接、画面和实时讨论展开</td>
              </tr>
              <tr>
                <td>六</td>
                <td>游戏 AI 真实参与</td>
                <td>规划中</td>
                <td>先从棋牌方向验证，再考虑动作游戏和硬件方案</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section id="web-scope" class="section-block" aria-labelledby="web-scope-heading">
        <div class="section-head">
          <h2 id="web-scope-heading">这个网站和客户端有什么不同</h2>
          <p class="section-lead">官网负责介绍、下载、网页轻量聊天和管理入口；完整体验仍以 Android 为主。</p>
        </div>
        <div class="cap-md">
          <h3>网站能做什么</h3>
          <p>
            这里可以了解 PonyChat、下载 APK，也可以打开轻量的<strong>网页版聊天</strong>。但角色主页、语音消息、游戏/锁分、长期陪玩等完整体验，仍主要在 <strong>Android 客户端</strong> 里提供。
          </p>
          <h3>聊天和游戏模式</h3>
          <p>
            当前主线是适合日常陪伴的<strong>普通聊天</strong>；Galgame / 锁分模式仍由后端和 Android 原生 UI 承载，长期记忆与普通对话隔离。若使用很旧的客户端，建议更新到当前版本。
          </p>
          <h3>剧情向体验（规划中）</h3>
          <p>更偏独立剧本的剧情模式仍在规划中。若未来推出，会在客户端里与日常聊天区分开，篇幅与形式以届时公告为准。</p>
        </div>
        <p class="info-callout" role="note">
          <strong>提示</strong>：想完整使用角色、语音、长期记忆和陪玩相关功能，请在手机上下载 Android 客户端，并连接可信的服务端地址。
        </p>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-links">
        <RouterLink to="/">首页</RouterLink>
        <a href="#capabilities">能做什么</a>
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

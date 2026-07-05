# PonyChat-Website

## 组成

| 路径 | 说明 |
|------|------|
| `Main/frontend/` | Vite + Vue 主站前端：官网（`/`,`/detail`,`/archive`,`/mbti`）、网页聊天（`/app`→`/chat-embed/`）、管理后台（`/admin`→`/admin-embed/`）、服务器终端（`/admin/terminal`）。构建产物 `Main/frontend/dist/`；静态资源与旧版 JS 在 `public/`（含 `css/`、`js/`、`chat-embed/`、`admin-embed/`）。 |
| `Main/deploy/server-usa/` | Server-USA 部署脚本与 Nginx 配置；详见同目录 `DEPLOY-STATIC-WEB.md`。 |
| `MBTI/` | MBTI 子站：`MLP/`（小马 MBTI）、`Standard/`（标准 MBTI）、`Common/`（共享组件）。 |
| `MLP-Songs/` | MLP 歌曲相关小项目（FastAPI 后端 + 静态前端）。 |
| `TTS/` | CosyVoiceTTS 语音实验室与部署脚本；生产入口为 `voice.ponychat.org/cosyvoice`，旧 Qwen3TTS / OmniVoice 仅保留兼容或历史代码。 |
| `LLM/` | OpenAI-compatible 静态聊天前端，支持流式输出、Markdown/KaTeX、代码高亮和图片输入。 |
| `deploy_lib/` | 网站部署脚本共享的增量同步、SSH 和 manifest 工具。 |

## 约定（端侧）

- **顶栏外链**：「MBTI测试」进入站内路由 **`/mbti`**（标准 / 小马 二选一后再打开对应子域）；「MLP音乐」仍为新标签外链。二者仅在首页展示；进入「了解产品」「项目近况」等子页时顶栏隐藏这两项，避免与子站内容抢注意力。
- 营销站与 **MLP MBTI / MLP Music** 对齐深色 slate + 紫青渐变；窄屏顶栏导航与详情页一致（导航换至 Logo 下方）。
- 键盘用户：主要链接与按钮使用 `:focus-visible` 轮廓，避免仅靠 `:hover`。
- 当前首页已有停更/合规评估公告开关，`HomeView.vue` 中 `showHomeActions=false` 时隐藏下载与跳转入口，仅展示公告。

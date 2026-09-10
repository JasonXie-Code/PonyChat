> 2026-09-09：官网网页继续部署在 USA；聊天 API 与最新 APK 由本机 `P:\PonyChat` 提供。下载入口必须保留无缓存代理，不再生成服务器 APK alias 或上传 APK。详见 [运行说明](../../SERVER.md)。

# PonyChat-Website

> 文档状态：2026-08-09 已复核。当前主站使用 Vue 3 + Vite 6；完整工程快照见 `../../../docs/PROJECT_STATUS.md`。

## 组成

| 路径 | 说明 |
|------|------|
| `Main/frontend/` | Vite + Vue 主站前端：官网（`/`,`/detail`,`/archive`,`/mbti`）、网页聊天（`/app`→`/chat-embed/`）、管理后台（`/admin`→`/admin-embed/`）、服务器终端（`/admin/terminal`）。构建产物 `Main/frontend/dist/`；静态资源与旧版 JS 在 `public/`（含 `css/`、`js/`、`chat-embed/`、`admin-embed/`）。 |
| `Main/deploy/server-usa/` | Server-USA 部署脚本与 Nginx 配置；详见同目录 `DEPLOY-STATIC-WEB.md`。 |
| `MBTI/` | MBTI 子站：`MLP/`（小马 MBTI）、`Standard/`（标准 MBTI）、`Common/`（共享组件）。 |
| `MLP-Songs/` | MLP 歌曲相关小项目（FastAPI 后端 + 静态前端）。 |
| `TTS/` | CosyVoiceTTS 语音实验室与部署脚本；生产入口为 `voice.ponychat.org/cosyvoice`，Qwen3TTS 本机 8010 与 CosyVoice 本机 18010 提供语音 API；OmniVoice 保留历史代码。 |
| `LLM/` | OpenAI-compatible 静态聊天前端，支持流式输出、Markdown/KaTeX、代码高亮和图片输入。 |
| `deploy_lib/` | 网站部署脚本共享的增量同步、SSH 和 manifest 工具。 |

## 约定（端侧）

- **顶栏外链**：「MBTI测试」进入站内路由 **`/mbti`**（标准 / 小马 二选一后再打开对应子域）；「MLP音乐」仍为新标签外链。二者仅在首页展示；进入「了解产品」「项目近况」等子页时顶栏隐藏这两项，避免与子站内容抢注意力。
- 营销站与 **MLP MBTI / MLP Music** 对齐深色 slate + 紫青渐变；窄屏顶栏导航与详情页一致（导航换至 Logo 下方）。
- 键盘用户：主要链接与按钮使用 `:focus-visible` 轮廓，避免仅靠 `:hover`。
- 2026-09-06 官网已恢复 Android 下载，移除停更公告，并支持简体中文、繁体中文、英文、俄文。首页版本号读取 `/api/app/version`，下载固定使用同域 `/download/apk`。
- 官网文案集中在 `frontend/src/i18n/{zh-CN,zh-TW,en,ru}.json`。首页、产品页、近况、MBTI 入口及角色大厅、导出、网页聊天的界面文字共用语言状态；角色资料和聊天内容保留原文，独立子站和管理后台不属于官网翻译范围。
- 自动选择顺序：有效 `?lang=` 参数、用户保存的手动选择、浏览器语言列表、地区／时区回退、英文默认。中文优先识别 Hans/Hant，再识别 CN/SG 与 TW/HK/MO；浏览器只提供 `zh` 时参考地区／时区。地区信号来自浏览器区域设置和时区，不请求精确定位，也不依赖第三方 IP 定位接口。
- 语言切换器支持恢复自动选择，手动选择写入 `ponychat.website.language`；页面标题、描述和 HTML `lang` 同步更新。验证命令：`node --test tests/locale.test.js`、`npm run build`，再检查移动端布局及公网下载。
- 旧版 2026-06-03 项目近况原文保留在 `src/content/archive-2026-03-28.md`；当前近况页展示 2026-09-06 的四语产品状态。

## 代码结构与构建

- 管理后台大组件的纯逻辑位于 `frontend/src/views/admin/sections/*Model.js`，scoped 样式位于 `sections/styles/`；组件本身保持页面编排和状态管理。
- PonyDrive 的文件类型、图标和格式化逻辑位于 `frontend/src/views/driveViewModel.js`。
- 页面和管理后台子页由 `frontend/src/router/index.js` 使用动态导入按路由加载。在 `Main/frontend` 运行 `npm run build`；2026-08-09 验证入口 JS 为 120.09 kB、最大延迟 JS 为 295.59 kB，已消除 500 kB chunk 警告。

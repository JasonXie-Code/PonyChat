# MLP Music — ROADMAP

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

## 原则

先跑通上传与访问，再优化体验；与 `PROJECT.md` 同步维护。

## 已完成（实现项）

- [x] `transcode.py` / `generate_index.py` / FastAPI `/api/albums|songs|scores`
- [x] 前端：专辑列表、曲目播放与下载、乐谱 **PDF.js** 画布预览与分页、全屏滑动翻页、统一侧边栏（音乐/乐谱 Tab）、History API 与整页滚动约束
- [x] `deploy.py`：远端目录、venv、Nginx、systemd、媒体 rsync/scp（或 tarball 单次上传）

## 部署说明（媒体）

- 默认：`deploy.py` 将 `media-export` 打成 `dist/mlp-media-export.tar.gz` 后单次 `scp`，远端解压（加速上传）。
- 备选：`--media-rsync` 按目录 rsync/scp。

## 可选后续

- [ ] 全站 HTTPS 与自动续期（certbot）写入运维说明
- [ ] 播放列表持久化（localStorage）
- [ ] PDF.js 改为本地打包或固定版本镜像（降低 CDN 依赖、便于离线）
- [ ] 超大 PDF 内存与首屏性能优化（按需仅渲染可见页等）

## 变更记录

- 2026-04-06：前端顶栏使用 `safe-area-inset-top` 与 `--header-h` 几何对齐（`--header-inner-h` + 安全区），`PROJECT.md` 同步说明。
- 2026-04-06：索引中正剧等专辑不再单独列出 *-extras*，`Extras/` 内曲目并入主专辑。
- 2026-04-06：约定本地长期以 `media-export/`（MP3、乐谱、封面）为主；Ultimate 原始合集为可选，可删并以 `--source` 重指。
- 2026-04-06：同步 `PROJECT.md` 前端架构（统一侧栏、PDF.js、History API、布局与播放器说明）；更新 `ROADMAP` 已完成项与可选后续（替换过时的 iframe/pdf.js 待办）。
- 2026-04-06：项目根目录置于 `PonyChat/MLP-Songs/`，与原始合集同级。
- 2026-04-06：底部播放器 DOM 调整为进度在上、`.player-now` 在下；移动端间距与全宽进度条样式优化。
- 2026-04-06：`deploy.py` 远端 Nginx：检测到 `/etc/letsencrypt/live/` 下证书时保留 HTTPS，避免重复部署抹掉 certbot 配置。
- 2026-04-06：专辑曲目列表序号改为当前列表内 1…n；移动端底部栏收紧时间行与封面/控制行间距。
- 2026-04-06：修复移动端点击侧栏遮罩时 `popstate` 误关专辑页（History 回到 `album` 位时应保持曲目列表）。
- 2026-04-06：乐谱全屏关闭时先恢复焦点再设 `aria-hidden`，消除控制台无障碍告警。
- 2026-04-06：`deploy.py` 远端 SSL：自动选用 `live` 下任意有效证书目录（不限固定文件夹名），修复 443 配置路径错误。
- 2026-04-06：Server-USA 上公网 443 由 `stream` SNI 转发；将 `music` 从空端口 8447 改为 `127.0.0.1:8443`，站点 TLS 改为监听 8443（与 ponychat 其它站一致）。

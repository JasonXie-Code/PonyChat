# MLP Music（PonyChat）

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

## 服务器密钥：唯一来源与用法

**`scripts/deploy.py`** 依赖工作区 [`ServerKeys/ssh_lib.py`](../../../../ServerKeys/ssh_lib.py) 与 `servers.json` 中 **`usa`** 条目：**唯一权威**为 [`ServerKeys/servers.json`](../../../../ServerKeys/servers.json)；密钥安全与排障见 [`ServerKeys.md`](../../ServerKeys.md)（PonyChat 仓库根）。

## 定位

在 `www.music.ponychat.org` 提供 MLP 相关音乐在线试听、MP3 下载，以及乐谱 PDF 预览与下载。元数据由 FastAPI 提供；音频、PDF、封面由 Nginx 直接提供（支持 Range）。

### 2026-10-07 收听平台升级

- 无账号、无收藏、无收听历史；队列、音量与播放模式仅保留在当前页面内。新打开页面不恢复、不自动播放；分享链接可以预选歌曲，但仍需手动播放。
- 直接歌曲搜索，支持已整理的中文别名、角色、剧集和双语歌词片段；默认主发行版本，可显示伴奏、Demo 与其他版本。首页有主题精选与角色入口。
- 临时队列支持加入、下一首播放、移除、清空；顺序、随机、单曲循环、列表循环；缓冲/失败/重试反馈、系统媒体控制与仅衰减的音量均衡。
- 正式主发行人声曲目提供原文与中文意译、点击歌词跳转、自动高亮/滚动、手动浏览暂停跟随和同步微调。Extras、Demo、伴奏、片尾及本地派生音频不生成歌词。
- 歌词从本地用户提供音频识别，并与已有本地歌词资料校正；声学对齐通过质量门槛后才替换结果。机器识别和翻译属于待校对数据，不等同于逐曲人工验收。
- 歌词提取保留首个演唱者标签之前的正文及音频中的英文对白，排除“另见/参见”链接。对齐时保留 ASR 漏识别的合唱回应，避免错误时间锚点将其压缩消失；`A True, True Friend` 的开场对白与前四句已单独回归验证。
- 原 AUTO 的四首五线谱/简谱跟随并入播放页“跟谱”，只由主播放器发声。四首音频哈希与原跟谱音频一致。双击谱面跳转主播放进度。
- 滚动条统一由 `web/scrollbars.css` 管理，主页面与跟谱 iframe 共用 PonyChat 的细紫色透明轨道。

离线构建：工作区 Python 3.10 执行 `scripts/build_catalog.py`、`scripts/build_lyrics.py`、`scripts/align_lyrics.py`，最后执行 `scripts/build_lyrics.py --translate-only`。模型和 ASR/翻译缓存位于外部工具目录与忽略的 `dist/lyrics-cache/`，站点运行时只读 JSON，不持有模型或提供商密钥。

验证：`P:\PonyChat\.venv\Scripts\python.exe -m pytest tests/test_music.py -q`。部署前提交音乐站范围，再执行 `py -3.10 scripts/release.py --redirect-auto`；只上传应用/歌词/跟谱与网页，不重传音频库。脚本备份原应用、网页与两个虚拟主机，添加 `/follow-media/` 代理，并将旧 AUTO 域名重定向到音乐站。旧独立后端停止，原文件保留以便回滚。

## 目录（均在 `PonyChat/PonyChat-Website/MLP-Songs/`）

| 路径 | 说明 |
|------|------|
| `media-export/` | **建议本地长期保留**：已压缩的 MP3（`audio/`）、乐谱 PDF（`scores/`）、封面（`covers/`）、图表（`charts/` 若有）；体积大，勿提交仓库。站点与索引均以此为工作副本。 |
| `My Little Pony Friendship is Magic - Ultimate Soundtrack Collection v1.2/` | **可选**：Ultimate 原始合集（FLAC 等）。仅首次或需全量重转码时使用；若磁盘紧张可删除，改由 `python scripts/transcode.py --source "路径"` 指向其它位置的源。 |
| `scripts/transcode.py` | FLAC→MP3 320k，整理 `media-export/`；小马国女孩各子文件夹封面写入 `covers/equestria-girls__*/`（`--sync-eqg-covers` 可单独补封面） |
| `scripts/generate_index.py` | 扫描 `media-export/` → `app/data/index.json`（正剧等专辑的 `Extras/` 曲目并入主专辑；`equestria-girls/` 下每个一级子文件夹仍单独成专辑） |
| `scripts/deploy.py` | 部署到 Server-USA |
| `app/` | FastAPI（`/api/*`） |
| `web/` | 静态前端（专辑/曲目/播放器、乐谱 PDF.js 预览；详见下节） |

### 前端（`web/`）

- **品牌图标**：`web/logo.png` 为 PonyChat 主站同款角标；顶栏 `<img>` 指向 `/logo.png`，`rel="icon"` / `apple-touch-icon` 指向由同源 logo 生成的圆角版 `/favicon.png`，浏览器标签页显示该圆角图标。
- **布局**：整页不滚动（`html`/`body` 锁视口高度）；仅侧栏与主内容区内部滚动，避免双滚动条。
- **顶栏与安全区**：`--header-inner-h` 为顶栏内容行高；`--header-h` 为 `inner + env(safe-area-inset-top)`，与固定顶栏 `.top` 的 `padding-top`、以及 `.shell` 的 `margin-top`、侧栏/遮罩的 `top` 一致，避免刘海屏下主内容顶到状态栏后方。
- **统一侧边栏**：`#sidebar` 随顶栏 Tab 在「专辑筛选」与「乐谱列表」之间切换；移动端同一抽屉与 `#sidebarOverlay`，无独立乐谱侧栏层。
- **乐谱**：PDF.js（CDN）画布渲染分页；页内工具栏翻页、下载当前页 PNG；全屏 lightbox 支持左右滑动翻页（关闭以右上角按钮或返回键等行为为准）。
- **导航**：专辑视图、侧栏开关、乐谱全屏等配合 **History API**，便于系统返回键逐级关闭浮层。移动端侧栏打开时会 `pushState`；点击遮罩关闭会 `history.back()` 回到上一历史位（若在专辑内则为 `album`），`popstate` 需识别该情况，避免误执行「退出专辑」。
- **曲目列表**：专辑内曲目序号按**当前列表排序后的顺序**显示为 1…n，不直接使用元数据 `track`（同一专辑内可出现同号，如正式版与 Demo）。**整行点击即播放**（与移动端一致）；仅「下载」链接触发下载、不播放。
- **播放器**：底部栏为「进度区 + `.player-now`（封面/元数据/控制）」结构；桌面端用 flex `order` 保持左信息右进度；手机端自上而下全宽进度条与统一水平内边距。播放/暂停为内联 SVG，避免部分环境下 emoji 出现异常描边。

## 本地流程

1. 安装 ffmpeg，执行：`python scripts/transcode.py`（可选 `--dry-run`；源目录不在默认路径时用 `--source`）  
   - 若已只保留 `media-export/`、不再持有原始合集，则**无需**再跑本步，除非您从备份或其它路径重新提供源。
2. `python scripts/generate_index.py`
3. `cd app && pip install -r requirements.txt && uvicorn main:app --reload --host 127.0.0.1 --port 8822`  
   浏览器访问 `http://127.0.0.1:8822/`（开发时由 uvicorn 挂载 `web/` 与 `media-export/`）

## 生产（Server-USA）

- 应用：`/opt/mlp-music/`，systemd：`mlp-music.service`，监听 `127.0.0.1:8822`
- 启动先预热正式跟谱目录，完成后才监听端口；完整冷启动可能需要数分钟，部署探测应等待预热完成。`/api/health` 用于进程存活检查，`/api/ready` 实际加载目录并返回歌曲、专辑、乐谱与可用跟谱数量；故障或空曲库返回 503。
- 跟谱缓存按歌曲失效，只保存依赖指纹；每次请求仍检查全部文件时钟与符号链接目标。专辑、乐谱、搜索、歌词读取不启动跟谱证据验证。只修复运行代码时，按提交导出并备份精确变更文件，不重传 `app/data` 或媒体。
- 暖扫描复用压缩的依赖定位计划，逐次重新读取完整文件时钟和链接目标；任何时钟、定位、根目录、注册内容或 OMR 成员变化都重新发现依赖并执行原验收。计划仅节省证书解析和路径遍历，不持久化证据原文或绕过验收。
- 完整验证退出及启动预热结束后回收已释放的证据对象；Linux/glibc 同时归还空闲堆页，避免下一次跟谱验证叠加旧堆高水位。原验证锁、注册谓词和字节绑定门槛保持不变。
- 前端：`/var/www/mlp-music/`
- 媒体：`/data/mlp-music/`（`audio/`、`scores/`、`covers/`、`charts/`）
- 一键部署：`python scripts/deploy.py`（需 `ServerKeys/ssh_lib.py` 与 `usa` 密钥）；若服务器上已有 Let's Encrypt 证书，部署脚本会写入 80 重定向与 **本机 `127.0.0.1:8443` 上的 TLS**（与 Server-USA 上 **stream SNI** 一致：公网 443 由 `/etc/nginx/stream.d/sni-route.conf` 按域名转发至 8443，**勿**再对 `music` 使用占位端口 8447）。证书目录名可为 `music.ponychat.org-0001` 等，脚本会扫描 `/etc/letsencrypt/live/`。无证书时：`certbot --nginx -d music.ponychat.org -d www.music.ponychat.org`。  
  - 媒体默认：本地将 `media-export` 打成 `dist/mlp-media-export.tar.gz`，单次 `scp` 上传后在服务器 `tar -xzf` 解压至 `/data/mlp-music/`（比海量小文件直传更快）  
  - 若需按目录同步：`python scripts/deploy.py --media-rsync`

## DNS

- A 记录：`music.ponychat.org`、`www.music.ponychat.org` → `154.17.23.237`
- HTTPS：在服务器上执行 `certbot --nginx` 等（HTTP 由部署脚本先写好）

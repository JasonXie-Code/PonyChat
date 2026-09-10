# Standard MBTI

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

标准情境 MBTI 人格倾向自测（手机优先）。产品约定见 [PROJECT.md](PROJECT.md)，阶段规划见 [ROADMAP.md](ROADMAP.md)。

## 一键启动（Windows）

1. 首次使用请在 **`web`** 目录执行 `npm install` 安装依赖。
2. 回到 **`MBTI/Standard` 目录**，双击 **`启动网站.bat`**（若存在）：会调用便携环境与 `misc/start_dev.py` 启动 `web` 下的开发服务。

与 **PonyChat 主仓库**共用便携环境：绿化后上级目录存在 `../misc/tools/python/python.exe` 时将优先使用；否则使用系统 `python`。

## 本地运行（命令行）

```bash
cd web
npm install
npm run dev
```

浏览器打开终端提示的本地地址（一般为 `http://127.0.0.1:5173`）。

## 构建与类型检查

```bash
cd web
npm run build
npm run typecheck   # tsc --noEmit
npm run preview     # 本地预览 dist
```

产物在 **`web/dist/`**。部署到静态托管时，请为 **SPA** 配置「所有路径回退到 `index.html`」。生产 Nginx 配置见主仓库 `PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf`（`standard-mbti.ponychat.org` 站点块）。

## 功能说明（摘要）

- 题库 **72** 题，测验随机抽 **12** 或 **36** 题并打乱；计分见 `docs/SCORING.md`。
- `docs/questions.json` 与 `web/src/data/questions.json` 须保持一致（也可用 `misc/gen_standard_questions.py` 重新生成）。
- **无后端**：匿名 ID 与作答保存在浏览器 `localStorage`。
- 路由 **`/types`**、**`/types/:mbti`** 为 16 型浏览与示例结果页。

## 部署到 Server-USA

```powershell
cd web
npm run build
cd ..
python misc/deploy_standard_mbti_server_usa.py
```

远端静态目录：`/var/www/standard-mbti-static`，域名 **`standard-mbti.ponychat.org`**。HTTPS 与 Nginx 站点块说明见仓库根目录 **[SERVER.md](../../../SERVER.md)**。

连接参数从 `P:\ServerKeys\servers.json` 读取（与 `MBTI/MLP` 部署脚本相同机制）。

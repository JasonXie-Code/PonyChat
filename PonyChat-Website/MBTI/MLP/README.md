# MLP MBTI

同人向 MBTI 测验（手机优先）。产品约定见 [PROJECT.md](PROJECT.md)，阶段规划见 [ROADMAP.md](ROADMAP.md)。

## 一键启动（Windows）

1. 首次使用请在 **`web`** 目录执行 `npm install` 安装依赖。
2. 回到 **`MBTI/MLP` 目录**，双击 **`启动网站.bat`**：会先执行与 PonyChat 主仓库相同的**绿色部署**（`Backend/scripts/launch/AAA_deploy_portable.bat --no-pause`），再调用 `misc/start_dev.py` 启动 `web` 下的开发服务。

与 **PonyChat 主仓库**共用便携环境：绿化后上级目录存在 `../misc/tools/python/python.exe` 时将优先使用；否则使用系统 `python`。开发服务器会尝试把 `../misc/tools/node-windows-64`（或 `node`）加入 `PATH`，以便在未装全局 Node 时运行 `npm`。

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

产物在 **`web/dist/`**。部署到静态托管时，请为 **SPA** 配置「所有路径回退到 `index.html`」（否则直接打开或刷新 `/quiz`、`/result` 等可能 404）。若站点不在域名根路径，需在 `web/vite.config.ts` 设置 `base: '/子路径/'` 后再构建。

## 功能说明（摘要）

- 题库 **72** 题，测验随机抽 **12** 或 **36** 题并打乱；计分见 `docs/SCORING.md`。
- `docs/questions.json` 与 `web/src/data/questions.json` 须保持一致。
- **无后端**：匿名 ID 与作答保存在浏览器 `localStorage`。
- 路由 **`/types`**、**`/types/:mbti`** 为 16 型浏览与示例结果页。

## 部署到生产（SSH + Nginx）

生产环境示例：**静态根目录** `/var/www/mbti`，**Nginx** 配置见 **`misc/nginx-mbti.ponychat.org.conf`**（`server_name` 与站点域名一致，如 `mbti.ponychat.org`）。

1. **DNS**：为站点域名配置 **A/AAAA** 指向服务器公网 IP。
2. **服务器首次准备**（SSH 登录后，路径按实际调整）：
   ```bash
   sudo mkdir -p /var/www/mbti
   sudo chown -R "$USER":"$USER" /var/www/mbti
   sudo cp /path/to/misc/nginx-mbti.ponychat.org.conf /etc/nginx/sites-available/mbti.ponychat.org
   sudo ln -sf /etc/nginx/sites-available/mbti.ponychat.org /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```
3. **本机发布**：在项目根目录执行 **`.\misc\deploy.ps1`**（先 `npm run build`，再 `scp` 上传 `web/dist`）。未配置 SSH 别名时可指定：
   ```powershell
   .\misc\deploy.ps1 -SshTarget "root@103.117.100.19" -IdentityFile "TheServerHK-CN2\TheServerHK-CN2-id_rsa\id_rsa.pem"
   ```
4. **HTTPS**（可选）：DNS 生效后 `sudo certbot --nginx -d mbti.ponychat.org`（域名改为实际值）。

**Windows 私钥权限**：若 OpenSSH 提示 “Bad permissions” 或 “UNPROTECTED PRIVATE KEY”，在密钥所在目录对 `.pem` 执行：

`icacls .\id_rsa.pem /reset; icacls .\id_rsa.pem /inheritance:r; icacls .\id_rsa.pem /grant:r "$($env:USERNAME):(F)"`

服务器与密钥若仅在本机保管，请**勿将私钥与明文密码提交到公开仓库**。

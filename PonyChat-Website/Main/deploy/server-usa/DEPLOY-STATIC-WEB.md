# Server-USA：部署主站静态前端（ponychat.org / www.ponychat.org / drive.ponychat.org）

`www.ponychat.org`、`ponychat.org` 与 `drive.ponychat.org` **均**指向同一静态站点（仓库内 **`PonyChat-Website/Main/frontend`** 的 **`npm run build`** 产物）。`drive.ponychat.org` 在根路径直接渲染个人网盘，不做 `/drive` 重定向；主站域名上的 `/drive` 与 `/api/drive` 会返回 404。

## 1. DNS（由您在 DNS 服务商配置）

- **`ponychat.org`**：**A** 记录 → Server-USA 公网 IPv4（`154.17.23.237`）。
- **`www.ponychat.org`**：**A** 或 **CNAME**（若用 CNAME 则指向 `ponychat.org` 或同机别名，按服务商规则）。
- **`drive.ponychat.org`**：**A** 记录 → Server-USA 公网 IPv4（`154.17.23.237`）。

生效后：`certbot` 与浏览器访问均依赖解析正确。

## 2. 本机构建

在 **PonyChat 仓库根**：

```bash
cd PonyChat-Website/Main/frontend
npm install
npm run build
```

产物目录：**`PonyChat-Website/Main/frontend/dist/`**。

### 一键同步（本机已配置 SSH 密钥时）

在仓库根执行（使用 `P:\ServerKeys\servers.json` 中 `servers.usa` 等配置）：

```bash
python PonyChat-Website/Main/deploy/server-usa/deploy_static_web_now.py
```

可通过环境变量 **`PONYCHAT_USA_HOST`**、**`PONYCHAT_USA_KEY`** 覆盖主机与私钥路径。

## 3. 上传到 Server-USA

在**能 SSH 到 Server-USA `root`** 的机器上：

```bash
KEY=/path/to/id_rsa.pem
HOST=154.17.23.237

ssh -i $KEY root@$HOST "mkdir -p /var/www/ponychat-static"

# 清空旧文件后同步（注意末尾 /）
scp -i $KEY -r PonyChat-Website/Main/frontend/dist/. root@$HOST:/var/www/ponychat-static/
```

若已安装 **rsync**：

```bash
rsync -avz --delete -e "ssh -i $KEY" PonyChat-Website/Main/frontend/dist/ root@$HOST:/var/www/ponychat-static/
```

## 4. Nginx 与证书（Server-USA 上）

1. 将仓库内 **`PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf`** 安装为 **`/etc/nginx/sites-available/ponychat-www`**，并链到 **`sites-enabled`**：

```bash
scp -i $KEY PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf root@$HOST:/tmp/ponychat-www.conf
ssh -i $KEY root@$HOST "
  install -m 0644 /tmp/ponychat-www.conf /etc/nginx/sites-available/ponychat-www
  ln -sf /etc/nginx/sites-available/ponychat-www /etc/nginx/sites-enabled/ponychat-www
  nginx -t && systemctl reload nginx
"
```

2. 若尚未为 **`www.ponychat.org` + `ponychat.org` + `drive.ponychat.org`** 签发证书：

```bash
ssh -i $KEY root@$HOST \
  "certbot certonly --webroot -w /var/www/html -d www.ponychat.org -d ponychat.org -d drive.ponychat.org"
```

（或沿用已有 **`/etc/letsencrypt/live/www.ponychat.org/`**。）

### 4.1 为额外子域增加 HTTPS（Let's Encrypt，与主站同证书）

适用：**子域**（例如 **`drive.ponychat.org`**、**`mbti.ponychat.org`**）由**同一台** Server-USA 提供静态页，TLS 仍终止在 **`127.0.0.1:8443`**。

1. **DNS**：子域 **A** 记录指向 `154.17.23.237`。若使用 Cloudflare：签发与续期 HTTP-01 验证时，该记录需为 **DNS only（灰云）**。
2. **Nginx**：`nginx-ponychat-www.conf` 已含 **`drive.ponychat.org`** 的 `server`，与主站共用 **`/var/www/ponychat-static`**；也含 **`mbti.ponychat.org`** 的静态子域示例，根目录默认 **`/var/www/mbti-ponychat-static`**（按需改路径后 `nginx -t && systemctl reload nginx`）。
3. **扩展证书主机名**（在已有 `www` + 根域证书上增加 SAN）：

```bash
ssh -i $KEY root@$HOST \
  "certbot certonly --webroot -w /var/www/html --expand \
   -d www.ponychat.org -d ponychat.org -d drive.ponychat.org -d mbti.ponychat.org"
```

证书路径仍为 **`/etc/letsencrypt/live/www.ponychat.org/`**，无需改 `ssl_certificate` 行。

4. **`stream` SNI**：在 **`/etc/nginx/nginx.conf`** 的 `map $ssl_preread_server_name` 中为子域增加一行：

```text
mbti.ponychat.org   127.0.0.1:8443;
drive.ponychat.org  127.0.0.1:8443;
```

然后 **`nginx -t && systemctl reload nginx`**。

## 5. stream SNI（公网 443 → 本机 TLS）

公网 **443** 由 **`nginx.conf` 内 `stream { map ... }`** 按域名转发到 **`127.0.0.1:8443`**。请确认 **`map`** 中**同时**包含：

```text
www.ponychat.org    127.0.0.1:8443;
ponychat.org        127.0.0.1:8443;
mbti.ponychat.org   127.0.0.1:8443;
drive.ponychat.org  127.0.0.1:8443;
```

修改后：**`nginx -t && systemctl reload nginx`**。

## 6. 验收

- `curl -I https://www.ponychat.org/`、`curl -I https://ponychat.org/` → **200**，且为静态页 `index.html`。
- `curl -I https://drive.ponychat.org/` → **200**；`curl -I https://ponychat.org/drive` 与 `curl -I https://ponychat.org/api/drive` → **404**。
- 若已配置子域：`curl -I https://mbti.ponychat.org/` → **200**。
- 浏览器访问 `/detail`、`/archive` 等前端路由应正常（`try_files ... /index.html`）。

## 7. 后续更新

每次改文案或前端后：重复 **§2 构建** + **§3 上传** 覆盖 `/var/www/ponychat-static` 即可，**一般无需**动 Nginx 与证书。子域站点同理覆盖其 `root` 目录（如 `/var/www/mbti-ponychat-static`）。

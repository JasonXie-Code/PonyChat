# PonyChat 国内入口 HTTPS / WSS

## 部署范围

App 6.0.6（384）的正式地址为 `https://39.101.74.217`，实时同步使用 `wss://39.101.74.217`。API、登录、聊天、语音桥接及 APK 更新走国内入口。后端仍运行于 Windows `P:/PonyChat`，本次不迁移、不重启后端。

链路：App TLS → CN 公网 443 → Nginx stream → CN 回环 10449（终止 TLS）→ 回环 18500 → SSH 加密隧道 → Windows 回环 5000。TLS 在 CN 终止，属于分段加密，不是客户端到模型的端到端加密。

原 SNI 域名路由和 default 路由保留。仅新增空 SNI 与 IP 字面量 SNI 指向 10449；IP TLS 客户端通常不发送 DNS SNI。共享服务器既有域名继续使用原上游。

共享 stream 转发空闲超时从 300 秒延长到 900 秒，覆盖聊天客户端 600 秒的等待窗口；现有其他 SNI 路由的空闲连接也采用此更长超时。

## 证书与续期

- Let's Encrypt 公信 IP 证书，SAN 为 `39.101.74.217`，初次签发有效期至 2026-09-18 00:10:59 UTC。
- 独立 Certbot 5.4.0：`/opt/ponychat-certbot/bin/certbot`；不替换其他站点的系统 Certbot。
- 配置、证书：`/etc/letsencrypt-ponychat`；工作目录：`/var/lib/letsencrypt-ponychat`；日志：`/var/log/letsencrypt-ponychat`。
- HTTP-01 验证目录：`/var/www/ponychat-acme`，仅新增 `/.well-known/acme-challenge/`。
- `ponychat-cert-renew.timer` 每六小时检查续期，随机延迟最多五分钟，启用 Persistent。部署钩子先 `nginx -t`，再 reload。
- 已执行 `renew --dry-run --run-deploy-hooks`，模拟续期和 Nginx reload 成功。
- IP 证书为短期证书，续期失败需要在到期前处理；可用 `systemctl status ponychat-cert-renew.service` 和独立 Certbot 日志排查。

操作脚本：`scripts/ops/enable_cn_tls.py`，按 `prepare`、`issue`、`install`、`verify-renewal` 执行；`require-https` 仅在新版完成发布后执行。

依据：[Let's Encrypt IP 证书与 Certbot 指南](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。

## App 传输策略

- 移除全信任 TrustManager 和始终返回 true 的主机名校验，REST、聊天、WebSocket、语音及 Coil 均使用平台证书校验。
- 正式包禁止明文，客户端不跟随 HTTPS → HTTP 降级重定向。
- 历史国内 HTTP 媒体地址在网络请求前升级到 HTTPS；旧生产地址偏好迁移至 HTTPS。
- 正式包不接受用户偏好中的调试地址覆盖；Debug 包允许本地 HTTP 测试，但国内生产 IP 仍禁用明文。
- 针对 Android 7.0，国内 IP 的信任配置补充官方 ISRG Root X1，仍验证完整证书链与 IP。其 DER SHA-256 为 `96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6`；下载自官方 `https://letsencrypt.org/certs/isrgrootx1.pem`。
- `androidTest/assets/untrusted-test.p12` 是专供拒绝伪造证书测试的自签测试证书，公开测试密码 `test-only-ponychat`，不进入 Release APK。

## 旧版迁移与回滚

新版发布后，CN 的 PonyChat HTTP 业务接口返回 426 升级提示；只有 `/api/app/version` 和 `/download/apk` 保留 HTTP 升级通道。其他业务（如 `/scenery/`）不使用此规则。旧版在安装新版前仍可能发出 HTTP 请求，不能把新版保护描述成已经替旧版加密。

原服务器配置备份于 `/root/ponychat-tls-20260911`。若需临时恢复旧版访问，恢复备份中的 `ponychat-local-ip.conf`，执行 `nginx -t && systemctl reload nginx`，无需停用 HTTPS 或改变现有 APK。若撤销 TLS，需恢复 `sni-route.conf`，移除本次 `ponychat-ip-tls` 启用链接并停止续期 timer；这会使新版无法连接，必须与 APK 回滚协调。

APK 发布前另存本机 `var/releases/latest.json`；版本化 APK 和旧版签名保持不变。验收文件位于 `docs/testing/tls-20260911/`。

# Server-USA 2026-09-06 管理连接故障恢复

服务器：154.17.23.237，Ubuntu 24.04，2 vCPU / 2 GB RAM。

## 已确认事实

- 约 21:00 起，SSH 直连和经已有服务器中转连接均在 banner 或登录阶段超时；部分网站 HTTP 仍可响应。
- VNC 显示的 npm ci / next-server OOM 经重启前 journal 核实，发生于 8 月 1 日和 8 月 25 日，并不是 9 月 6 日的新 OOM。
- 9 月 6 日 21:02:54 有 pam_systemd(sshd:session) “Failed to create session: Connection timed out”。这证明会话管理出现超时，但不足以确定最底层原因；未找到同一时段的新内核 OOM 记录。
- 用户没有控制台 root 密码。未重设密码、未开启 SSH 密码登录；继续使用已有 SSH 密钥。

## 恢复操作和验证

在 DMIT 当前 Server-USA 实例上执行重启，约 21:12 确认 SSH 恢复。官网 HTTP 200，PonyChat 健康接口 running，systemd failed units 为 0。

重启后内存 1962 MiB、available 约 1003–1093 MiB；原有 /swapfile 为 4095 MiB、使用 0；根磁盘约剩余 30 GB。没有扩容交换空间，4 GB 暂无不足的现场证据。

PonyChat Harness 默认同时运行一个 SDK 子进程，等待可取消。生产同时配置 MemoryHigh=768M、MemoryMax=1G、MemorySwapMax=1G、TasksMax=256，避免单个后端无上限挤占共享主机。配置源为 Backend/deploy/40-harness-capacity.conf；服务器在 /etc/systemd/system/ponychat-backend.service.d/ 下保存，已有文件会先备份到 /var/backups/ponychat-recovery-20260906/。本次检查后端 MemoryCurrent 约 465–487 MB、峰值约 500 MB。

限额属于预防措施，不能当作今日故障根因已查明。2 GB 是多个网站共同使用的物理内存，交换空间只适合缓冲峰值。后续避免在生产并行 npm ci / 构建；持续出现交换换入换出或内存压力时，再根据负载决定迁移构建或升级物理内存。

回滚限额：恢复备份的同名 drop-in（原先不存在时仅移除本次创建的文件），清除本次 runtime 属性覆盖并 daemon-reload，确认生效值；不要改动其他服务配置。

# PonyChat 后端部署说明

本目录存放 Server-USA 后端部署脚本、systemd 服务文件，以及远程测试注意事项。

## 部署命令

在仓库根目录运行：

```powershell
python Backend/deploy/deploy_backend_server_usa.py
```

不要在 `Backend/deploy` 目录里用相对路径直接运行部署命令。部署脚本会自行定位仓库根目录和 `Backend` 目录。

## 部署脚本流程

`deploy_backend_server_usa.py` 会按下面的顺序执行：

1. 读取 `P:/ServerKeys/servers.json` 里的 Server-USA SSH 配置。
2. 在服务器上定位远端 `Backend` 目录；生产环境通常是 `/opt/ponychat/Backend`。
3. 生成新的 `Backend/.deploy_revision` 部署令牌。
4. 计算本地 `Backend` 文件和远端 `Backend` 文件的 MD5 差异。
5. 跳过运行期或危险路径，例如 `database`、`deploy`、`data`、`backups`、图片、日志、密钥、数据库文件等。
6. 只打包上传新增或变更的后端文件，并在服务器解压。
7. 如果 `ponychat-backend.service` 有变化，同步到 `/etc/systemd/system/ponychat-backend.service` 并执行 `daemon-reload`。
8. 重启 `ponychat-backend` 服务。
9. 轮询 `/api/health`，直到返回的 `deploy_token` 与本次部署令牌一致，确认新进程已经加载。

## 生产运行入口

远端服务入口以 systemd 为准：

```bash
systemctl cat ponychat-backend
```

当前关键配置是：

```ini
WorkingDirectory=/opt/ponychat
ExecStart=/opt/ponychat/.venv/bin/python -m Backend
```

仓库中的默认服务模板使用 CosyVoice：

```ini
Environment=PONYCHAT_TTS_PROVIDER=cosyvoice
Environment=PONYCHAT_COSYVOICE_BASE_URL=https://voice.ponychat.org/cosyvoice
Environment=COSYVOICE_MODEL=cosyvoice-v3.5-plus
```

旧本机 Qwen3TTS 隧道不再是默认部署依赖。若临时回退到本机语音栈，必须显式改 systemd 环境变量并确认对应计划任务、隧道和 `127.0.0.1:18012` 可用。

远程调试和远程后端测试必须使用相同的工作目录和 Python 解释器：

```bash
cd /opt/ponychat
/opt/ponychat/.venv/bin/python Backend/scripts/example_test.py
```

一次性远程测试片段也应该这样运行：

```bash
cd /opt/ponychat
/opt/ponychat/.venv/bin/python - <<'PY'
# test code here
PY
```

不要用裸 `python3` 跑远程后端测试。系统 Python 可能没有安装后端依赖，例如 `httpx`、数据库 helper、模型客户端等；如果测试因为解释器不对而在打到 API 之前失败，这不算后端测试结果。

## 健康检查

部署完成后，可在服务器上检查：

```bash
curl -s http://127.0.0.1:5000/api/health
```

预期返回包含：

```json
{
  "status": "running",
  "deploy_token": "部署脚本本次打印的 deploy_token"
}
```

## 角色回复测试数据规则

测试普通对话或后端角色回复时，必须隔离测试数据：

- 创建全新的随机测试用户。
- 将测试用户会员等级设为 `developer`。
- 先把目标 `System` 角色临时克隆到测试用户下。
- 请求接口时只使用临时克隆角色 ID，不要直接请求 `System` 角色 ID。
- 测试结束后清理测试用户、会员、克隆角色、会话、消息、记忆、场景状态等相关数据。

更多远程测试注意事项见 [`REMOTE_TESTING.md`](REMOTE_TESTING.md)。

## 密钥配置

`Backend/conf/models/*.json` 中的 `api_key` 均为 `${ENV_NAME}` 占位符。生产环境必须通过 `/opt/ponychat/.env`、systemd `EnvironmentFile` 或部署平台注入真实值。参考仓库根目录 `.env.example`，不要把真实 `.env` 或供应商 Key 提交到 Git。

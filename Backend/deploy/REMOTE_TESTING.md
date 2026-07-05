# 远程后端测试注意事项

这份说明给 Codex 和维护者使用，避免远程测试时因为环境不一致得到错误结论。

## 使用和 systemd 相同的 Python 环境

远程后端测试不要用裸 `python3`。生产服务使用 `ponychat-backend.service` 里声明的解释器运行：

```bash
cd /opt/ponychat
/opt/ponychat/.venv/bin/python -m Backend
```

一次性远程测试也必须使用相同的工作目录和 Python：

```bash
cd /opt/ponychat
/opt/ponychat/.venv/bin/python - <<'PY'
# test code here
PY
```

系统自带的 `python3` 可能没有安装后端依赖，例如 `httpx`、数据库 helper、模型客户端等。若测试因为缺依赖而没打到 API，这不是后端测试失败，只是测试命令用错了环境。

## 先确认服务入口

如果服务文件有变更，先查看 systemd 当前实际配置：

```bash
systemctl cat ponychat-backend
```

远程测试命令要以 systemd 显示的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 为准。

语音相关测试还要核对 systemd 中的 TTS provider。当前仓库模板默认：

```bash
PONYCHAT_TTS_PROVIDER=cosyvoice
PONYCHAT_COSYVOICE_BASE_URL=https://voice.ponychat.org/cosyvoice
```

如果远端实际仍指向 `voice_lab` / `127.0.0.1:18012`，测试结论必须同时记录本机 Qwen3TTS 隧道状态。

## 测试数据规则

角色回复后端测试必须这样隔离数据：

- 创建全新的随机测试用户。
- 给测试用户授予 `developer` 会员等级。
- 先把 `System` 角色临时克隆到测试用户下，再发送聊天请求。
- 不要直接请求 `System` 角色 ID。
- 测试结束后清理测试用户、克隆角色、会话、消息、记忆和场景状态等数据。

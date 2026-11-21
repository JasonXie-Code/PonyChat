# 2026-04-26 Change Log

## 锁分体征与校验

- `galgame/vitals._apply_lock_side_effects` 中情绪互链按字段 `±3` 单轮限幅。
- 体征数值的直连调整不受该钳位。
- 提示词与 `step_02_lock_vitals` 等近期有联动迭代。
- 轻量回归可运行 `Backend/scripts/verify_vitals_emotion_chain.py`。

## 部署版本识别

- `Backend/deploy/deploy_backend_server_usa.py` 写入 `.deploy_revision`。
- `routes/system.py` 启动时读入 deploy token，避免「已更新文件但旧进程未重启」误报新版本。

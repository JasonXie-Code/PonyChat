# 2026-08-13 Change Log

## H618 系统与量产

- 修复桌面显示，限制硬件监看单实例；补充 HEVC 硬件解码修复。
- 默认启用 Companion 无障碍，调整 H618 设备上的 QQ 回复执行与前台安全判断。
- 实施无 Root 量产架构，升级 Runtime AIDL，增加只读诊断及签名保护的服务修复接口。
- 接入 PonyChat 共用产品签名，完善正式 user 固件集成与构建检查。
- 修复默认服务在包更新或签名轮换后的自恢复，增加 APK 与 privileged 权限白名单配对检查。

> 原 `20260813-change-log.md` 随 2026-08-21 的 H618 共享硬件迁移移出；此处按 Git 重建项目历史摘要。跨日的预装签名保留修复归入 2026-08-14。

## Git 依据

按 Git 作者日期（UTC+08:00）归档，同日连续修复在上文合并说明。

- `3fea5d9` 修复 H618 桌面显示并限制监看单实例
- `afa89c1` Enable Companion accessibility by default
- `aad7806` Run QQ replies on H618 device
- `2e0c7b2` 正式修复 H618 HEVC 硬件解码
- `1bc0066` 实施 H618 无 Root 量产架构
- `65caa8c` 接入 PonyChat 共用产品签名
- `968863a` 修复默认服务自恢复并加强量产构建检查
- `9839bf6` 完善 H618 正式固件构建流程

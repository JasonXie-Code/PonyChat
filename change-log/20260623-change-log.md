# 2026-06-23 Change Log

## PonyChat Drive

- 新增后端 `Drive` 路由 `/api/drive`，提供独立的个人网盘接口。
- Drive 登录使用基于 `AUTH_SECRET` 的签名 token，并支持 `PONYCHAT_DRIVE_PASSWORD`、`PONYCHAT_DRIVE_TOKEN_TTL_SECONDS` 和 `PONYCHAT_DRIVE_ROOT` 等环境配置。
- Drive 文件根目录与回收站分离，默认落在 `var/drive/files` 与 `var/drive/.trash`，并用 metadata 记录删除前路径。
- 文件路径统一做规范化和越界检查，拒绝 `..`、`.trash` 和非法文件名，避免通过接口访问 Drive 根目录外的文件。
- Drive 接口覆盖登录、文件列表、文件夹树、回收站列表、新建文件夹、重命名、移入回收站、还原、永久删除、清空回收站、上传和下载。
- 上传支持同名文件自动追加序号，下载接口按路径返回真实文件，文件条目返回类型、mime、大小、子项数量、更新时间和回收站状态。

## Drive 前端与部署

- 新增 `DriveView.vue` 与 `drive.css`，在主站加入 PonyChat Drive 页面和路由入口。
- Drive 页面包含密码登录、文件夹树、面包屑、搜索、排序、详细信息/大图标视图切换、详情窗格和回收站入口。
- Drive 工具栏支持上传文件、上传文件夹、新建文件夹、重命名、下载、删除、还原和永久删除。
- Drive 工作区支持拖拽上传、键盘操作、多选状态、当前目录统计和已选数量提示。
- 新增 Server-USA 静态站点部署说明、部署脚本和 `nginx-ponychat-www.conf`，为 `drive.ponychat.org` 与主站静态资源部署做准备。

## Android 与后端配套

- Android 聊天页、滚动辅助、ViewModel 和主动任务页继续适配新的消息/面板状态。
- 后端注册 Drive 路由，同时调整聊天图片 DAO、会话 DAO、语音缓存、Qwen TTS/CosyVoice/Voice Lab 客户端和 uptime monitor 相关逻辑。
- `test_voice_audio_cache.py` 跟随语音缓存行为更新，保证语音文件缓存与新增路径处理保持一致。


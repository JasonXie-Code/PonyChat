# 状态拟音规则发布

- 发布标记：`local-speech-state-options-20260913-045424-ad7bed6c`
- 运行代码提交：`ad7bed6cc4de5f5dec91f1ca1273400ce93740ff`
- 目标：本机后端；CN、官网健康检查通过，部署标记一致。
- 仅更新 Backend/chat_modules/Prompts.py，生产进程环境确认并发保持20。
- 文件 SHA-256：`eeb042c7cd88c0081f0aed4a95b5a369ed1252cadb103e6a58ab31e2c9e0b30f`
- 旧版代码及数据库备份：`P:\PonyChat\var\local-stack\releases\local-speech-state-options-20260913-045424-ad7bed6c`
- 旧版源文件哈希匹配；数据库备份 quick_check=ok。
- 发布后隔离真实模型 /api/chat HTTP 200，回复及记忆保存成功，未操作生产聊天数据。
- 规则回归198项通过；此前32轮并发对照及三轮重复历史单次测试结果均已留档。
- 未重复进行语音、搜索或20路生产压力测试。

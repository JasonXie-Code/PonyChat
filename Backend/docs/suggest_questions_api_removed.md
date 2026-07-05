# 对话模式「建议问题」生成已下线

**状态**：自 2026-04-24 起，普通对话（`normal`）下的 **建议问题/选项** 生成功能已从产品与后端移除。

## 已删除的后端能力

- **HTTP 接口**：`POST /api/suggest-questions`（原实现于 `Backend/routes/suggestions.py`，整文件已删除）
- **落库回写**：`update_message_suggestions`（`Backend/db/conversations_dao.py` 中已删除；不再由任何路由写入 `messages.suggestions`）

## 未改动（与 Galgame/历史数据兼容）

- **数据库表字段**：`messages`（及历史迁移中的 `suggestions` / `suggestions_status` 等列）**保留不变**，以兼容已存在的历史对话 JSON / 行数据；新对话不再通过 API 更新这些字段
- **Galgame**：消息 JSON 中的 `suggested_options`、分步生成中的选项步等，属于游戏/锁分管线，**不受本次下线影响**

## 相关客户端

- **Android App**：已移除对 `api/suggest-questions` 的调用与底部建议卡片 UI（见同仓库 `Android-App` 提交记录）
- **Web 试玩**（若曾依赖旧静态资源）：以仓库内实际前端代码为准

---

*若需做「彻底删除列」的 DB 迁移，应单独开任务并评估对备份/回滚的影响。*

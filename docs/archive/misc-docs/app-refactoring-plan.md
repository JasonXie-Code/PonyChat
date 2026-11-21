# App.js 模块化重构计划

## 目标
将 2400+ 行的 app.js 拆分为多个功能模块，提高代码可维护性。

## 模块划分

### 1. 核心模块 (js/core/)
- **config.js** ✅ - 配置常量
- **dom.js** - DOM 元素引用
- **state.js** - 全局状态管理
- **settings.js** - 设置管理（保存/加载/重置）

### 2. 聊天模块 (js/chat/)
- **message-ui.js** - 消息渲染（appendMessageToUI, renderChat）
- **chat-api.js** - API 调用（sendMessage 核心逻辑）
- **message-actions.js** - 消息操作（删除、编辑、重新生成）
- **context-manager.js** - 上下文溢出管理
- ~~**suggestions.js** - 建议问题生成~~（已废除，见 `Backend/docs/suggest_questions_api_removed.md`）

### 3. Galgame 模块 (js/galgame/)
- **galgame-core.js** - 核心逻辑（toggle, trigger, perform）
- **galgame-ui.js** - UI 更新（分数、进度条）
- **galgame-loading.js** - 加载动画

### 4. UI 模块 (js/ui/)
- **theme.js** - 主题切换
- **event-handlers.js** - 事件监听器设置
- **think-tags.js** - 思维链处理
- **code-blocks.js** - 代码块处理

### 5. 工具模块 (js/utils/)
- **helpers.js** - 工具函数（stringToColor, scrollToBottom）
- **markdown.js** - Markdown 渲染

## 实施步骤

### Phase 1: 准备阶段
1. ✅ 创建目录结构
2. ✅ 创建 config.js
3. 创建其他核心模块
4. 设置模块导入/导出

### Phase 2: 逐步迁移
1. 迁移独立功能（工具函数）
2. 迁移UI组件
3. 迁移聊天逻辑
4. 迁移Galgame逻辑

### Phase 3: 整合测试
1. 更新 index.html 引入顺序
2. 测试所有功能
3. 修复依赖问题

### Phase 4: 清理
1. 删除旧 app.js 中已迁移的代码
2. 保留主入口逻辑
3. 文档更新

## 注意事项
- 保持向后兼容（window.xxx 全局暴露）
- 使用 ES6 模块（import/export）
- 避免循环依赖
- 保持功能完整性

## 当前状态
- [x] 创建重构计划
- [x] 创建 config.js
- [ ] 创建其他模块
- [ ] 迁移代码
- [ ] 测试验证

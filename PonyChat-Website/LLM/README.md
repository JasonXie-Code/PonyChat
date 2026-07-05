# PonyChat LLM 静态站

`PonyChat-Website/LLM/` 是一个轻量的本地 LLM 聊天前端，面向 OpenAI-compatible 服务。

## 功能

- 通过 `GET /v1/models` 获取当前模型。
- 通过 `POST /v1/chat/completions` 进行流式聊天。
- 支持文本、图片输入、多轮上下文、停止生成、新会话。
- 支持 Markdown、KaTeX 数学公式、代码块复制、思维链折叠与图片预览。
- 前端静态资源自包含：`marked.min.js`、KaTeX JS/CSS 与字体均在 `assets/` 下。

## 期望后端

页面默认与后端同源部署，接口路径为：

| 路径 | 用途 |
| --- | --- |
| `GET /health` | 健康检查与模型状态 |
| `GET /v1/models` | 模型列表 |
| `POST /v1/chat/completions` | OpenAI-compatible 聊天补全，使用 `stream: true` |

请求会发送 `messages`、`temperature`、`top_p`、`max_tokens`、`stream_options.include_usage` 等字段。

## 文件结构

| 路径 | 说明 |
| --- | --- |
| `index.html` | 单页入口 |
| `assets/llm.js` | 聊天、流式解析、渲染和交互逻辑 |
| `assets/llm.css` | 页面样式 |
| `assets/marked.min.js` | Markdown 渲染依赖 |
| `assets/katex/` | KaTeX 与字体 |

## 部署

把 `PonyChat-Website/LLM/` 作为静态目录挂到 LLM 服务同源即可。若放在独立域名或路径下，需要在反向代理中把 `/health`、`/v1/models`、`/v1/chat/completions` 转发到实际推理服务。

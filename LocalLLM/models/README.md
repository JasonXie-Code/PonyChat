# 模型注册表

`models/` 目录不提交到 Git（已在 .gitignore 中排除）。此文件记录本机已有模型信息，方便管理与复现。

## 已有模型

### Qwen3.5-9B（多模态）

| 项目 | 内容 |
|------|------|
| 目录 | `models/Qwen3.5-9B/` |
| 主模型 | `Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf`（约 5.6 GB）|
| 视觉编码器 | `mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf`（约 922 MB）|
| 量化 | Q4_K_M（主模型）/ BF16（mmproj）|
| 建议上下文 | 4096 tokens |
| 多模态 | 支持图像输入，需同时加载 mmproj |
| 来源 | HuggingFace / 手动下载 |

## 使用约定

- 所有 `.gguf` 文件放到对应子目录下，不要放在 `models/` 根目录
- 每个模型一个子目录，目录名格式：`{系列}-{参数量}/`
- `server/config.json` 中的 `model` 和 `mmproj` 字段均相对项目根目录

## 下载新模型

推荐来源：
- [HuggingFace GGUF 搜索](https://huggingface.co/models?library=gguf)
- [bartowski 量化集合](https://huggingface.co/bartowski)
- [TheBloke 量化集合](https://huggingface.co/TheBloke)（较旧，但存量大）

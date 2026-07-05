"""
memory 子包：记忆提取、固化调度、分层摘要、MLP RAG 等。

模块：
  - auto_summarizer : 后台上下文摘要循环
  - consolidator    : 空闲期记忆固化（原 memory_consolidator）
  - extractor       : 单轮记忆提取（原 memory_extractor）
  - scheduler       : 分层记忆日/周/月调度（原 memory_layer_scheduler）
  - mlp_rag         : MLP 知识库混合检索（主流程注入默认关，见 request_context.MLP_RAG_INJECT_ENABLED）
"""

# 测试经验

## 真实模型与原始证据

- [probe_speech_variety.py](../scripts/ops/probe_speech_variety.py)：碧琪/柔柔，四情境、每组四轮。用 `--output` 指定新目录，禁止覆盖已有 results.json。
- [probe_fluttershy_repeated_history.py](../scripts/ops/probe_fluttershy_repeated_history.py)：人为构造三轮相同“唔嗯～”，再请求一次真实回复。默认目录已存在时会拒绝覆盖。
- [smoke_deployed_harness.py](../scripts/ops/smoke_deployed_harness.py)：隔离数据库的真实模型 ASGI /api/chat 验收；不是公网真实用户验收。当前可使用测试环境变量 `PONYCHAT_SMOKE_USERNAME=System`，不要登录生产用户。
- 模型配置和凭据从本地环境读取；只保存输入、系统提示、工具返回及模型原始输出，不输出 API key。
- 既保存未渲染 envelope 和每次生成尝试，也保存最终可见文本；后处理可能删除标点、合并片段，仅看渲染文本会漏信息。

## 多轮比较方法

相同场景、用户原文、角色资料及关系配置更利于比较。后续历史必须使用该组真实回复；不同版本累积历史会分叉，应披露这个限制。每组单样本无法证明统计改善。

“完全不同字符串”不等于“不疲劳”：同时看音节族、音串长度、回应意图、配套动作、是否擅自解除限制。声词增加后曾出现“呣”集中和更长音串，并未明确改善审美疲劳。

## 并发陷阱

`asyncio.gather` 只表示任务并发提交。Harness 另有 `harness_capacity.py` 信号量；独立探针未加载生产环境时可能默认1。显式设置测试用 `PONYCHAT_HARNESS_CONCURRENCY`，在实际调用前确认，记录开始/结束时间与重叠峰值。2026-09-13正式样本峰值8，启动失败批次单列，不能混算。

不要按模糊命令行后缀杀进程：父 PowerShell 的完整命令也可能包含脚本路径。曾因此中断后续编辑。需要停止探针时，精确匹配 python.exe 和独立脚本参数，排除当前进程及祖先进程，并检查编辑确实写入。

## 已踩过的兼容坑

`smoke_deployed_harness.py` 默认用随机合成用户名登录，会被 `Backend/login_control.py` 的白名单拒绝（`Synthetic login failed: HTTP 403`）；这不是后端故障。必须显式设置 `PONYCHAT_SMOKE_USERNAME=System`，脚本随后的断言才有意义。

记忆时间 schema 改为 `type: [string, null]` 后，普通单测通过，真实聊天却在模型调用前500：Harness自有 schema 校验只接受单一类型。现已支持单一类型加null，见 `test_harness_nullable_schema.py`。提示词变化伴随工具参数变化时必须跑真实注册链路。

```powershell
.\.venv\Scripts\python.exe -m pytest Backend/tests/test_autonomous_prompt_skills.py Backend/tests/test_sound_mark_style.py Backend/tests/test_agent_speech_followup_policy.py Backend/tests/test_autonomous_prompt_manuals.py -q
```

测试数量只对应具体命令，不把重叠测试累加成覆盖量；健康检查、真实模型、音频、压力测试分别说明，未做就写未做。

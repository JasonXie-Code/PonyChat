# 普通对话技能整理发布验收

- 发布：`local-skill-audit-20260913-042600-b78b6053`
- 运行代码提交：`b78b60538c79c43d50182026e420906eee56358e`
- 目标：本机 P:/PonyChat 后端；CN 和 USA 保留入口转发。
- 范围：整轮技能整理及配套记忆、图片重发、语言/语音延续、快捷描写修复；image_style 按用户要求保留。
- handoff：只暂存交接请求，不代写目标角色，也不保证目标角色已接话。
- 发布前真实模型验收发现 nullable 工具 schema 不兼容，已支持单一类型与 null 的联合校验并增加回归测试。
- 验证：主回归 357 passed；nullable 针对性 34 passed；补修后相关回归 115 passed，各组有重叠，不累计。
- 发布前后隔离真实模型 ASGI /api/chat 验收通过，HTTP 200、回复和记忆保存成功；未使用生产用户数据，不等同公网真实账号聊天验收。
- 本机、CN IP、官网健康检查通过，deploy_token 一致。
- 21 个发布文件哈希复核一致；备份数据库 PRAGMA quick_check=ok。
- 备份：`P:\PonyChat\var\local-stack\releases\local-skill-audit-20260913-042600-b78b6053`
- 回滚限制：以下旧文件不能逐字节匹配上一部署标记，保留的是上一标记对应 Git 提交的源文件，不能声称完整复原此前运行字节：
  - `Backend/agent_memory/review.py`
  - `Backend/chat_modules/autonomous_contracts.py`
  - `Backend/chat_modules/autonomous_history.py`
  - `Backend/chat_modules/autonomous_shortcuts.py`
  - `Backend/chat_modules/harness_runtime.py`
  - `Backend/tests/test_history_image_tools.py`

## 发布文件 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `Backend/agent_memory/prose.py` | `1a3f408effea9437c5de862e7659ce54f6ec37be73965666c4b5ac203288bd34` |
| `Backend/agent_memory/review.py` | `00190226dee0653075400a642ff93c97e556dd290d65bb8981a903982a944cb9` |
| `Backend/agent_memory/store.py` | `9a346ebeed576d76919da28884eabbba8cad4ab91996e671109fa438392d3284` |
| `Backend/chat_modules/Prompts.py` | `743840313430d5373728b9dbcd158675a7dd3204040eec9738f54e783458fdb3` |
| `Backend/chat_modules/autonomous_contracts.py` | `cbaf539e4340da4352f4a80d3dc751a0a1bece7e1d3cf5f037cccd806628cce4` |
| `Backend/chat_modules/autonomous_delivery.py` | `80f6f513fb8aebec6ad24322f107895e03adcbc618b67ad0af53785fe337866e` |
| `Backend/chat_modules/autonomous_history.py` | `7d3abc3e323d100fe033e93a1a5c8f68f31d5ae8ec755725d2050e64f5ec9187` |
| `Backend/chat_modules/autonomous_normal.py` | `fc233060a02275ebd113a2fcd9865ea10e3c0091bbac2d2348271771ead653d8` |
| `Backend/chat_modules/autonomous_shortcuts.py` | `f348a7cf4720750684cc2074afaca66b200e0c6c74fadca884c54b3fe6dc63a8` |
| `Backend/chat_modules/harness_runtime.py` | `ef8993850eeceb8d28ece5eee473aeff0f249442f4160bb180934c0ce24e3ca0` |
| `Backend/chat_modules/history_image_tools.py` | `9aef0415dcd9f78b0fc08393960d239df7a7455dc8db63e6a745d634ae03c8b8` |
| `Backend/chat_modules/reply_language_state.py` | `5017a3f7887bb3d756a48bc8d74cc918617f9919ccd7635e1b3694eca939e374` |
| `Backend/chat_modules/runtime.py` | `277673d9149a47954a5c47bc8348411fd9de4037b66eec6e76b64738c23f4fa9` |
| `Backend/tests/test_agent_speech_followup_policy.py` | `17d4f3d51191ef4e4774b694cedbf49f1e3dcd7d2082943ab83018914fa96cf3` |
| `Backend/tests/test_autonomous_prompt_manuals.py` | `59367b33a94b40ccba605b751d9c12609dbad7fd7903f106a0b735fc6a9667b8` |
| `Backend/tests/test_history_image_tools.py` | `c0801c1394bc7d7ca4f3c4608ec6389b38466ce8f58648ee321f85c125f1e15e` |
| `Backend/tests/test_memory_prose_rewrite.py` | `74f03420ee3ee518caa9d75fb00cb12b10d0fa6579ccbc074e9ead2b6cab2373` |
| `Backend/tests/test_reply_language_state.py` | `fa3bd0a988ad4a2c88cb23310b59d97a18c479bbf54431c39f94426b3e927c92` |
| `Backend/tests/test_shortcut_target_kinds.py` | `ca44d65600a47c3f50237bf9e961374b1813a77a26333ac20b20aa13e1eb73b7` |
| `Backend/tests/test_sound_mark_style.py` | `938abb7a20261de2c7072ac0c3e51639f8d30dc263ca8758f311dd84bc275943` |
| `Backend/tests/test_harness_nullable_schema.py` | `8e4ad61c1c60cbab67b63fc33b32c70d3ea634ae9487c109005e7ec233a25085` |

详细本机记录：`var/local-stack/skill-audit-deploy/deployment.json`、`smoke-postdeploy.json`。
本次未重复执行搜索、语音和 APK 下载验收。

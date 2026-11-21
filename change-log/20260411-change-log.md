# 2026-04-11 Change Log

## Galgame / 锁分分步与导演

- 导演 JSON 增加 `word_limits`。
- `word_limits` 对本轮选中的 `env`、`body_state`、`thoughts` 分别给出 20～200 目标字数。
- 后端会裁剪并与分步指令字数对齐，缺省回退为 100。
- 移除客户端「游戏内容描写 / 环境·心理描写字数」档位及请求字段 `galgame_scene_length`。
- `nonstream` 固定回退基准。
- `ChatRequest` 不再包含 `galgame_scene_length`，Web 若仍传多余键由 Pydantic 忽略。
- `normalize_director_json` 在 `scene_fields` 未含 `third_party` 时清空 `third_party_hint`。
- `normalize_director_json` 会剔除 `word_limits` 中与 `scene_fields` 不一致的键。
- 导演提示词继续迭代 `scene_fields` 选题原则、必选 `response` + `options`、第三者台词与主角 `response` 区分等。
- 模型若在导演 JSON 顶层误写 `response` / `options` 正文，后端不采用，仍以分步流水线第 7 / 9 步生成为准：`scene.response` / `suggested_options`。

## 锁分口渴 `thirst`

- 自然积累由每轮 `+2` 改为 `+1`。
- 叙事档位与 `galgame.vitals._apply_lock_side_effects` 级联对齐。
- 叙事约为 `40 / 60 / 70 / 80 / 90`。
- 体力 / 意识 / 情绪惩罚延后至 `>=60 / >=80 / >=90`，避免轻度口渴即大幅扣体。
- 死亡线仍为 `thirst>=98`。
- 提示词与 `galgame_hints.py` 已同步。

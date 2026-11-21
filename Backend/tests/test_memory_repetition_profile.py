from __future__ import annotations

from Backend.galgame.memory import (
    _split_memory_agent_payload,
    format_repetition_profile_for_prompt,
    normalize_repetition_profile,
)


def test_splits_structured_memory_agent_payload() -> None:
    raw = {
        "memory_entry": {
            "turn": 108,
            "player_action": "玩家递水。",
            "event": "角色接受照顾。",
        },
        "repetition_profile": {
            "avoid_next_turn": ["不要继续用同一微动作表现害羞。"],
            "overused_surface_patterns": [
                {
                    "pattern": "翅根抖动",
                    "type": "micro_action",
                    "meaning": "羞怯",
                    "cooldown_turns": 4,
                }
            ],
            "semantic_loops": [
                {
                    "pattern": "被称赞后用细微身体反应回避",
                    "meaning": "嘴硬掩饰羞怯",
                    "suggested_alternatives": ["转移话题", "生活化动作"],
                }
            ],
        },
    }

    entry, profile = _split_memory_agent_payload(raw)

    assert entry == raw["memory_entry"]
    assert profile["avoid_next_turn"] == ["不要继续用同一微动作表现害羞。"]
    assert profile["overused_surface_patterns"][0]["cooldown_turns"] == 4
    assert profile["semantic_loops"][0]["suggested_alternatives"] == ["转移话题", "生活化动作"]


def test_legacy_memory_payload_still_works() -> None:
    entry, profile = _split_memory_agent_payload(
        {
            "turn": 12,
            "player_action": "玩家提问。",
            "event": "角色回答。",
        }
    )

    assert entry == {
        "turn": 12,
        "player_action": "玩家提问。",
        "event": "角色回答。",
    }
    assert profile == {}


def test_normalizes_profile_limits_prompt_size() -> None:
    profile = normalize_repetition_profile(
        {
            "avoid_next_turn": [f"规则{i}" for i in range(8)],
            "overused_surface_patterns": [
                {"pattern": f"模式{i}", "cooldown_turns": 99}
                for i in range(12)
            ],
            "semantic_loops": [
                {
                    "pattern": f"节拍{i}",
                    "suggested_alternatives": [f"替代{j}" for j in range(8)],
                }
                for i in range(7)
            ],
        }
    )

    assert len(profile["avoid_next_turn"]) == 5
    assert len(profile["overused_surface_patterns"]) == 8
    assert profile["overused_surface_patterns"][0]["cooldown_turns"] == 8
    assert len(profile["semantic_loops"]) == 5
    assert len(profile["semantic_loops"][0]["suggested_alternatives"]) == 5


def test_formats_repetition_profile_for_next_turn_prompt() -> None:
    text = format_repetition_profile_for_prompt(
        {
            "repetition_profile": {
                "avoid_next_turn": ["不要继续用翅根抖表达害羞。"],
                "overused_surface_patterns": [
                    {
                        "pattern": "翅根抖动",
                        "meaning": "羞怯或紧张",
                        "cooldown_turns": 4,
                    }
                ],
                "semantic_loops": [
                    {
                        "pattern": "被温柔称赞后立刻回避",
                        "meaning": "嘴硬掩饰羞怯",
                        "suggested_alternatives": ["短促台词", "转移话题"],
                    }
                ],
            }
        }
    )

    assert "上一轮记忆 Agent 去重档案" in text
    assert "不要继续用翅根抖表达害羞" in text
    assert "被温柔称赞后立刻回避" in text
    assert "短促台词" in text

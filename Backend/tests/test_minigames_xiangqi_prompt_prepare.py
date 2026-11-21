from __future__ import annotations

from Backend.routes import minigames


def test_xiangqi_execute_normalize_clears_move_payload_for_chat_only():
    result = minigames._normalize_execute_result(
        {
            "schema_version": 2,
            "action": "chat_only",
            "selected_move_id": "c1",
            "character_reply": {"text": "等你走完我再下。"},
            "move": {
                "from": {"x": 0, "y": 0},
                "to": {"x": 1, "y": 0},
                "piece": "炮",
            },
        }
    )

    assert result["selected_move_id"] is None
    assert result["move"] is None
    assert result["character_reply"]["text"] == "等你走完我再下。"


def test_xiangqi_execute_normalize_clears_move_payload_for_resign():
    result = minigames._normalize_execute_result(
        {
            "schema_version": 2,
            "action": "Resign",
            "selected_move_id": "c1",
            "character_reply": {"text": "好吧，我认输。"},
            "move": {
                "from": {"x": 0, "y": 0},
                "to": {"x": 1, "y": 0},
                "piece": "炮",
            },
        }
    )

    assert result["action"] == "resign"
    assert result["selected_move_id"] is None
    assert result["move"] is None
    assert result["character_reply"]["text"] == "好吧，我认输。"


def test_xiangqi_prepare_card_normalizes_power_and_play_style():
    fallback = minigames._fallback_prepare(
        minigames.XiangqiPrepareRequest(character_name="紫悦", user_name="Jason")
    )

    card = minigames._normalize_prepare_card(
        {
            "power_tier": "advanced",
            "opening_lines": ["我先冲个小兵！"],
            "chess_style": {
                "play_style": "调皮型",
                "skill_level": 9,
                "calculation_depth": 4,
                "risk_tolerance": 5,
                "attack_bias": 5,
                "defense_bias": 2,
                "trade_bias": 3,
                "blunder_tier": 0,
            },
        },
        fallback,
    )

    assert card["power_tier"] == "advanced"
    assert card["chess_style"]["play_style"] == "playful"
    assert card["chess_style"]["play_style_label"] == "调皮型"
    assert card["execution_policy"]["prefer_candidate_tags"][:4] == [
        "best",
        "active",
        "good",
        "random_safe",
    ]
    assert card["execution_policy"]["user_request_affinity"] == 3
    assert "opening_lines" not in card

    affinity_card = minigames._normalize_prepare_card(
        {
            "power_tier": "junior",
            "execution_policy": {"user_request_affinity": 5},
        },
        fallback,
    )
    assert affinity_card["execution_policy"]["user_request_affinity"] == 5


def test_xiangqi_prepare_prompt_explains_play_style_and_candidate_tags():
    req = minigames.XiangqiPrepareRequest(
        character_name="紫悦",
        user_name="Jason",
        player_side="red",
        game_memory={
            "has_previous_game": True,
            "latest_game": {
                "summary": "上一局角色输了，有点不服气。",
                "capture_stats": {"user_captured_character": {"by_kind": {"soldier": 1}}},
            },
        },
    )
    prompt = "\n".join(
        message["content"]
        for message in minigames._prepare_prompt(
            req,
            {
                "character_profile": "认真、好学、爱研究。",
            },
        )
    )

    assert "play_style 只能是 attacking、cautious、playful、textbook" in prompt
    assert "attacking=进攻型" in prompt
    assert "book、best、solid、active、good、risky、novelty、random_safe、random、blunder" in prompt
    assert minigames._candidate_tags_for_policy("novice", "playful")[:3] == [
        "novelty",
        "random_safe",
        "random",
    ]
    assert minigames._candidate_tags_for_policy("junior", "playful")[:3] == [
        "novelty",
        "random_safe",
        "good",
    ]
    assert "user_request_affinity 表示角色愿不愿意听用户的走棋建议" in prompt
    assert "不要输出 role_brief、relationship、speech、reaction、memory_hooks、开场白" in prompt
    assert "温柔、照顾型、亲近用户、调皮想逗用户开心的角色通常 4-5" in prompt
    assert "好胜、强势、自信、进攻型或想证明自己的角色通常 0-2" in prompt
    assert "power_tier 和 play_style 必须直接由角色稳定设定判断" in prompt
    assert "后端不会用角色名单或代码规则替你纠正" in prompt
    assert "新手不等于完全不会规则" in prompt
    assert "派对型、恶作剧型、强烈追求即时快乐" in prompt
    assert "novice + playful" in prompt
    assert "16人格是辅助证据" in prompt
    assert "角色正文强证据优先级高于 MBTI" in prompt
    assert "数百/上千岁寿命" in prompt
    assert "【角色稳定设定，仅用于判断象棋参数】" in prompt
    assert "【最近象棋对局记忆，仅用于参数倾向，不是本局棋盘事实】" in prompt
    assert "latest_game" in prompt
    assert "只能用它影响本次棋局参数上的谨慎/好胜/冒险倾向" in prompt
    assert "上一局角色输了，有点不服气" in prompt
    assert "字段结构模板如下，所有字段都必须出现" in prompt
    assert '"schema_version": 2' in prompt
    assert '"chess_style"' in prompt
    assert '"execution_policy"' in prompt
    assert '"role_brief"' not in prompt
    assert '"relationship"' not in prompt
    assert '"speech"' not in prompt
    assert '"reaction"' not in prompt
    assert '"memory_hooks"' not in prompt
    assert "不要照抄占位文字或数字" in prompt
    assert '"opening_lines"' not in prompt


def test_xiangqi_prepare_card_drops_role_context_fields():
    fallback = minigames._fallback_prepare(
        minigames.XiangqiPrepareRequest(character_name="玉琪派", user_name="Jason")
    )

    missing = minigames._normalize_prepare_card({}, fallback)
    provided = minigames._normalize_prepare_card(
        {
            "role_brief": "玉琪派安静害羞，和用户最近一直在轻声互动。" * 20,
            "xiangqi_role_context": "旧别名不应保留",
            "relationship": {"warmth": 5},
            "speech": {"frequency": 5},
            "reaction": {"on_loss": "旧反应摘要"},
            "memory_hooks": [{"key": "old"}],
        },
        fallback,
    )

    assert "role_brief" not in missing
    assert "role_brief" not in provided
    assert "xiangqi_role_context" not in provided
    assert "relationship" not in provided
    assert "speech" not in provided
    assert "reaction" not in provided
    assert "memory_hooks" not in provided


def test_xiangqi_execute_prompt_promotes_current_user_stated_recall_answer():
    req = minigames.XiangqiExecuteRequest(
        character_name="珍奇",
        user_name="Jason",
        player_side="red",
        turn="red",
        user_message="你还记得A吗？别只说记得，要说出小铃兰书签口令。",
        game_memory={
            "latest_game": {
                "summary": "旧局 A 是精致晚餐口令，赌注是写短诗。",
            }
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【本轮用户明示事实锚｜高于旧记忆】" in prompt
    assert "小铃兰书签口令" in prompt
    assert "这些原话高于跨局象棋记忆、普通对话上下文和角色早先错答" in prompt
    assert "不得说它“就是/也就是/是”另一个旧短语" in prompt
    assert "不得主动补出旧口令、旧赌注或角色刚才错答" in prompt


def test_xiangqi_execute_prompt_requires_confirming_current_user_abc_statement():
    req = minigames.XiangqiExecuteRequest(
        character_name="珍奇",
        user_name="Jason",
        player_side="red",
        turn="red",
        user_message="先把A和B说清楚：闲聊内容A是小铃兰书签口令，赌注B是输的人给赢家写一句胜利留言。",
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【本轮用户明示事实锚｜高于旧记忆】" in prompt
    assert "用户本轮原话：先把A和B说清楚" in prompt
    assert "本轮可见文本必须确认用户原话中的 A/B/C、口令或赌注关键内容" in prompt
    assert "不得只重复开场白、催用户走棋、泛称“我记住了”" in prompt
    assert "不得跳过用户刚说的 A/B/C" in prompt

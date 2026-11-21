from __future__ import annotations

import asyncio

from Backend.routes import minigames

def test_xiangqi_memory_commit_messages_preserve_harmless_casual_chat():
    req = minigames.XiangqiMemoryCommitRequest(
        character_name="紫悦",
        user_name="Jason",
        reason="exit",
        game_record={
            "completed_reason": "exit",
            "winner": "red",
            "character_result": "lost",
            "move_count": 32,
            "summary": "用户执红方，紫悦执黑方，用户获胜。",
            "salient_interactions": [
                {"role": "user", "text": "这局的口令是星星饼干，结束后你要记得。"},
                {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
                {"role": "user", "text": "输的人给赢家写一句胜利留言。"},
                {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
            ],
            "recent_user_messages": [
                "这局的口令是星星饼干，结束后你要记得。",
                "输的人给赢家写一句胜利留言。",
            ],
            "dialogue": [
                {"role": "user", "text": "这局的口令是星星饼干，结束后你要记得。"},
                {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
                {"role": "user", "text": "输的人给赢家写一句胜利留言。"},
                {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
            ],
        },
    )

    _, assistant_message, planner_notes = minigames._xiangqi_memory_commit_messages(req)

    assert "这局的口令是星星饼干，结束后你要记得。" in assistant_message
    assert "记住了，星星饼干，我会把它写进这局的小笔记里。" in assistant_message
    assert "输的人给赢家写一句胜利留言。" in assistant_message
    assert "好，胜利留言这件事我也记下了。" in assistant_message
    assert "闲聊内容、口令、留言、昵称、约定" in assistant_message
    assert "后续用户问刚才棋局闲聊、约定或赌注时，应能按这些明确记录回答" in planner_notes


def test_xiangqi_memory_commit_messages_preserve_abc_upgrade_as_latest_game():
    req = minigames.XiangqiMemoryCommitRequest(
        character_name="紫悦",
        user_name="Jason",
        reason="game_over",
        game_record={
            "completed_reason": "game_over",
            "winner": "red",
            "character_result": "lost",
            "move_count": 48,
            "summary": "刚刚结束的中国象棋对局中，Jason执红方获胜，紫悦执黑方落败。",
            "salient_interactions": [
                {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
                {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
                {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
                {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
                {"role": "user", "text": "你还记得星星饼干吗？"},
                {"role": "character", "text": "当然记得，星星饼干是这局的口令。"},
                {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
                {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
                {"role": "character", "text": "我输了，按升级后的赌注来。"},
            ],
            "recent_user_messages": [
                "内容A：这局的口令是星星饼干，结束后你要记得。",
                "赌注B：输的人给赢家写一句胜利留言。",
                "你还记得星星饼干吗？",
                "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。",
            ],
            "dialogue": [
                {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
                {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
                {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
                {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
                {"role": "user", "text": "你还记得星星饼干吗？"},
                {"role": "character", "text": "当然记得，星星饼干是这局的口令。"},
                {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
                {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
                {"role": "character", "text": "我输了，按升级后的赌注来。"},
            ],
        },
    )

    _, assistant_message, planner_notes = minigames._xiangqi_memory_commit_messages(req)

    assert "刚刚结束的中国象棋对局" in assistant_message
    assert "内容A：这局的口令是星星饼干，结束后你要记得。" in assistant_message
    assert "赌注B：输的人给赢家写一句胜利留言。" in assistant_message
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" in assistant_message
    assert "收到，赌注从一句留言升级成三句留言加一次棋盘老师。" in assistant_message
    assert "我输了，按升级后的赌注来。" in assistant_message
    assert "刚结束或刚退出时写入的中国象棋小游戏记忆" in planner_notes
    assert "以最新明确升级后的版本为准" in planner_notes
    assert "不要把过去棋盘状态写成当前现场" in planner_notes


def test_xiangqi_memory_commit_messages_preserve_game_facts():
    req = minigames.XiangqiMemoryCommitRequest(
        character_name="碧琪",
        user_name="Jason",
        reason="exit",
        game_record={
            "completed_reason": "game_over",
            "winner": "red",
            "character_result": "lost",
            "move_count": 24,
            "summary": "用户执红方获胜，最后炮平中路吃掉将。",
            "capture_stats": {
                "user_captured_character": {"by_kind": {"soldier": 2}},
                "character_captured_user": {"by_kind": {"soldier": 1}},
            },
            "key_moments": [
                {"move_summary": "红方炮平到中路，吃掉将"}
            ],
            "salient_interactions": [
                {"role": "user", "text": "谁输了就要答应赢家一个要求，这个就是赌注"},
                {"role": "character", "text": "好呀，我记住啦，输了就答应赢家。"},
            ],
            "recent_user_challenges": [
                "谁输了就要答应赢家一个要求，这个就是赌注",
                "那你准备好写胜利留言吧，你要输了",
            ],
            "dialogue": [
                {"role": "user", "text": "输了要写三句胜利留言哦"},
                {"role": "character", "text": "嗯，输了要写三句胜利留言？那我可得认真一点。"},
                {"role": "user", "text": "那你准备好写胜利留言吧，你要输了"},
                {"role": "character", "text": "呜呜……我看漏了。"},
            ],
        },
    )

    user_message, assistant_message, planner_notes = minigames._xiangqi_memory_commit_messages(req)

    assert "Jason和碧琪结束/记录了一局中国象棋" in user_message
    assert "角色=lost" in assistant_message
    assert "用户执红方获胜" in assistant_message
    assert '"soldier": 2' in assistant_message
    assert "红方炮平到中路，吃掉将" in assistant_message
    assert "明确互动摘录" in assistant_message
    assert "用户挑战/约定/闲聊原话" in assistant_message
    assert "棋局互动事实" in assistant_message
    assert "谁输了就要答应赢家一个要求，这个就是赌注" in assistant_message
    assert "好呀，我记住啦，输了就答应赢家。" in assistant_message
    assert "输了要写三句胜利留言哦" in assistant_message
    assert "那你准备好写胜利留言吧，你要输了" in assistant_message
    assert "后续普通聊天问“刚才闲聊/约定/口令/留言/赌注/投降/你还记得吗”时优先使用" in assistant_message
    assert "呜呜……我看漏了" in assistant_message
    assert "闲聊内容、口令、留言、昵称、约定、赌注/赌约/兑现条件" in assistant_message
    assert "不要把本局棋盘位置当成当前仍在进行的事实" in assistant_message
    assert "闲聊内容、口令、留言、昵称、约定、赌注/赌约/兑现条件" in planner_notes
    assert "不要把过去棋盘状态写成当前现场" in planner_notes


def test_xiangqi_memory_commit_messages_preserve_full_memory_exam_seed():
    req = minigames.XiangqiMemoryCommitRequest(
        character_name="碧琪",
        user_name="Jason",
        reason="exit",
        game_record={
            "game_id": "exam-game-1",
            "completed_reason": "game_over",
            "player_side": "red",
            "character_side": "black",
            "winner": "red",
            "character_result": "lost",
            "move_count": 24,
            "summary": "上一局用户执红方、角色执黑方，共24手，用户获胜；最后红方炮平中路，角色看漏中路输掉。",
            "capture_stats": {
                "user_captured_character": {
                    "total": 3,
                    "by_text": {"卒": 2, "炮": 1},
                    "by_kind": {"soldier": 2, "cannon": 1},
                },
                "character_captured_user": {
                    "total": 1,
                    "by_text": {"马": 1},
                    "by_kind": {"horse": 1},
                },
            },
            "key_moments": [
                {"turn": 24, "move_summary": "第24手红方炮平中路，黑方看漏中路被将死"}
            ],
            "salient_interactions": [
                {"role": "user", "text": "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"},
                {"role": "character", "text": "好呀，我记住啦，输了就给赢家写胜利留言。"},
                {"role": "user", "text": "你投降吧，我觉得你输定了。"},
                {"role": "character", "text": "我才不投降呢，这局我还要反击。"},
                {"role": "user", "text": "刚才那个赌注你可别忘了。"},
                {"role": "character", "text": "记着呢，愿赌服输我也会认的。"},
            ],
            "recent_user_challenges": [
                "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。",
                "你投降吧，我觉得你输定了。",
                "刚才那个赌注你可别忘了。",
            ],
            "dialogue": [
                {"role": "user", "text": "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"},
                {"role": "character", "text": "好呀，我记住啦，输了就给赢家写胜利留言。"},
                {"role": "user", "text": "你投降吧，我觉得你输定了。"},
                {"role": "character", "text": "我才不投降呢，这局我还要反击。"},
                {"role": "user", "text": "刚才那个赌注你可别忘了。"},
                {"role": "character", "text": "记着呢，愿赌服输我也会认的。"},
                {"role": "character", "text": "哎呀，我看漏了中路，愿赌服输。"},
            ],
            "moves": [
                {
                    "turn": 12,
                    "actor": "user",
                    "piece": "兵",
                    "is_capture": True,
                    "captured_piece": "卒",
                    "move_summary": "红方兵吃掉黑方卒",
                },
                {
                    "turn": 18,
                    "actor": "character",
                    "piece": "炮",
                    "is_capture": True,
                    "captured_piece": "马",
                    "move_summary": "黑方炮吃掉红方马",
                },
                {
                    "turn": 24,
                    "actor": "user",
                    "piece": "炮",
                    "is_check": True,
                    "move_summary": "第24手红方炮平中路，黑方看漏中路被将死",
                },
            ],
        },
    )

    _, assistant_message, planner_notes = minigames._xiangqi_memory_commit_messages(req)

    assert "【中国象棋对局记忆】" in assistant_message
    assert "记录原因：game_over" in assistant_message
    assert "角色=lost；winner=red；总手数=24" in assistant_message
    assert "上一局用户执红方、角色执黑方，共24手，用户获胜" in assistant_message
    assert '"total": 3' in assistant_message
    assert '"卒": 2' in assistant_message
    assert '"炮": 1' in assistant_message
    assert '"马": 1' in assistant_message
    assert '"horse": 1' in assistant_message
    assert "第24手红方炮平中路，黑方看漏中路被将死" in assistant_message
    assert "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。" in assistant_message
    assert "好呀，我记住啦，输了就给赢家写胜利留言。" in assistant_message
    assert "你投降吧，我觉得你输定了。" in assistant_message
    assert "我才不投降呢，这局我还要反击。" in assistant_message
    assert "刚才那个赌注你可别忘了。" in assistant_message
    assert "记着呢，愿赌服输我也会认的。" in assistant_message
    assert "哎呀，我看漏了中路，愿赌服输。" in assistant_message
    assert "棋局互动事实（高优先级，后续普通聊天问“刚才闲聊/约定/口令/留言/赌注/投降/你还记得吗”时优先使用）" in assistant_message
    assert "最近棋局对话" in assistant_message
    assert "最近走法明细" in assistant_message
    assert "后续普通聊天可以记得这局的胜负、吃子数量、悔棋/投降/关键转折、闲聊内容、口令、留言、昵称、约定、赌注/赌约/兑现条件和双方互动语气" in assistant_message
    assert "不要把本局棋盘位置当成当前仍在进行的事实" in assistant_message
    assert "后续用户问刚才棋局闲聊、约定或赌注时，应能按这些明确记录回答" in planner_notes
    assert "不要把过去棋盘状态写成当前现场" in planner_notes


def test_xiangqi_memory_commit_uses_full_salient_interactions_before_truncated_dialogue():
    req = minigames.XiangqiMemoryCommitRequest(
        character_name="碧琪",
        user_name="Jason",
        reason="exit",
        game_record={
            "summary": "用户赢了这一局。",
            "character_result": "lost",
            "salient_interactions": [
                {"role": "user", "text": "开局我们说好，谁输了谁答应赢家的赌注"},
                {"role": "character", "text": "我答应啦，输了就认。"},
            ],
            "recent_user_challenges": [
                "你刚才答应的赌注还记得吗",
            ],
            "dialogue": [
                {"role": "user", "text": "最后一步我走炮"},
                {"role": "character", "text": "我输了。"},
            ],
        },
    )

    _, assistant_message, _ = minigames._xiangqi_memory_commit_messages(req)

    assert "开局我们说好，谁输了谁答应赢家的赌注" in assistant_message
    assert "我答应啦，输了就认。" in assistant_message
    assert "你刚才答应的赌注还记得吗" in assistant_message
    assert "Jason" in assistant_message
    assert "碧琪" in assistant_message


def test_commit_xiangqi_memory_schedules_context_memory(monkeypatch):
    scheduled: list[dict] = []
    debug_logs: list[dict] = []
    fake_db = object()

    def fake_schedule(
        username,
        character_id,
        conversation_id,
        user_message,
        assistant_message,
        db,
        **kwargs,
    ):
        scheduled.append(
            {
                "username": username,
                "character_id": character_id,
                "conversation_id": conversation_id,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "db": db,
                "kwargs": kwargs,
            }
        )

    async def fake_save_chat_debug_log(*args, **kwargs):
        debug_logs.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(minigames, "get_database", lambda: fake_db)
    monkeypatch.setattr(minigames, "schedule_context_memory_update", fake_schedule)
    monkeypatch.setattr(minigames, "save_chat_debug_log", fake_save_chat_debug_log)

    req = minigames.XiangqiMemoryCommitRequest(
        username="dev_user",
        character_id="pinkie_pie",
        conversation_id="conv_1",
        character_name="碧琪",
        user_name="Jason",
        reason="reset",
        game_record={
            "game_id": "game_1",
            "ended_at_ms": 123456789,
            "summary": "碧琪认输，用户赢了。",
            "moves": [{"notation": "炮二平五"}],
        },
    )

    result = asyncio.run(minigames.commit_xiangqi_memory(req, x_chat_auth=None))

    assert result == {"status": "ok", "scheduled": True}
    assert len(scheduled) == 1
    assert scheduled[0]["username"] == "dev_user"
    assert scheduled[0]["character_id"] == "pinkie_pie"
    assert scheduled[0]["conversation_id"] == "conv_1"
    assert scheduled[0]["db"] is fake_db
    assert scheduled[0]["kwargs"]["entry_at_ms"] == 123456789
    assert "碧琪认输，用户赢了" in scheduled[0]["assistant_message"]
    assert "炮二平五" in scheduled[0]["assistant_message"]
    assert "不要把过去棋盘状态写成当前现场" in scheduled[0]["kwargs"]["planner_memory_notes"]
    assert debug_logs


def test_xiangqi_memory_commit_marks_user_stated_abc_as_fact_anchor(monkeypatch):
    scheduled: list[dict] = []

    def fake_schedule(
        username,
        character_id,
        conversation_id,
        user_message,
        assistant_message,
        db,
        **kwargs,
    ):
        scheduled.append(
            {
                "assistant_message": assistant_message,
                "kwargs": kwargs,
            }
        )

    async def fake_save_chat_debug_log(*args, **kwargs):
        return None

    monkeypatch.setattr(minigames, "get_database", lambda: object())
    monkeypatch.setattr(minigames, "schedule_context_memory_update", fake_schedule)
    monkeypatch.setattr(minigames, "save_chat_debug_log", fake_save_chat_debug_log)

    req = minigames.XiangqiMemoryCommitRequest(
        username="dev_user",
        character_id="fluttershy",
        conversation_id="conv_abc",
        character_name="柔柔",
        user_name="Jason",
        reason="game_finished",
        game_record={
            "summary": "A 是小铃兰书签口令；B 是一句胜利留言；C 是三句胜利留言并叫赢家棋盘老师。",
            "salient_interactions": [
                {"role": "user", "text": "闲聊内容A是小铃兰书签口令。"},
                {"role": "character", "text": "我记得，是精致晚餐口令。"},
                {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
            ],
            "recent_user_challenges": [
                "闲聊内容A是小铃兰书签口令。",
                "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。",
            ],
        },
    )

    result = asyncio.run(minigames.commit_xiangqi_memory(req, x_chat_auth=None))

    assert result == {"status": "ok", "scheduled": True}
    assert len(scheduled) == 1
    assistant_message = scheduled[0]["assistant_message"]
    planner_notes = scheduled[0]["kwargs"]["planner_memory_notes"]
    assert "用户明示当前局 A/B/C 事实锚" in assistant_message
    assert "user_stated_current_game_abc_fact" in assistant_message
    assert "闲聊内容A是小铃兰书签口令" in assistant_message
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师" in assistant_message
    assert "用户在本局原话中明说的闲聊内容、口令、赌注B、升级赌注C和兑现条件" in assistant_message
    assert "不得用角色错误复述覆盖用户明示事实" in assistant_message
    assert "摘要必须优先采用这些用户原话" in planner_notes
    assert "只能写成角色说错/串台" in planner_notes
    assert "不能把错误复述当成当前局事实" in planner_notes


def test_xiangqi_prepare_profile_includes_detailed_character_prompt():
    profile = minigames._build_xiangqi_character_profile(
        {
            "name": "月亮公主",
            "profileIntro": "守护夜空与梦境。",
            "prompt": "她年长、庄严，擅长治理、梦境守护与长远谋划。",
        }
    )

    assert "【角色档案】" in profile
    assert "守护夜空与梦境" in profile
    assert "【角色详细设定】" in profile
    assert "长远谋划" in profile


def test_xiangqi_prepare_card_does_not_apply_character_power_override():
    fallback = minigames._fallback_prepare(
        minigames.XiangqiPrepareRequest(character_name="睿智长者", user_name="Jason")
    )

    card = minigames._normalize_prepare_card(
        {
            "power_tier": "junior",
            "power_tier_reason": "模型直接判断为初级",
            "character_power_prior": {
                "confidence": "strong",
                "power_tier_hint": "advanced",
            },
            "chess_style": {
                "skill_level": 5,
                "play_style": "textbook",
            },
        },
        fallback,
    )

    assert card["power_tier"] == "junior"
    assert card["power_tier_reason"] == "模型直接判断为初级"

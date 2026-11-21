from __future__ import annotations

import asyncio
from types import SimpleNamespace

from Backend.routes import minigames


def test_force_chess_payload_no_thinking_removes_reasoning_controls():
    payload = {
        "model": "fake-model",
        "messages": [],
        "enable_thinking": True,
        "thinking": {"type": "enabled"},
        "thinking_budget": 8192,
        "reasoning_effort": "high",
        "reasoning": {"effort": "high"},
    }

    result = minigames._force_chess_payload_no_thinking(payload)

    assert result is payload
    assert payload["enable_thinking"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert "thinking_budget" not in payload
    assert "reasoning_effort" not in payload
    assert "reasoning" not in payload


def test_xiangqi_llm_steps_charge_one_membership_credit(monkeypatch):
    calls: list[dict] = []
    disabled_policy = SimpleNamespace(
        thinking_type="disabled",
        reasoning_effort=None,
        effort=None,
        deepseek_v4_api_reasoning_effort=None,
    )

    monkeypatch.setattr(
        minigames,
        "_chess_model_no_thinking",
        lambda: (
            {"model_name": "fake-model", "endpoint": "https://example.invalid", "enable_thinking": False},
            "fake-model",
            disabled_policy,
        ),
    )

    async def fake_call_llm_payload(payload, active_model, **kwargs):
        calls.append({"payload": payload, "active_model": active_model, "kwargs": kwargs})
        if kwargs["chat_debug_request"]["stage"] == "XIANGQI_PREPARE_REQUEST":
            text = '{"schema_version": 2, "power_tier": "junior"}'
        else:
            text = '{"schema_version": 2, "action": "chat_only", "character_reply": {"text": "我看一下。"}}'
        return SimpleNamespace(text=text)

    monkeypatch.setattr(minigames, "call_llm_payload", fake_call_llm_payload)

    for step in ("prepare", "execute"):
        asyncio.run(
            minigames._call_chess_llm(
                username="Jason",
                character_id="twilight",
                step=step,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=64,
                temperature=0.3,
            )
        )

    assert [call["kwargs"]["chat_debug_request"]["stage"] for call in calls] == [
        "XIANGQI_PREPARE_REQUEST",
        "XIANGQI_EXECUTE_REQUEST",
    ]
    for call in calls:
        payload = call["payload"]
        assert payload["enable_thinking"] is False
        assert payload["thinking"] == {"type": "disabled"}
        assert "thinking_budget" not in payload
        assert "reasoning_effort" not in payload
        assert "reasoning" not in payload
        assert call["active_model"]["enable_thinking"] is False

        kwargs = call["kwargs"]
        policy = kwargs["reasoning_policy"]
        assert policy.thinking_type == "disabled"
        assert policy.reasoning_effort is None
        assert policy.effort is None
        assert policy.deepseek_v4_api_reasoning_effort is None
        assert kwargs["record_usage"] == "main"
        assert kwargs["usage_meter_username"] == "Jason"
        assert kwargs["llm_api_calls"] == 1
        assert kwargs["charge_membership_chat_quota"] is True


def test_xiangqi_guest_llm_steps_do_not_charge_membership_credit(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        minigames,
        "_chess_model_no_thinking",
        lambda: ({"model_name": "fake-model", "endpoint": "https://example.invalid"}, "fake-model", object()),
    )

    async def fake_call_llm_payload(payload, active_model, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text='{"schema_version": 2}')

    monkeypatch.setattr(minigames, "call_llm_payload", fake_call_llm_payload)

    asyncio.run(
        minigames._call_chess_llm(
            username="",
            character_id="twilight",
            step="prepare",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=64,
            temperature=0.3,
        )
    )

    assert calls[0]["record_usage"] == "none"
    assert calls[0]["usage_meter_username"] is None
    assert calls[0]["llm_api_calls"] == 1
    assert calls[0]["charge_membership_chat_quota"] is False


def test_xiangqi_execute_prompt_guides_characterized_non_repetitive_replies():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="紫色的聪明",
        turn="black",
        user_message="你觉得你能赢吗",
        entry_card={
            "power_tier": "junior",
            "speech": {"frequency": 3, "playfulness": 2},
            "relationship": {"familiarity": 4, "warmth": 4},
            "execution_policy": {"user_request_affinity": 4},
        },
        dialogue_history=[
            {"role": "user", "text": "下一步，你把你的车收回去"},
            {
                "role": "character",
                "text": "你先走完这步我再考虑吧。",
                "近期重复词": ["我再考虑"],
            },
        ],
        move_history=[
            {
                "actor": "user",
                "side": "red",
                "move_summary": "红方兵往前走，吃掉卒",
                "reply_hint": "兵往前走，吃掉卒",
            },
            {
                "actor": "character",
                "side": "black",
                "move_summary": "黑方车往后撤退",
                "reply_text": "我把车往后撤一下，顺便盯一下你的马。",
                "近期重复词": ["顺便盯"],
            },
        ],
        move_candidates=[
            {
                "id": "c1",
                "quality_tag": "good",
                "move_summary": "黑方车横着挪一下",
                "reply_hint": "车横着挪一下",
            }
        ],
    )

    messages = minigames._execute_prompt(req)
    system_prompt = messages[0]["content"]
    full_prompt = "\n".join(message["content"] for message in messages)

    for hardcoded_role_term in ("碧琪", "珍奇", "柔柔", "亲爱的"):
        assert hardcoded_role_term not in system_prompt

    assert "角色说棋要先像这个角色本人" in system_prompt
    assert "【最高优先级：反模板挑战】" in system_prompt
    assert "角色可见台词绝对不要承认被用户发现、猜到、看穿" in system_prompt
    assert "不要说用户说得对" in system_prompt
    assert "不要声明本轮不说某词或换个花样" in system_prompt
    assert "本轮也不要写“套路”或“中路”" in system_prompt
    assert "需要表达位置时改说“五路”“这条线”“棋面中央”" in system_prompt
    assert "第一可见句必须直接用当前角色口吻落到棋子动作" in system_prompt
    assert "从角色自己的语气、生活领域、动作习惯或关系态度里选一个开头" in system_prompt
    assert "活泼夸张型可用声音、小剧场或庆祝动作" in system_prompt
    assert "审美设计型可用线条、搭配、质感或剪裁动作" in system_prompt
    assert "温柔照看型可用轻声、小心或照看的动作" in system_prompt
    assert "称呼或口头禅只有最近没有反复使用时才可加" in system_prompt
    assert "不能当每轮固定前缀" in system_prompt
    assert "本轮可见文本必须含有来自当前角色设定的具体标记" in system_prompt
    assert "称呼/口头禅只能加分，不能作为唯一角色标记" in system_prompt
    assert "不要只靠重复一个称呼证明角色风味" in system_prompt
    assert "【最高优先级：普通走棋角色化】" in system_prompt
    assert "不能只报“棋子+方向+通用理由”" in system_prompt
    assert "如果 entry_card、角色名或普通角色上下文中出现 careful/cautious/gentle/supportive/defensive" in system_prompt
    assert "只加这些词再接“照看棋盘中央/棋子之间能有个照应/不会太散/留出空间/试探阵脚”仍不合格" in system_prompt
    assert "必须把理由改成角色自己的顾虑、安抚或生活经验" in system_prompt
    assert '只要用户提示里的 entry_card JSON 出现 "play_style": "careful"' in system_prompt
    assert "reaction_text 或 move_reason_text 必须字面包含上述照看信号之一" in system_prompt
    assert "不要只写“嗯……我看看/炮动一下/靠中间一点”" in system_prompt
    assert '只要用户提示里的 entry_card JSON 出现 "play_style": "playful"' in system_prompt
    assert "具体玩笑/庆祝/热闹/点心/糖果/彩带/小剧场/惊喜/蹦跳/派对式动作" in system_prompt
    assert "只写“哇/那我/看看你的阵线/我把炮挪到中间”不合格" in system_prompt
    assert "称呼、口头禅、语气词不能当唯一角色标记" in system_prompt
    assert "普通角色上下文含审美、设计、服装、时尚、手艺、优雅、华丽、品质、风格、搭配等信号" in system_prompt
    assert "不能写成“打开边路/稳住阵脚/看看阵线/把炮移到中路”这种棋盘通用句" in system_prompt
    assert "反模板挑战或用户点名要求换说法时" in system_prompt
    assert "不能只用“阵脚/棋面/位置/动一动/收拢”这类棋盘通用词充当角色风味" in system_prompt
    assert "本轮必须至少带一个该领域的具体动作、物件或感官词" in system_prompt
    assert "当前角色设定明显是温柔照看、胆怯谨慎或低压安抚型" in system_prompt
    assert "不要先说“啊”、不要先回应用户是否猜中" in system_prompt
    assert "把“棋规事实”翻译成角色自己的动作、比喻、情绪或生活经验" in system_prompt
    assert "至少要有一处来自角色设定的可感知口吻" in system_prompt
    assert "这些只是转译方法，不是固定模板；禁止每轮套同一个比喻" in system_prompt
    assert "活泼庆祝型回复应更像突发奇想、热闹动作或夸张小剧场" in system_prompt
    assert "庆祝物、点心、蹦跳、突然冒出的玩笑" in system_prompt
    assert "审美设计型回复应更像品味、线条、搭配、质感或剪裁" in system_prompt
    assert "理顺线条/收住轮廓/留出余地/像别针固定裙摆" in system_prompt
    assert "温柔照看型、careful/cautious/gentle/supportive/defensive 棋风回复应更像轻声、顾虑、照看、小心翼翼或关心对方感受" in system_prompt
    assert "非沉默走棋时必须优先带出" in system_prompt
    assert "轻轻/小心/慢慢/别吓到/安全一点/可以吗" in system_prompt
    assert "称呼和口头禅是调味，不是每轮固定前缀" in system_prompt
    assert "角色设定里的亲密称呼、兴奋感叹、迟疑轻声、标志性尾音或固定口癖允许穿插使用" in system_prompt
    assert "最近 2 条角色台词已经用过同一个称呼或口头禅时" in system_prompt
    assert "本轮普通走棋应换成动作、情绪或角色生活经验开头" in system_prompt
    assert "只有开场、赌约确认、胜负承认、安慰/挑逗用户、或角色关系倾向强烈时才适合再次使用" in system_prompt
    assert "尤其不要每回合都用同一个亲密称呼来证明角色风味" in system_prompt
    assert "优先换成该角色设定里的具体生活领域语言、动作比喻或情绪反应" in system_prompt
    assert "当上下文明显显示当前角色是温柔照看、胆怯谨慎或低压安抚型时" in system_prompt
    assert "必须至少有一个照看信号" in system_prompt
    assert "棋子动作应像在安抚棋盘上的小动物或怕惊扰对方棋子" in system_prompt
    assert "如果【普通对话同源角色上下文】显示当前角色有明确生活领域、职业、兴趣或价值观" in system_prompt
    assert "普通 move 文本必须至少使用一个来自该领域的具体词或动作" in system_prompt
    assert "审美/设计/手艺领域可用线条、轮廓、搭配、剪裁、质感、颜色、收边、布置等词" in system_prompt
    assert "示例只是领域抽取方式，不是角色名模板" in system_prompt
    assert "不要只用“嗯……那我把某棋往某处挪”" in system_prompt
    assert "不得让不同角色都说成同一个“先稳住中路/试探你的兵线”" in system_prompt
    assert "同一手用户走法已经被角色回应过，本轮不要再次用“你这一步/你刚才/你的小兵……”开头复述同一手" in system_prompt
    assert "用户只说“继续/再来/别重复/换个说法”时" in system_prompt
    assert "“试探/中路/阵型/阵脚/车路/先稳/占个位置”是高风险机械词" in system_prompt
    assert "最近两条可见台词里出现过就必须换成角色化说法" in system_prompt
    assert "如果候选走法与上一轮相似，不能只替换棋子名" in system_prompt
    assert "把“轻轻试探布料弹性”改成“试探阵脚”" in system_prompt
    assert "必须更换表达角度" in system_prompt
    assert "如果连续两轮选择同一类棋子或同一个 selected_move_id" in system_prompt
    assert "不要继续使用上一轮的同一拟人、同一动词和同一收尾" in system_prompt
    assert "往前蹦一蹦/有什么好玩的反应" in system_prompt
    assert "挪一挪/站到宽敞的地方" in system_prompt
    assert "用户本轮发了新消息，必须先短短回答" in system_prompt
    assert "用户抱怨“你又要说/别重复/换个说法/不要模板”时" in system_prompt
    assert "禁止任何承认模板存在或解释自己正在改写的元话语" in system_prompt
    assert "不要使用“自己被用户识破了”的自我揭穿句" in system_prompt
    assert "不要用“用户提醒得正确”开头自我纠错" in system_prompt
    assert "不要声明本轮要避开某个词或改用别的说法" in system_prompt
    assert "台词里不解释“我在避免重复”" in system_prompt
    assert "不要引用用户抱怨里的禁用词" in system_prompt
    assert "尤其是温柔照看型角色遇到这类抱怨时" in system_prompt
    assert "不能先承认被指出、不能声明自己正在改写" in system_prompt
    assert "应直接变成低压动作" in system_prompt
    assert "反模板挑战轮的第一句只能从角色动作或情绪出发" in system_prompt
    assert "活泼/庆祝型=“声音或热闹动作 + 直接说棋子动作”" in system_prompt
    assert "审美/手艺型=“生活领域动作/线条/搭配 + 棋子动作”" in system_prompt
    assert "最近没有反复称呼时才可带亲密称呼" in system_prompt
    assert "温柔/照看型=“低声/轻一点/小心 + 棋子轻缓行动”" in system_prompt
    assert "用户消息与【最近小游戏对话】里的旧消息相同" in system_prompt
    assert "小兵/卒被吃只需轻描淡写" in system_prompt
    assert "【普通对话同源角色上下文】决定同一走法的说法差异" in system_prompt
    assert "不要让所有角色都套“先动某个棋子 + 空泛理由”的同一种句式" in system_prompt
    assert "同一个“车往前走”，寡言角色、活泼角色、学者型角色、进攻型角色、温柔谨慎角色都应有不同措辞" in system_prompt
    assert "普通 move 若只是“你走 X，我把 Y 平到 Z/挪到某处，这样照看中央/留出空间/试探阵脚”，就算机械说棋" in system_prompt
    assert "没有明确战术原因时，也要让棋子动作带一点角色自己的身体感、生活领域或情绪转弯" in system_prompt
    assert "move_summary/reply_hint 当成必须复读的台词" in system_prompt
    assert "候选走法可能带 speech_hooks" in system_prompt
    assert "本局语言记忆与下一句换法" in full_prompt
    assert "上一轮模型自报近期重复词" in full_prompt
    assert "我再考虑" in full_prompt
    assert "顺便盯" in full_prompt
    assert "本轮内部避让记号" in full_prompt
    assert "overused_phrases" in full_prompt
    assert "这是硬格式要求，不是风格建议" in system_prompt
    assert "这些只是生成前的内部风格避让记号，不是角色台词素材" in full_prompt
    assert "不能在角色台词中解释、引用、纠正、吐槽或表演" in system_prompt
    assert "不要把避让动作写成自我审稿、纠错或解释禁词的元话语" in system_prompt
    assert "不要只是把棋子名替换进上一轮相同的默认模板" in system_prompt
    assert "【输出前硬性自检】" in system_prompt
    assert "只要任一可见字段含有承认模板存在、自我纠错、解释禁词、声明本轮改写或引用用户坏例子的元话语" in system_prompt
    assert "本次 JSON 不合格，必须重写为角色内行动或情绪" in system_prompt
    assert "本场景还额外禁止自我揭穿、自我纠错、声明本轮改口、声明避开某个词这些句式结构" in system_prompt
    assert "如果【普通对话同源角色上下文】显示当前角色是温柔照看、胆怯谨慎或低压安抚型" in system_prompt
    assert "action=move 的可见文本必须含有至少一个照看信号" in system_prompt
    assert "如果【普通对话同源角色上下文】或角色名显示当前角色是温柔照看、胆怯谨慎或低压安抚型" in system_prompt
    assert "entry_card.chess_style.play_style 是 careful/cautious/gentle/supportive/defensive" in system_prompt
    assert "只写“我把炮平到五路/照应棋面中央/我先动一下/棋子之间能有个照应”仍不合格" in system_prompt
    assert "即使同句也有“轻轻/小心”，仍视为机械说棋" in system_prompt
    assert "先给你的小兵一点余地" in system_prompt
    assert "如果普通 move 的可见文本只有棋子、方向、五路/中路/棋面中央、留空间、试探、照应、动一动这些通用棋盘信息" in system_prompt
    assert "如果普通 move 的可见文本含“稳住阵脚/看看阵线/打开边路/先稳住/阵线/阵脚”" in system_prompt
    assert "playful 必须补具体热闹/点心/彩带/小剧场动作" in system_prompt
    assert "审美/手艺型必须补线条/剪裁/质感/布置动作" in system_prompt
    assert "普通 move 的可见文本必须至少落到一个对应领域的具体词或动作" in system_prompt
    assert "只写“阵脚/棋面/位置/动一动/收拢/看一看”不合格" in system_prompt
    assert "普通走棋的可见文本如果含有“试探/中路/阵型/阵脚/先稳/稳一点/车路/占个位置/透透气”或其它通风呼吸类比喻" in system_prompt
    assert "JSON 不合格，必须改成角色自己的动作语言" in system_prompt
    assert "【最终可见文本自检】" in full_prompt
    assert "如果角色上下文明显是温柔照看、胆怯谨慎或低压安抚型且 action=move" in full_prompt
    assert "如果最近小游戏对话和本局长程互动记录还没有出现“升级/改成/现在改为 C/赌注C”等用户明确升级语句" in system_prompt
    assert "不得抢先把 B 说成已经升级到 C" in system_prompt
    assert "用户本轮是在确认/升级赌注、追问 A/B/C、口令、留言、昵称、约定、角色答应过什么或谁该兑现" in system_prompt
    assert "不得用“还没轮到我/等你先走/你还没动”挡掉确认" in system_prompt
    assert "用户本轮明说“赌注升级为C/升级为C/当前有效赌注/按升级后的赌注C/哪个赌注执行”" in system_prompt
    assert "必须完整逐字写出该专名" in system_prompt
    assert "不得截成“棋...”/“一...”/“那声称呼”" in system_prompt
    assert "不得先用“轮到你/等你出招/你先走完/等你落子”拖延确认" in system_prompt
    assert "不要用【跨局象棋记忆】或【普通对话同源角色上下文】里的旧局事实覆盖本局事实" in system_prompt
    assert "当前局内若用户已经明说“闲聊内容A是/口令是/赌注B是/赌注升级为C”" in system_prompt
    assert "这些用户原话就是当前局事实锚" in system_prompt
    assert "只能算角色说错或旧记忆串台" in system_prompt
    assert "用户本轮直接给出“别只说记得，要说出 X”时" in system_prompt
    assert "回复必须逐字包含 X" in system_prompt
    assert "不得把 X 解释成“就是/也就是/是”另一个旧短语" in system_prompt
    assert "不得主动补出旧口令或角色刚才错答" in system_prompt
    assert "普通 move 的角色风味必须出现在本轮 move 可见文本里" in system_prompt
    assert "开场、上一轮称呼或前文已经有角色风味，不能抵扣本轮" in system_prompt
    assert "心里踏实一点/免得你太放肆/透透气" in system_prompt
    assert "opening_chat 和普通 move 都必须至少含一个明确低压照看信号" in system_prompt
    assert "认真下/愉快对局/心里踏实一点/先看住这一线" in system_prompt
    assert "本轮普通 move 的角色领域词必须出现在当前可见文本本身" in system_prompt
    assert "不能因为开场说过设计、礼服、派对、温柔，就让本轮 move 退回通用棋评" in system_prompt
    assert "任何“棋...”“一...”或省略号截断都不合格" in full_prompt
    assert "event_type=opening_chat 的开场也要有角色风味" in system_prompt
    assert "只说“好的，我会认真下，希望玩得开心”不合格" in system_prompt
    assert "角色执黑方后手时，不能说“那我先走/我先动/我先落子”" in system_prompt
    assert "如果普通角色上下文里有明确生活领域、职业、兴趣或价值观" in full_prompt
    assert "不要只写“阵脚/棋面/位置/动一动/收拢/看一看”这类通用棋盘词" in full_prompt
    assert "不要回应自己被指出了，也不要声明正在避开某个词或更换表达" in full_prompt
    assert "直接用角色自己的动作语言落子" in full_prompt
    assert "本轮必须同时换开头、换用户动作描述方式、换走法理由角度" in system_prompt
    assert "只删掉“轻轻”或把“布料”换成“阵脚”仍算重复" in system_prompt
    assert "反复把棋子说成好玩反应或蹦跳" in system_prompt
    assert "反复使用布料、开门、帘幕、通风类比喻" in system_prompt
    assert "反复承认自己在改写/纠错" in system_prompt
    assert "不得继续沿用同一个比喻簇" in system_prompt
    assert "以下词簇是高风险默认模板，即使最近没出现也不要主动拿来写普通走棋" in system_prompt
    assert "试探、中路、阵型、阵脚、先稳、稳一点、车路、占个位置、通风呼吸类比喻、承认被识破类元话语、声明本轮改口类元话语" in system_prompt
    assert "或自我纠错类元话语时" in system_prompt
    assert "被你发现" not in system_prompt
    assert "我确实" not in system_prompt
    assert "这次不说" not in system_prompt
    assert "看看能不能吓你一跳" in system_prompt
    assert '顶层字段 "近期重复词"' in system_prompt
    assert "写完 character_reply.text 和 tts_text 之后，必须回头填写" in system_prompt
    assert "这个 JSON 就是不合格的" in system_prompt
    assert '字段必须至少包含 ["嘿嘿","那我","将你一军"]' in system_prompt
    assert "下一回合会把这个字段注入【上一轮模型自报近期重复词】和【本轮内部避让记号】" in system_prompt
    assert '"近期重复词"' in full_prompt
    assert "同一条回复内部也要避免重复同一个语气词" in system_prompt
    assert "角色情绪要沿着这一局推进" in system_prompt
    assert "挑衅、调侃、赌约、求饶、追问、撒娇或亲密玩笑" in system_prompt
    assert "前进动作不要扩写成固定攻击口号" in system_prompt
    assert "活动一下" not in system_prompt
    assert "往前压" not in system_prompt
    assert "看看你怎么应对" not in system_prompt
    assert "优先从“看看能不能吃到、看看能不能打到、碰一下" in system_prompt
    assert "“瞄/盯/看着”只能偶尔使用" in system_prompt
    assert "尤其不要写“能不能瞄到/顺便瞄一下”" in system_prompt
    assert "最近 3 条用过“瞄/瞄到/盯/看着/心疼/换回一点/先站稳/试探/中路" in system_prompt
    assert "过河压一压" not in system_prompt
    assert "user_requested=用户明确要求/建议的合法走法" in system_prompt
    assert "user_requested 是用户请求，不是硬性命令" in system_prompt
    assert "必须读取 entry_card.execution_policy.user_request_affinity" in system_prompt
    assert "4-5 的角色更倾向于接受用户请求" in system_prompt
    assert "0-2 的角色更倾向于坚持自己的判断" in system_prompt
    assert "user_request_affinity 高的角色" in system_prompt
    assert "user_request_affinity 低的角色" in system_prompt
    assert "不要因为存在 user_requested 就自动服从" in system_prompt
    assert "用户说“走兵/小兵”，角色执黑方时 piece=卒 的 user_requested 候选也算接受请求" in system_prompt
    assert "跳过用户请求的原因" in system_prompt
    assert "必须区分两类用户请求" in system_prompt
    assert "下一回合请求/建议，不是硬命令" in system_prompt
    assert "可以按性格答应、说会考虑、调皮敷衍、或婉拒" in system_prompt
    assert "要求角色抢回合立即走棋" in system_prompt
    assert "所有方向描述必须以角色自己的视角为准" in system_prompt
    assert "角色说“前/后”时" in system_prompt
    assert "角色说“左/右”时也按同一角色视角计算" in system_prompt
    assert "我的左边/我的右边" in system_prompt
    assert "你的左边/你的右边" in system_prompt
    assert "不是用户坐在屏幕前反向换算出来的左右" in system_prompt
    assert "不要去掉“我的/你的”" in system_prompt
    assert "当前棋子存亡摘要" in full_prompt
    assert "已经离开棋盘，不能再作为“协同、配合、保护、照应、借力进攻”的对象" in system_prompt
    assert "己方车、马、炮等高价值棋子" in system_prompt
    assert "禁止自行补出“护仕/护士/护中路小兵/保护小兵/照应某子”" in system_prompt
    assert "士/仕、兵/卒这类低价值或贴身防守棋子" in system_prompt


def test_xiangqi_execute_prompt_injects_normal_role_context():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="Jason",
        turn="black",
        entry_card={
            "power_tier": "novice",
            "chess_style": {"play_style": "playful"},
            "execution_policy": {"user_request_affinity": 5},
        },
    )

    prompt = "\n".join(
        message["content"]
        for message in minigames._execute_prompt(
            req,
            {
                "character_profile": "【角色详细设定】碧琪热情、跳脱、爱开玩笑。",
                "context_memory": "【上下文记忆】\n[中期记忆]\n用户和碧琪最近常常一起玩小游戏。",
                "memory_fragments": "- relationship: 碧琪喜欢用轻松语气逗 Jason 开心。",
                "recent_dialogue": "Jason: 我们刚才说好下棋不要太严肃。",
            },
        )
    )

    assert "【普通对话同源角色上下文】" in prompt
    assert "【角色详细设定】碧琪热情、跳脱、爱开玩笑。" in prompt
    assert "[中期记忆]" in prompt
    assert "用户和碧琪最近常常一起玩小游戏" in prompt
    assert "碧琪喜欢用轻松语气逗 Jason 开心" in prompt
    assert "我们刚才说好下棋不要太严肃" in prompt
    assert "entry_card 只是一张象棋专用配置卡" in prompt


def test_xiangqi_execute_prompt_defines_opening_events():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="black",
        turn="red",
        event_context={"event_type": "opening_first_move", "must_speak": True},
        move_candidates=[
            {
                "id": "c1",
                "quality_tag": "random_safe",
                "move_summary": "红方马往前跳",
                "reply_hint": "马往前跳",
            }
        ],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_type=opening_chat" in prompt
    assert "角色执黑方后手" in prompt
    assert "禁止承诺具体首招" in prompt
    assert "event_type=opening_first_move" in prompt
    assert "开场白和第一步棋必须在同一轮完成" in prompt
    assert "只允许围绕最终选中的候选走法" in prompt
    assert "opening_commitment" not in prompt


def test_xiangqi_execute_prompt_uses_cross_game_memory_for_previous_game_questions():
    req = minigames.XiangqiExecuteRequest(
        character_name="云宝",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="上一局我吃了你几个兵？",
        game_memory={
            "schema_version": 1,
            "has_previous_game": True,
            "latest_game": {
                "game_id": "game-previous",
                "summary": "上一局用户执红方、角色执黑方，用户吃了角色2个卒。",
                "capture_stats": {
                    "user_captured_character": {
                        "total": 3,
                        "by_text": {"卒": 2, "炮": 1},
                        "by_kind": {"soldier": 2, "cannon": 1},
                    },
                    "character_captured_user": {
                        "total": 1,
                        "by_text": {"兵": 1},
                        "by_kind": {"soldier": 1},
                    },
                },
            },
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【跨局象棋记忆】" in prompt
    assert "用户问“上一局/上局/上一盘/上一把/刚才那局/刚才那盘”" in prompt
    assert "不要从当前棋盘倒推" in prompt
    assert "latest_game.capture_stats" in prompt
    assert "capture_stats.user_captured_character.by_kind.soldier" in prompt
    assert "capture_stats.character_captured_user.by_kind.soldier" in prompt
    assert "不存在该键就按 0 回答" in prompt
    assert '"game_id": "game-previous"' in prompt
    assert '"soldier": 2' in prompt
    assert "不要把用户吃角色和角色吃用户反过来" in prompt


def test_xiangqi_execute_prompt_keeps_current_game_dialogue_and_moves_for_in_game_memory_questions():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="刚才我们这局说好的赌注是什么？我刚才吃了你什么？你刚才答应了吗？下局让我先手还算数吗？",
        board_state={"winner": None, "turn": "black"},
        dialogue_history=[
            {"role": "user", "text": "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"},
            {"role": "character", "text": "好呀，我记住啦，输了就给赢家写胜利留言。"},
            {"role": "user", "text": "你投降吧，我觉得你输定了。"},
            {"role": "character", "text": "我才不投降呢，这局我还要反击。"},
            {"role": "user", "text": "下局你让我先手，记住了吗？"},
            {"role": "character", "text": "记住啦，下局再说，这局我先顾眼前。"},
        ],
        move_history=[
            {
                "actor": "user",
                "side": "red",
                "piece": "兵",
                "piece_kind": "soldier",
                "is_capture": True,
                "captured_piece": "卒",
                "captured_piece_kind": "soldier",
                "move_summary": "红方兵往前走，吃掉黑方卒",
            },
            {
                "actor": "character",
                "side": "black",
                "piece": "炮",
                "piece_kind": "cannon",
                "is_capture": True,
                "captured_piece": "马",
                "captured_piece_kind": "horse",
                "move_summary": "黑方炮平过去，吃掉红方马",
            },
        ],
        game_memory={
            "has_previous_game": True,
            "latest_game": {
                "game_id": "old-game",
                "summary": "上一局角色赢了，不能覆盖当前这一局。",
                "capture_stats": {
                    "user_captured_character": {"by_kind": {"soldier": 5}},
                    "character_captured_user": {"by_kind": {"horse": 2}},
                },
            },
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【本局记忆问答】" in prompt
    assert "优先读取【本局长程互动记录】、【最近小游戏对话】、【最近走法】、【最近一步事实】和当前用户/角色执棋方" in prompt
    assert "不要用【跨局象棋记忆】或【普通对话同源角色上下文】里的旧局事实覆盖本局事实" in prompt
    assert "不要从棋盘残子倒推已发生的吃子账本" in prompt
    assert "本局尚未终局时，不得因为用户追问、挑衅、赌约、下一局约定或跨局摘要提前宣布胜负" in prompt
    assert "只有 board_state.winner、event_context.winner 或 event_context.postgame_review 明示时才说已赢/已输" in prompt
    assert "只作为下一局约定和聊天记忆，不改变当前 player_side、turn、board_state 或候选走法" in prompt
    assert "用户执棋：红方" in prompt
    assert "角色执棋：黑方" in prompt
    assert "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。" in prompt
    assert "好呀，我记住啦，输了就给赢家写胜利留言。" in prompt
    assert "你投降吧，我觉得你输定了。" in prompt
    assert "我才不投降呢，这局我还要反击。" in prompt
    assert "下局你让我先手，记住了吗？" in prompt
    assert "红方兵往前走，吃掉黑方卒" in prompt
    assert "黑方炮平过去，吃掉红方马" in prompt
    assert "上一局角色赢了，不能覆盖当前这一局。" in prompt


def test_xiangqi_execute_prompt_keeps_current_game_long_term_casual_chat():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="刚才我让你记住的口令是什么？输的人要做什么？",
        board_state={"winner": None, "turn": "black"},
        dialogue_history=[
            {"role": "character", "text": "最近几步我一直在防你的车。"}
        ],
        game_memory={
            "current_game": {
                "completed_reason": "in_progress",
                "character_result": "unfinished",
                "move_count": 38,
                "summary": "本局仍在进行，用户执红方。",
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
            }
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【本局长程互动记录】" in prompt
    assert "current_game.salient_interactions" in prompt
    assert "这局的口令是星星饼干，结束后你要记得。" in prompt
    assert "记住了，星星饼干，我会把它写进这局的小笔记里。" in prompt
    assert "输的人给赢家写一句胜利留言。" in prompt
    assert "好，胜利留言这件事我也记下了。" in prompt
    assert "不能说“我想起来了/你这一提才想起来/好像有个约定”" in prompt
    assert "普通连续走棋不要每回合都套“先猜用户意图、再说我方落子、最后等用户反应”的固定骨架" in prompt


def test_xiangqi_execute_prompt_tracks_abc_wager_upgrade_before_game_over():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="你还记得A和现在的赌注吗？",
        board_state={"winner": None, "turn": "black"},
        game_memory={
            "current_game": {
                "completed_reason": "in_progress",
                "character_result": "unfinished",
                "move_count": 42,
                "summary": "本局仍在进行。",
                "salient_interactions": [
                    {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
                    {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
                    {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
                    {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
                    {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
                    {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
                ],
                "recent_user_messages": [
                    "内容A：这局的口令是星星饼干，结束后你要记得。",
                    "赌注B：输的人给赢家写一句胜利留言。",
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
                ],
            }
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "内容A：这局的口令是星星饼干，结束后你要记得。" in prompt
    assert "赌注B：输的人给赢家写一句胜利留言。" in prompt
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" in prompt
    assert "收到，赌注从一句留言升级成三句留言加一次棋盘老师。" in prompt
    assert "原来是 B，后来改成 C" in prompt
    assert "当前有效版本是 C" in prompt


def test_xiangqi_execute_prompt_postgame_uses_upgraded_c_for_either_winner():
    base_review = {
        "summary": "这一局已经结束。",
        "move_count": 48,
        "salient_interactions": [
            {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
            {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
            {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
            {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
            {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
            {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
        ],
        "recent_user_messages": [
            "内容A：这局的口令是星星饼干，结束后你要记得。",
            "赌注B：输的人给赢家写一句胜利留言。",
            "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。",
        ],
        "dialogue": [
            {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
            {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
            {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
            {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
            {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
            {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
        ],
    }

    user_won_req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="我赢了，升级后的赌注是什么？",
        event_context={
            "event_type": "postgame_chat",
            "winner": "red",
            "character_result": "lost",
            "postgame_review": {**base_review, "character_result": "lost"},
        },
        move_candidates=[],
        legal_moves=[],
    )
    character_won_req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="你赢了，现在要我执行什么？",
        event_context={
            "event_type": "postgame_chat",
            "winner": "black",
            "character_result": "won",
            "postgame_review": {**base_review, "character_result": "won"},
        },
        move_candidates=[],
        legal_moves=[],
    )

    user_won_prompt = "\n".join(message["content"] for message in minigames._execute_prompt(user_won_req))
    character_won_prompt = "\n".join(message["content"] for message in minigames._execute_prompt(character_won_req))

    assert "若角色输了且最新有效赌注/约定要求输家做 C" in user_won_prompt
    assert "角色应按角色性格承认结果并表示愿意按 C 做" in user_won_prompt
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" in user_won_prompt
    assert "若角色赢了且最新有效赌注/约定要求输家做 C" in character_won_prompt
    assert "角色可以按角色性格提醒、调侃或认真要求用户执行 C" in character_won_prompt
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" in character_won_prompt


def test_xiangqi_execute_prompt_distinguishes_latest_game_from_previous_previous_game():
    req = minigames.XiangqiExecuteRequest(
        character_name="云宝",
        user_name="用户",
        player_side="black",
        turn="red",
        user_message="上一局是谁赢？上上局是谁赢？",
        game_memory={
            "schema_version": 1,
            "completed_games_count": 2,
            "has_previous_game": True,
            "latest_game": {
                "game_id": "game-b",
                "summary": "第二局用户执黑方、角色执红方，角色获胜。",
                "winner": "red",
                "character_result": "won",
            },
            "recent_games": [
                {
                    "game_id": "game-a",
                    "summary": "第一局用户执红方、角色执黑方，用户获胜。",
                    "winner": "red",
                    "character_result": "lost",
                },
                {
                    "game_id": "game-b",
                    "summary": "第二局用户执黑方、角色执红方，角色获胜。",
                    "winner": "red",
                    "character_result": "won",
                },
            ],
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "用户问“上上局/前一局的前一局/倒数第二局”" in prompt
    assert "读取 recent_games 中 latest_game 前一条完成记录" in prompt
    assert "不要用 latest_game 覆盖上上局" in prompt
    assert "不要把 recent_game_summaries 的顺序倒过来" in prompt
    assert '"game_id": "game-a"' in prompt
    assert "第一局用户执红方、角色执黑方，用户获胜。" in prompt
    assert '"game_id": "game-b"' in prompt
    assert "第二局用户执黑方、角色执红方，角色获胜。" in prompt


def test_xiangqi_execute_prompt_exposes_postgame_review_fields_for_score_and_wager_questions():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="Jason",
        player_side="red",
        turn="black",
        user_message="刚才这局谁赢了？我吃了你几个卒？赌注是什么？最后你哪里看漏了？",
        event_context={
            "event_type": "postgame_chat",
            "winner": "red",
            "character_result": "lost",
            "postgame_review": {
                "summary": "这一局用户执红方、角色执黑方，共24手，用户获胜。最后用户炮平中路形成杀棋。",
                "move_count": 24,
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
                    {"move_summary": "第24手红方炮平中路，黑方看漏中路被将死"}
                ],
                "recent_user_challenges": [
                    "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"
                ],
            },
        },
        dialogue_history=[
            {"role": "user", "text": "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"},
            {"role": "character", "text": "好呀，我记住啦，输了就给赢家写胜利留言。"},
            {"role": "user", "text": "刚才那个赌注你可别忘了。"},
            {"role": "character", "text": "记着呢，愿赌服输我也会认的。"},
        ],
        move_history=[
            {
                "actor": "user",
                "side": "red",
                "piece": "炮",
                "is_check": True,
                "is_capture": True,
                "captured_piece": "将",
                "move_summary": "第24手红方炮平中路，黑方看漏中路被将死",
            }
        ],
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_type=postgame_chat 或 event_context.postgame_review 存在时" in prompt
    assert "【终局/赛后硬状态】" in prompt
    assert "当前请求已经离开走棋阶段：turn 只是客户端旧值或无意义残留" in prompt
    assert "本轮用户正在追问本局闲聊、约定、赌注、承诺或答应过什么" in prompt
    assert "不能只复盘胜负或最后一手" in prompt
    assert "用户问胜负、双方执棋方、总手数、吃子账本、最后关键走法、早先闲聊" in prompt
    assert "postgame_review.summary、move_count、capture_stats、key_moments、salient_interactions" in prompt
    assert "精确数量按 capture_stats 回答" in prompt
    assert "原话和答应用 dialogue/salient_interactions/recent_user_messages/recent_user_challenges 回答" in prompt
    assert '"move_count": 24' in prompt
    assert '"卒": 2' in prompt
    assert '"炮": 1' in prompt
    assert '"马": 1' in prompt
    assert "第24手红方炮平中路，黑方看漏中路被将死" in prompt
    assert "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。" in prompt
    assert "好呀，我记住啦，输了就给赢家写胜利留言。" in prompt
    assert "记着呢，愿赌服输我也会认的。" in prompt


def test_xiangqi_execute_prompt_reviews_postgame_loss_without_repeating_fixed_reply():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="black",
        user_message="碧琪你怎么输了",
        event_context={
            "event_type": "postgame_chat",
            "winner": "red",
            "character_result": "lost",
            "postgame_review": {
                "summary": "这一局用户执红方、角色执黑方，共24手，用户获胜。最后用户炮平中路形成杀棋。",
                "last_move": {
                    "actor": "user",
                    "piece": "炮",
                    "is_capture": True,
                    "captured_piece": "将",
                    "move_summary": "红方炮平到中路，吃掉将",
                },
                "repeated_user_question_count": 3,
                "recent_postgame_replies": [
                    "呜呜……输掉了……不过没关系！再来一局，我肯定能赢！"
                ],
                "recent_user_challenges": [
                    "你投降吧，我觉得你输定了",
                    "输了要挨草哦",
                ],
            },
        },
        dialogue_history=[
            {"role": "user", "text": "你投降吧，我觉得你输定了"},
            {"role": "user", "text": "碧琪你怎么输了"},
            {"role": "character", "text": "呜呜……输掉了……不过没关系！再来一局，我肯定能赢！"},
            {"role": "user", "text": "碧琪你怎么输了"},
        ],
        move_history=[
            {
                "actor": "user",
                "side": "red",
                "piece": "炮",
                "is_capture": True,
                "captured_piece": "将",
                "move_summary": "红方炮平到中路，吃掉将",
            }
        ],
        game_memory={
            "has_previous_game": True,
            "latest_game": {
                "summary": "这一局用户执红方、角色执黑方，共24手，用户获胜。",
                "key_moments": [
                    {"move_summary": "红方炮平到中路，吃掉将"}
                ],
            },
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【终局复盘问答】" in prompt
    assert "你怎么输了/为什么输了/输在哪" in prompt
    assert "event_context.postgame_review" in prompt
    assert "不要只套用胜负情绪或固定“输掉了，再来一局”" in prompt
    assert "至少要点到最近终局相关事实之一" in prompt
    assert "本轮换一个角度" in prompt
    assert "不要复用上一句的开头、标点节奏、结尾或整句" in prompt
    assert "recent_user_challenges" in prompt
    assert "用户对输赢、投降、赌约、惩罚或挑衅的旧话" in prompt
    assert "角色输了时可承认" in prompt
    assert "不要只说普通“我输了/再来一局”" in prompt
    assert "你投降吧，我觉得你输定了" in prompt
    assert "红方炮平到中路，吃掉将" in prompt
    assert "repeated_user_question_count" in prompt
    assert "呜呜……输掉了" in prompt


def test_xiangqi_execute_prompt_character_loss_recalls_user_challenge():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="black",
        event_context={
            "event_type": "character_lost",
            "winner": "red",
            "character_result": "lost",
            "postgame_review": {
                "summary": "用户用炮将死黑方，角色输掉了。",
                "last_move": {
                    "actor": "user",
                    "piece": "炮",
                    "move_summary": "红方炮平中路将死黑方",
                },
                "recent_user_challenges": [
                    "你投降吧，我觉得你输定了",
                    "那你准备把屁股翘高吧，你要输了",
                ],
            },
        },
        dialogue_history=[
            {"role": "user", "text": "你投降吧，我觉得你输定了"},
            {"role": "character", "text": "现在才刚开局，我可不会轻易认输的！"},
            {"role": "user", "text": "那你准备把屁股翘高吧，你要输了"},
        ],
        move_history=[
            {
                "actor": "user",
                "piece": "炮",
                "is_check": True,
                "move_summary": "红方炮平中路将死黑方",
            }
        ],
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_type=character_lost" in prompt
    assert "recent_user_challenges" in prompt
    assert "【终局/赛后硬状态】" in prompt
    assert "当前请求已经离开走棋阶段：turn 只是客户端旧值或无意义残留" in prompt
    assert "不得说还没轮到我、你先走、你先下、我等着接招、下一步再看、继续走或继续下" in prompt
    assert "这些终局/赛后事实优先级高于 turn" in prompt
    assert "不得再按“当前不是角色走棋”去催用户走棋" in prompt
    assert "必须明确承认本局已经结束且角色输了" in prompt
    assert "即使 turn 显示轮到用户、用户消息包含“现在/还打算/你打算/轮到”，也不得说还没轮到自己、等用户先下或接下来再走" in prompt
    assert "禁止说“现在轮到你/你先走/你先下/你先动/等你走/等你下/我等着/下一步看你/继续走/继续下”" in prompt
    assert "角色输后必须回收这句话的情绪" in prompt
    assert "不要只说普通“我输了/再来一局”" in prompt
    assert "你投降吧，我觉得你输定了" in prompt
    assert "那你准备把屁股翘高吧，你要输了" in prompt


def test_xiangqi_execute_prompt_preserves_character_owned_one_soldier_boast():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="现在呢？你还打算用那一个兵赢我吗？",
        event_context={
            "event_type": "character_lost",
            "winner": "red",
            "character_result": "lost",
            "postgame_review": {
                "summary": "角色只剩一个兵可以进攻，后来所有进攻型棋子都被用户吃完，角色输了。",
                "recent_user_challenges": [
                    "你打算就用这一个兵赢我吗",
                ],
            },
        },
        dialogue_history=[
            {"role": "user", "text": "你打算就用这一个兵赢我吗"},
            {"role": "character", "text": "是啊，试试才知道"},
        ],
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "你打算/你要/你是不是想/你准备用/你就用" in prompt
    assert "确认后的计划、嘴硬和承诺归属角色自己" in prompt
    assert "不要说“你刚才说要用一个兵赢我”" in prompt
    assert "【终局/赛后硬状态】" in prompt
    assert "当前请求已经离开走棋阶段：turn 只是客户端旧值或无意义残留" in prompt
    assert "不得说还没轮到我、你先走、你先下、我等着接招、下一步再看、继续走或继续下" in prompt
    assert "角色已经输掉本局；本轮回复要承认输局并承接本局聊天，不要写成仍在对弈" in prompt
    assert "【当前回合指令解读】" not in prompt
    assert "这些终局/赛后事实优先级高于 turn" in prompt
    assert "不得再按“当前不是角色走棋”去催用户走棋" in prompt
    assert "必须明确承认本局已经结束且角色输了" in prompt
    assert "即使 turn 显示轮到用户、用户消息包含“现在/还打算/你打算/轮到”，也不得说还没轮到自己、等用户先下或接下来再走" in prompt
    assert "禁止说“现在轮到你/你先走/你先下/你先动/等你走/等你下/我等着/下一步看你/继续走/继续下”" in prompt
    assert "如果用户旧话是“你打算/你要/你是不是...”这类对角色计划的提问" in prompt
    assert "不得写成“你刚才说要...”" in prompt
    assert "你打算就用这一个兵赢我吗" in prompt
    assert "是啊，试试才知道" in prompt


def test_xiangqi_execute_prompt_marks_waiting_turn_directive_as_deferred():
    req = minigames.XiangqiExecuteRequest(
        character_name="玉琪派",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="等一下你把炮放到中间，做一个当中炮",
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【当前回合指令解读】" in prompt
    assert "给角色下一回合提出走棋请求/建议，不是硬性命令" in prompt
    assert "可以答应、说会考虑、调皮地先记下" in prompt
    assert "也可以婉拒或表示这步未必合适" in prompt
    assert "不要承诺一定执行" in prompt
    assert "调用方未提供候选走法；如需走棋，只能返回 chat_only。" in prompt


def test_xiangqi_execute_prompt_does_not_treat_wager_upgrade_as_waiting_turn_directive():
    req = minigames.XiangqiExecuteRequest(
        character_name="玉琪派",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="现在我把赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。你确认一下当前有效赌注。",
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【当前回合指令解读】" not in prompt
    assert "赌注升级为C" in prompt
    assert "必须立刻 action=chat_only 回答这些对局记忆" in prompt
    assert "不得先用“轮到你/等你出招/你先走完/等你落子”拖延确认" in prompt


def test_xiangqi_execute_prompt_marks_immediate_waiting_turn_request_as_illegal():
    req = minigames.XiangqiExecuteRequest(
        character_name="玉琪派",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="你现在先走一步，把炮放到中间",
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【当前回合指令解读】" in prompt
    assert "要求角色现在/抢先下棋" in prompt
    assert "违反回合规则" in prompt
    assert "需要等用户先走完" in prompt
    assert "不要承诺立刻执行" in prompt


def test_xiangqi_execute_prompt_defines_undo_request_decisions():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="用户",
        player_side="red",
        turn="black",
        user_message="刚才点错了，让我申请悔棋",
        event_context={
            "event_type": "user_undo_request",
            "must_not_move": True,
            "undo_request": {
                "requester": "user",
                "steps": 1,
                "last_actor": "user",
                "reason": "刚才点错了",
                "case": "before_character_moved",
                "request_number": 2,
                "recent_character_replies": [
                    "好呀好呀，这步让你重走！嘿嘿，我正好也想看看你会换什么新招呢～"
                ],
                "user_move_to_undo": {
                    "actor": "user",
                    "piece": "兵",
                    "piece_kind": "soldier",
                    "from": {"x": 0, "y": 6},
                    "to": {"x": 0, "y": 5},
                },
                "recently_undone_user_moves": [
                    {
                        "actor": "user",
                        "piece": "兵",
                        "piece_kind": "soldier",
                        "from": {"x": 0, "y": 6},
                        "to": {"x": 0, "y": 5},
                    }
                ],
                "same_user_move_repeat_count": 1,
                "repeated_same_user_move_after_undo": True,
            },
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_type=user_undo_request 时，本轮必须只裁决悔棋申请" in prompt
    assert "case=before_character_moved 表示用户刚走完、角色尚未下棋" in prompt
    assert "case=after_character_moved 表示角色已经回应落子" in prompt
    assert "只能返回 approve_undo 或 reject_undo" in prompt
    assert "action=request_undo 表示角色主动申请悔棋" in prompt
    assert "action=resign 表示角色认输投降" in prompt
    assert "undo_request.request_number" in prompt
    assert "不要复用上一句的开头、句式、语气词或收尾" in prompt
    assert "undo_request.repeated_same_user_move_after_undo=true" in prompt
    assert "undo_request.same_user_move_repeat_count>0" in prompt
    assert "必须有递进或转折" in prompt
    assert "undo_request.user_move_to_undo" in prompt
    assert "undo_request.recently_undone_user_moves" in prompt
    assert '"action": "move|move_silent|chat_only|approve_undo|reject_undo|request_undo' in prompt
    assert "|resign" in prompt
    assert '"undo_request": null' in prompt


def test_xiangqi_character_can_request_undo_after_own_move_on_user_turn():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="你刚才那步是不是看漏了，要不要申请悔棋？",
        move_history=[
            {
                "actor": "character",
                "side": "black",
                "piece": "马",
                "from": {"x": 7, "y": 0},
                "to": {"x": 8, "y": 2},
                "move_summary": "黑方马跳到你的右边",
            }
        ],
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "当前不是角色走棋，但用户正在询问或劝角色撤回刚才一步" in prompt
    assert "last_move.actor=character" in prompt
    assert "角色可以立刻用 action=request_undo 主动申请悔棋" in prompt
    assert "不需要等到再次轮到角色" in prompt
    assert "不要说“要等轮到我才能悔棋”" in prompt
    assert '"actor": "character"' in prompt
    assert '"action": "move|move_silent|chat_only|approve_undo|reject_undo|request_undo' in prompt


def test_xiangqi_character_can_resign_when_persuaded_on_user_turn():
    req = minigames.XiangqiExecuteRequest(
        character_name="云宝",
        user_name="用户",
        player_side="red",
        turn="red",
        user_message="你现在局面已经救不回来了，认输投降吧",
        move_history=[
            {
                "actor": "character",
                "side": "black",
                "piece": "象",
                "from": {"x": 2, "y": 0},
                "to": {"x": 4, "y": 2},
                "move_summary": "黑方象飞到中路",
            }
        ],
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【当前回合投降解读】" in prompt
    assert "用户正在劝角色认输/投降" in prompt
    assert "可以立刻返回 action=resign" in prompt
    assert "不需要等到再次轮到角色" in prompt
    assert "不要说“要等轮到我才能投降”" in prompt
    assert "投降不是走棋" in prompt


def test_xiangqi_user_resigned_event_is_chat_only():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="black",
        user_message="我认输投降。",
        event_context={
            "event_type": "user_resigned",
            "must_not_move": True,
            "must_speak": True,
            "surrender": {
                "requester": "user",
                "result": "player_resigned",
                "phase": "opening_very_early",
                "move_count": 1,
                "pressure_hint": "very_early",
                "user_text": "认输投降",
                "last_move_summary": "红方兵往前走",
            },
        },
        move_candidates=[],
        legal_moves=[],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_type=user_resigned" in prompt
    assert "用户已经认输投降且角色赢了" in prompt
    assert "必须 action=chat_only" in prompt
    assert "不能走棋" in prompt
    assert "必须读取 event_context.surrender" in prompt
    assert "phase=before_first_move 或 opening_very_early" in prompt
    assert "pressure_hint=character_in_check 或 user_ahead_by_captures" in prompt
    assert "不能固定套胜利台词" in prompt
    assert '"phase": "opening_very_early"' in prompt


def test_xiangqi_user_resigned_fallback_varies_by_situation():
    early = minigames._xiangqi_user_resigned_fallback_text(
        minigames.XiangqiExecuteRequest(
            user_message="认输投降",
            event_context={
                "event_type": "user_resigned",
                "surrender": {
                    "phase": "opening_very_early",
                    "pressure_hint": "very_early",
                    "user_text": "认输投降",
                },
            },
        )
    )
    surprising = minigames._xiangqi_user_resigned_fallback_text(
        minigames.XiangqiExecuteRequest(
            user_message="我认输",
            event_context={
                "event_type": "user_resigned",
                "surrender": {
                    "phase": "middle",
                    "pressure_hint": "character_in_check",
                    "user_text": "我认输",
                },
            },
        )
    )
    tired = minigames._xiangqi_user_resigned_fallback_text(
        minigames.XiangqiExecuteRequest(
            user_message="有点累了，不想下了，我认输",
            event_context={
                "event_type": "user_resigned",
                "surrender": {
                    "phase": "middle",
                    "pressure_hint": "ordinary",
                    "user_text": "有点累了，不想下了，我认输",
                },
            },
        )
    )

    assert "这么快" in early
    assert "有点意外" in surprising
    assert "先到这里" in tired
    assert len({early, surprising, tired}) == 3


def test_xiangqi_execute_prompt_requires_new_move_after_character_undo_approved():
    req = minigames.XiangqiExecuteRequest(
        character_name="碧琪",
        user_name="用户",
        player_side="red",
        turn="black",
        user_message="下一次你走兵；刚才那步已经同意悔棋，这次请避开刚撤回的同类棋子；如果前面有具体棋子建议，优先按那个建议和合法候选处理；台词和实际走法必须一致。",
        event_context={
            "event_type": "normal",
            "must_not_repeat_undone_move": True,
            "recently_undone_character_moves": [
                {
                    "actor": "character",
                    "piece": "马",
                    "from": {"x": 7, "y": 0},
                    "to": {"x": 8, "y": 2},
                    "move_summary": "黑方马跳到你的右边",
                }
            ],
        },
        move_candidates=[
            {
                "id": "rook_alternative",
                "quality_tag": "good",
                "move": {"from": {"x": 0, "y": 0}, "to": {"x": 0, "y": 1}},
                "piece": "车",
                "move_summary": "黑方车往前走",
                "reply_hint": "车往前走",
            }
        ],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "event_context.must_not_repeat_undone_move=true" in prompt
    assert "recently_undone_character_moves 非空" in prompt
    assert "本轮必须改走另一种可用走法" in prompt
    assert "不能选择 recently_undone_character_moves 中相同 from/to 的走法" in prompt
    assert "优先选不同棋子种类" in prompt
    assert "不表示排除用户另提的具体棋子建议" in prompt
    assert "user_requested 且它不是刚撤回的同类棋子" in prompt
    assert "不要固定使用带“换/改”的套话承接" in prompt
    assert "优先直接说最终选中的棋子要做什么" in prompt
    assert "不要先说“准备走兵/下一步走兵”却实际选择马、炮、车等别的棋子" in prompt


def test_xiangqi_user_undo_request_result_is_coerced_to_decision():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="用户",
        event_context={"event_type": "user_undo_request"},
    )

    result = minigames._coerce_xiangqi_undo_result(
        req,
        minigames._normalize_execute_result(
            {
                "schema_version": 2,
                "action": "move",
                "selected_move_id": "c1",
                "character_reply": {"text": "我走这里。"},
                "move": {"from": {"x": 0, "y": 0}, "to": {"x": 0, "y": 1}},
            }
        ),
    )

    assert result["action"] == "reject_undo"
    assert result["selected_move_id"] is None
    assert result["move"] is None
    assert result["character_reply"]["text"]
    assert result["private"]["undo_coerced"] is True


def test_xiangqi_execute_prompt_exposes_captured_piece_survival_context():
    req = minigames.XiangqiExecuteRequest(
        character_name="紫悦",
        user_name="用户",
        player_side="black",
        turn="red",
        board_state={
            "pieces": [
                {"x": 4, "y": 9, "side": "red", "kind": "general", "text": "帅"},
                {"x": 5, "y": 5, "side": "red", "kind": "horse", "text": "马"},
                {"x": 7, "y": 5, "side": "black", "kind": "cannon", "text": "炮"},
                {"x": 4, "y": 0, "side": "black", "kind": "general", "text": "将"},
            ]
        },
        move_history=[
            {
                "actor": "character",
                "side": "red",
                "piece": "马",
                "is_capture": True,
                "captured_piece": "车",
                "to": {"x": 5, "y": 5},
                "move_summary": "红方马往前跳，从(6,7)到(5,5)，吃掉车",
            },
            {
                "actor": "user",
                "side": "black",
                "piece": "炮",
                "is_capture": False,
                "from": {"x": 7, "y": 2},
                "to": {"x": 7, "y": 5},
                "move_summary": "黑方炮往前挪，从(7,2)到(7,5)，并过河",
            },
        ],
        event_context={
            "character_material_pressure": {
                "active": True,
                "severity": "high",
                "reason": "recent_high_value_loss",
                "recent_lost_piece": {"piece": "车", "kind": "rook"},
                "remaining_high_value_count": 2,
            },
            "character_material_momentum": {
                "active": True,
                "severity": "medium",
                "reason": "recent_user_high_value_capture",
                "recent_captured_user_piece": {"piece": "马", "kind": "horse"},
                "user_remaining_piece_count": 5,
            },
        },
        move_candidates=[
            {
                "id": "c1",
                "quality_tag": "good",
                "move_summary": "红方马往前跳",
                "reply_hint": "马往前跳",
            }
        ],
    )

    prompt = "\n".join(message["content"] for message in minigames._execute_prompt(req))

    assert "【当前棋子存亡摘要】" in prompt
    assert '"黑方": {"炮": 1, "将": 1}' in prompt
    assert '"captured_side_label": "黑方"' in prompt
    assert '"captured_piece": "车"' in prompt
    assert "recent_captures 里的棋子已经离开棋盘" in prompt
    assert "不能再作为“协同、配合、保护、照应、借力进攻”的对象" in prompt
    assert "board_state.crossed_soldiers" in prompt
    assert "count=1 必须说“一个/一枚”" in prompt
    assert "event_context.character_material_pressure" in prompt
    assert "调皮型角色也同样要读取这一压力信号" in prompt
    assert "一边开玩笑一边急着补救" in prompt
    assert "event_context.character_material_momentum" in prompt
    assert "愉悦、得意、松一口气、兴奋" in prompt
    assert "刚吃掉用户大子时先高兴，刚丢自己大子时先紧张" in prompt



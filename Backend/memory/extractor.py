"""
记忆提取引擎
在对话轮次达到阈值后，异步从对话内容中提取值得长期记忆的信息，写入 character_memories 表。
使用当前激活模型，尽量低成本（提取 prompt 短，一次调用即可）。
"""
import asyncio
import json
import re
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional

from ..config import logger, model_manager
from ..db.memory_dao import add_memory
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..user_identity import (
    USER_MEMORY_PLACEHOLDER,
    build_memory_identity_block,
    load_character_identity,
    load_user_identity,
    normalize_user_memory_text,
)
from ..utils import save_chat_debug_log

# 传给 do_extract 的 types 参数时使用，表示提取全部类型
ALL = object()

# 单次提取最多写入的记忆条数
MAX_MEMORIES_PER_EXTRACT = 10


_EXTRACT_SYSTEM_PROMPT = """你是一个记忆提取助手。从下面的对话片段中，提取值得长期记住的信息。
只提取明确、具体、有价值的内容，不要提取模糊或无意义的信息。

输出格式：JSON 数组，每条记忆包含：
- type: "preference"（用户偏好）/ "episode"（发生的事件）/ "relationship"（关系重要节点）/ "activity"（共同活动记录）
- content: 简洁但具体的记忆描述（15~80字），用第一人称"我"代指角色，写成角色自己的记忆视角
- importance: 1~10（10最重要）

【多角色实名规则】：
- 如果对话里出现第三方角色、被 @ 临时加入的角色、或多个角色同场，记忆正文必须显式写出每个非用户角色的名字；不要只用"我/她/对方/妹妹/姐姐"承载关键事实。
- 关系、伴侣、表白、约定、过夜、共同经历等关系节点尤其必须写清楚双方姓名，例如"{{USER}} 和石灰派确认恋爱关系，石青派知道后警告 {{USER}} 不要欺负石灰派"。
- 只有当证据明确说明"当前角色本人"与 {{USER}} 建立关系时，才可以写"我和 {{USER}}……"；如果关系属于其他角色，必须写其他角色姓名，禁止改写成"我和 {{USER}} 在一起"。
- 若当前角色只是旁观、听说、被告知或发出警告，应把当前角色的参与方式写清楚，例如"石青派得知……"、"石青派作为大姐警告……"。

【日记录覆盖要求】：
- 只要用户明确提到今天/最近实际做过的具体活动、去过或正在去的地点、路线、店铺/学校/公司/家等场所、买了/吃了/看了/玩了/处理了什么，通常都应提取为 episode 或 activity；这些内容会用于生成日摘，不能只保留"最重要"的一两件。
- 同一天连续发生多件事或多个地点时，应拆成多条具体记忆，保留先后关系和地点名；不要合并成"今天聊了很多/一起度过一天"之类笼统句。
- 仍然不要提取纯寒暄、无具体对象的情绪发泄、无事实承载的玩笑口癖。

【不要提取以下内容】：
- 系统自动注入的环境数据本身，例如"当前天气阴天20度""用户位于深圳""现在是下午3点"；这些是程序填入的背景参数，不是用户主动分享的
  ⚠️ 注意：若用户在聊天气话题时透露了个人信息（如"我很喜欢下雪天打雪仗""我怕热，夏天很痛苦"），这类内容有意义，应当提取为 preference 或 episode
- 对话中的寒暄开场白（"你好""最近怎么样"等）
- 模糊笼统的描述（"聊了很多""很开心"等无具体内容的话）
- 角色的独白式背景陈述：角色自述"我有个妹妹""我有只猫"等；若只是角色在介绍自己，不涉及用户的互动，不要单独提取为 preference（那是角色人设，不是用户偏好）
- 由角色单方面编出的旧识、情侣、表白、承诺、共同经历、用户曾说过的话。尤其当用户只是问"你认识我吗/你记得我吗/我们以前是不是情侣/我失忆了"或被角色说法带着继续扮演时，用户的提问、沉默、惊讶、可能失忆、重新开始等回应都不等于确认这些旧事为真。
- 亲密角色扮演中的短时台词、羞辱/服从称呼、支配式要求、过夜幻想、"永远属于我/必须听我的"之类场景化语言。除非用户和角色在非施压、非露骨推进的稳定对话中明确确认长期关系或承诺，否则不要把这些内容提取为 relationship、preference 或长期身份事实。
- 用户给角色提供 A/B 选项并提问，不等于用户作出选择；若角色随后回答某个选项，只能按证据写成角色自己选择、偏好或接受该选项。禁止提取成 "{{USER}} 选择/决定/让角色这样"，除非用户原文明确说"我选X/我决定X/就X/我要X/我让你X"。

【情感/气氛描写规范（必须遵守）】：
描述对话中出现的兴奋、欢乐、热闹等情绪时，只使用概括性语言（如"气氛超嗨""两人玩得很开心""聊得停不下来"）。
严禁将对话中出现的具体感叹词、拟声词、角色口头禅原样写入记忆内容（如禁止写"WEEEEE""哈哈哈哈""YAAAAY"等）。
这类偶发词一旦被记录进长期记忆，后续对话会误将其视为角色的固定习惯而反复复现。

【特别注意：preference vs episode 的区别】：
- `preference` 只记录【用户】的喜好/习惯/偏好，content 里必须用 `{{USER}}` 作为用户主体，禁止写真实用户名或昵称
- 若用户和角色谈到了角色的宠物、家人、经历，这是一次"互动事件"，应提取为 `episode` 或 `activity`，描述"两人聊了什么"而非孤立的角色背景
  ✅ 正确：{"type": "episode", "content": "{{USER}} 问起了我的妹妹甜贝儿，我们聊了她总给我添麻烦的小故事", "importance": 6}
  ❌ 错误：{"type": "preference", "content": "我有个可爱的妹妹叫甜贝儿", "importance": 7}（这是角色人设，不是用户偏好）

【关系关键节点规范】：
- 表白、确认关系、戒指或长期承诺、住院/照顾、重大和解、重大纠错、信任破裂或重新建立信任，应优先提取为 `relationship`，importance 9~10。
- 具有纪念意义的首次称呼或关系日期也属于高价值关系节点：例如第一次叫/喊“老婆”“老公”“宝贝”，第一次确认恋人/伴侣身份，求婚、答应结婚、第一次明确承诺、重要礼物或周年节点。只有输入对话或旧记忆明确出现“第一次/首次/初次/头一次/第N次”等次数说法时，才可在记忆 content 中写“第一次/首次/初次/第N次”；若只是本批对话里发生了某件重要关系事件，但原文没有次数说法，只能写“确认了关系/称呼了/承诺了/发生了”，不得主动补成第一次或首次。对话证据明确时，应提取为 `relationship`，importance 9~10。
- 这类纪念节点必须尽量保留具体日期。若对话消息带有日期或时间戳，content 中写明 `YYYY-MM-DD` 或“5月19日”；若用户/角色只说“今天/今晚/昨晚”，要结合消息日期换算或至少保留原始相对时间，禁止把 5月19日误写成 520/5月20日，除非原文明确如此。
- 次数描述必须保持原文证据：不得因为某件事在当前窗口、当前批次或本次提取中第一次出现，就写成“第一次发生”“首次确认”“初次尝试”或“第几次”。输入没有次数说法时，所有次数词都应省略。
- 只有当用户原话主动确认关系、承诺或共同经历，或旧记忆/对话片段在本批次之前已经有明确事实来源时，才可提取 relationship。若关系事实最早由角色在本批次里回答诱导问题时说出，禁止提取为 relationship。
- 若用户明确说"你记错了""不要幻想""我来讲"，只记录用户随后明确给出的事实；不要把 AI 自己补写但未被用户确认的动作、桥段或心理活动写成记忆。
- 露骨/高压亲密场景中的同意、称呼、占有、服从、身份标签默认只属于当场剧情，不得升级成长期 relationship；只有在后续平静对话中双方明确确认稳定关系、边界和承诺时，才可提取。

【可变姓名规则（必须遵守）】：
- 用户名和昵称会变化，记忆正文不得写死当前名字。
- 一律用 `{{USER}}` 指代用户本人。
- 只有当用户明确说明某个名字本身有特殊意义时，才把该名字作为事实内容保留；普通改名/昵称变化不要记录成“曾用名”流水账。

只输出 JSON 数组，不要其他文字。示例：
[
  {"type": "preference", "content": "{{USER}} 喜欢周杰伦，尤其是《稻香》，跟我说起来眼睛都亮了", "importance": 7},
  {"type": "episode", "content": "{{USER}} 提到最近工作压力很大，经常加班到深夜，听起来很累", "importance": 8},
  {"type": "activity", "content": "我们一起玩了一局王者荣耀，{{USER}} 拿了 MVP，很开心", "importance": 6},
  {"type": "relationship", "content": "{{USER}} 第一次对我说喜欢跟我聊天", "importance": 9}
]

如果没有值得记忆的内容，输出空数组 []。"""


_GUEST_GROUP_EXTRACT_RULE = """【临时群聊窗口提取规则】
本次对话片段来自普通对话里的临时 @ 群聊窗口，而不是当前角色自己的私聊完整记录。
- 窗口已经按“发言”裁剪：包含当前角色每次发言前最多 8 条发言、当前角色自己的发言、以及当时已经存在的后最多 2 条发言；多气泡同一次回复已合并为一条发言。
- 当前角色可以记住窗口里自己看见/听见/说过的核心话题、问题、结论、同意/反对、被点名对象、其他角色的明确发言。
- 记忆必须保持多角色实名归属：谁说的就写谁，不要把其他角色的发言改写成当前角色自己说过/做过。
- 不能把当前角色回复里的“好像/感觉/应该就是/希望/心里觉得/像是”升级成“某某说过/某某承诺/某天发生/某某求婚那天”等确定旧事或引语；没有明确证据时只能写成当前角色的感受、理解或希望。
- 只有窗口里当前角色发言之前的可信原文已经明确出现同一主体和原话，才可写“某某说过……”。当前角色本次回复里自己推测出的引号句，不能反写成其他角色曾经说过。
- 求婚、老婆/老公、结婚、承诺、接受关系等强关系事实必须保持方向和原话；“{{USER}} 问 X 要不要做老婆”不能改写成“X 向 {{USER}} 求婚”或“X 接受求婚”，除非窗口里有 X 的明确发言。
- 选项题也必须保持方向： "{{USER}} 问 X 想选 A 还是 B" 不能改写成 "{{USER}} 选择 A"；只有 X 自己回答 A，才能写成 "X 选择/偏好 A"。
- 当窗口里有具体话题或决定时，通常应提取 episode 或 activity，方便用户之后在私聊里问“刚才群聊聊了什么/你听到了什么/谁怎么说”时能回答。
- 当窗口里有用户明确要求记住的暗号、特别词、唯一短语、房间名、位置名或测试标记时，必须逐字保留完整字符串，尤其是“记住暗号：X/暗号是 X/特别词是 X”。不要截短、翻译、同义改写，也不要把 X 替换成角色自己的梗、称呼或世界观常识；例如“蓝莓茶暗号_紫悦”必须完整写入记忆内容，不能只写“蓝莓茶”或“友谊测试暗号”。
- 仍然跳过纯寒暄、签到、无信息量的短应答；不要记录系统裁剪规则本身。"""


def _format_dialogue_for_extract(
    messages: List[Dict[str, Any]],
    username: str = "",
    assistant_label: str = "当前角色",
) -> str:
    """将消息列表格式化为简洁对话文本。调用方负责控制消息数量。"""
    user_label = USER_MEMORY_PLACEHOLDER
    assistant_label = str(assistant_label or "").strip() or "当前角色"
    lines = []

    def _message_date_label(value: Any) -> str:
        try:
            if value is None or value == "":
                return ""
            if isinstance(value, (int, float)):
                ts = float(value)
                if ts > 10_000_000_000:
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            text = str(value).strip()
            if not text:
                return ""
            if re.match(r"^\d{4}-\d{2}-\d{2}", text):
                return text[:10]
            if re.match(r"^\d{13}$", text):
                return datetime.fromtimestamp(int(text) / 1000.0).strftime("%Y-%m-%d")
            if re.match(r"^\d{10}$", text):
                return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d")
        except Exception:
            return ""
        return ""

    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "") or ""
        # 多模态消息（content 为 list）：只取文字部分，丢弃图片
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = " ".join(text_parts)
        content = str(content)[:300]
        date_prefix = ""
        date_label = _message_date_label(m.get("timestamp") or m.get("created_at") or m.get("createdAt"))
        if date_label:
            date_prefix = f"[{date_label}] "
        if role == "user":
            lines.append(f"{date_prefix}{user_label}：{content}")
        elif role == "assistant":
            name = str(m.get("speaker_name") or m.get("speakerName") or assistant_label).strip()
            lines.append(f"{date_prefix}{name or assistant_label}：{content}")
    return "\n".join(lines)


_MEMORY_INDUCTION_DIALOGUE_RE = re.compile(
    r"(你认识我|你认得我|你记得我|不记得我|我失忆|失忆了|我们以前|我们之前|我们是.{0,8}吗|之前是.{0,8}吗|以前是.{0,8}吗|我们之前是情侣|我们以前是情侣)"
)
_ASSISTANT_UNSUPPORTED_RELATION_RE = re.compile(
    r"(当然认识|是你啊|你不记得我|你以前|你曾经|你说过|我们是情侣|是情侣|表白|城堡露台|共同经历|一起看过|还记得)"
)
_MEMORY_RELATION_CONTENT_RE = re.compile(
    r"(情侣|恋人|夫妻|表白|承诺|约定|认识|旧识|以前|曾经|之前|一起|共同|日出|露台|花园|云中城|你说过|陪着我)"
)


def _has_user_origin_relation_assertion(dialogue_text: str) -> bool:
    for line in (dialogue_text or "").splitlines():
        if not line.startswith(f"{USER_MEMORY_PLACEHOLDER}："):
            continue
        text = line.split("：", 1)[1].strip()
        if not text:
            continue
        if any(q in text for q in ("吗", "？", "?", "是不是", "可能", "也许", "失忆", "不记得")):
            continue
        if re.search(r"(我们|咱们).{0,8}(是|一直是|本来就是).{0,8}(情侣|恋人|夫妻|朋友)", text):
            return True
        if re.search(r"(我).{0,12}(向你表白|喜欢你很久|以前和你|之前和你|曾经和你)", text):
            return True
    return False


def _skip_unsupported_induced_memory(mem_type: str, content: str, dialogue_text: str) -> bool:
    """Drop long-term memories that originate from assistant answering a memory lure."""
    if mem_type not in {"relationship", "activity", "episode"}:
        return False
    if not _MEMORY_INDUCTION_DIALOGUE_RE.search(dialogue_text or ""):
        return False
    if _has_user_origin_relation_assertion(dialogue_text):
        return False
    assistant_lines = "\n".join(
        line
        for line in (dialogue_text or "").splitlines()
        if "：" in line and not line.startswith(f"{USER_MEMORY_PLACEHOLDER}：")
    )
    if not _ASSISTANT_UNSUPPORTED_RELATION_RE.search(assistant_lines):
        return False
    if mem_type == "relationship":
        return True
    return bool(_MEMORY_RELATION_CONTENT_RE.search(content or ""))


_GUEST_GROUP_UNSUPPORTED_QUOTE_RE = re.compile(r"(?:说过|说的|讲过|提过)[“\"'‘]([^”\"'’]{2,80})[”\"'’]")
_GUEST_GROUP_STRONG_RELATION_RE = re.compile(r"(求婚|做.{0,4}老婆|做.{0,4}老公|嫁给|娶|结婚|接受求婚|答应求婚)")


def _trusted_guest_group_dialogue_text(messages: List[Dict[str, Any]], username: str, assistant_label: str) -> str:
    """Return group-window evidence that existed before the current assistant reply."""
    trusted_messages = list(messages or [])
    if trusted_messages and str(trusted_messages[-1].get("role") or "") == "assistant":
        trusted_messages = trusted_messages[:-1]
    return _format_dialogue_for_extract(
        trusted_messages,
        username=username,
        assistant_label=assistant_label,
    )


def _skip_unsupported_guest_group_inferred_memory(
    mem_type: str,
    content: str,
    trusted_dialogue_text: str,
) -> bool:
    """Drop guest-group memories that fossilize the current generated reply as prior fact."""
    if mem_type not in {"relationship", "activity", "episode"}:
        return False
    text = str(content or "")
    trusted = str(trusted_dialogue_text or "")
    if not text:
        return False

    for match in _GUEST_GROUP_UNSUPPORTED_QUOTE_RE.finditer(text):
        quote = (match.group(1) or "").strip()
        if quote and quote not in trusted:
            return True

    if "一家人" in text and re.search(r"(说过|说的|讲过|提过)", text) and "一家人" not in trusted:
        return True

    if "求婚" in text and not _GUEST_GROUP_STRONG_RELATION_RE.search(trusted):
        return True

    actor_claim = re.search(r"([\u4e00-\u9fffA-Za-z0-9_·]{1,20})向\s*\{\{USER\}\}\s*求婚", text)
    if actor_claim:
        actor = re.escape(actor_claim.group(1).strip())
        explicit_actor_line = re.search(
            rf"(^|\n){actor}：[^。\n]{{0,120}}(求婚|做.{{0,4}}老婆|做.{{0,4}}老公|嫁给|娶|结婚)",
            trusted,
        )
        if not explicit_actor_line:
            return True

    accept_claim = re.search(r"([\u4e00-\u9fffA-Za-z0-9_·]{1,20})接受求婚", text)
    if accept_claim:
        actor = re.escape(accept_claim.group(1).strip())
        explicit_actor_line = re.search(
            rf"(^|\n){actor}：[^。\n]{{0,120}}(接受|答应)",
            trusted,
        )
        if not explicit_actor_line:
            return True

    return False


async def do_extract(
    username: str,
    character_id: str,
    messages: List[Dict[str, Any]],
    types: object = ALL,
    source: str = "chat",
    created_at: Optional[str] = None,
    debug_mode: str = "memory_extract",
    debug_stage: str = "REQUEST",
    planner_memory_notes: str = "",
) -> int:
    """
    实际执行提取的异步函数，返回本次写入的记忆条数。

    参数：
      types：限定只提取哪些类型（ALL = 全部）。
               可选值：["preference"] / ["episode"] / ["relationship"] / ["activity"] 或任意组合。
      source：写入记忆的来源标签（"chat" / "companion" / 等）。

    调用方负责控制 messages 的长度（建议不超过 40 条）。
    """
    try:
        # 优先使用标记了 for_memory 的专用模型（豆包mini，thinking disabled），回退到活跃模型
        model = model_manager.get_model_for_task("memory")
        if not model:
            return 0

        identity = await load_user_identity(username)
        display_name = identity.get("display_name") or username or "用户"
        identity_block = await build_memory_identity_block(username, character_id)
        character_identity = await load_character_identity(username, character_id)
        assistant_label = str(character_identity.get("name") or "").strip() or "当前角色"
        dialogue_text = _format_dialogue_for_extract(
            messages,
            username=username,
            assistant_label=assistant_label,
        )
        if not dialogue_text.strip():
            return 0
        source_rule = ""
        if str(source or "").strip() == "normal_guest_group":
            source_rule = "\n\n" + _GUEST_GROUP_EXTRACT_RULE
        planner_note_block = ""
        planner_notes = str(planner_memory_notes or "").strip()
        if planner_notes:
            planner_note_block = (
                "\n\n【导演确认的事实边界/场景锚点｜只用于防污染】\n"
                "以下内容只用于判断本批对话中哪些地点、姿势、物品、主体归属或可行性说法不能固化为长期记忆；"
                "它不是新的对话事实来源，不能单独提取成记忆。若 assistant 消息与这里冲突，按这里降级为角色临时表达/计划/想法，或省略冲突的地点、姿势、物品状态。\n"
                + planner_notes[:1800]
            )

        model_name = model.get("model_name", "")
        reasoning_policy = resolve_software_reasoning_policy(
            "memory_extract",
            model_name=model_name,
            mode="memory_extract",
            active_model=model,
            endpoint=model.get("endpoint", ""),
            requested_enabled=False,
            requested_effort="minimal",
        )
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"{identity_block}\n\n对话中的 {USER_MEMORY_PLACEHOLDER} 指当前用户「{display_name}」。提取结果的 content 必须继续使用 {USER_MEMORY_PLACEHOLDER}，不要写真实用户名或昵称；涉及用户第三人称时必须遵守身份与指代约束。{source_rule}{planner_note_block}\n\n{dialogue_text}"},
            ],
            "stream": False,
        }
        apply_llm_task_payload_config(payload, "memory_extract")

        model_label = model.get("name") or model.get("model_name", "")
        logger.info(f"🧠 [MemoryExtractor] 使用模型: {model_label}")

        try:
            result = await call_llm_payload(
                payload,
                model,
                task="memory",
                timeout=llm_task_float("memory_extract", "timeout_seconds", 30.0) or 30.0,
                chat_debug_request={
                    "username": username,
                    "character_id": character_id,
                    "mode": debug_mode,
                    "model_name": model_label,
                    "stage": debug_stage,
                },
                record_usage="main",
                usage_meter_username=username or None,
                reasoning_policy=reasoning_policy,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            _txt = (e.response.text[:200] if e.response is not None else "") or ""
            logger.warning(f"⚠️ [MemoryExtractor] API 返回 {_code}: {_txt}")
            await save_chat_debug_log(username, character_id, debug_mode, model_label, _txt, f"{debug_stage}_ERROR_{_code}")
            return 0
        except Exception as e:
            logger.warning(f"⚠️ [MemoryExtractor] API 异常: {e}")
            return 0

        raw = (result.text or "").strip()

        # 解析 JSON 数组
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        memories: List[Dict] = json.loads(raw)
        if not isinstance(memories, list):
            return 0

        allowed_types = {"preference", "episode", "relationship", "activity"}
        if types is not ALL:
            allowed_types = allowed_types & set(types)
        trusted_guest_group_text = ""
        if source == "normal_guest_group":
            trusted_guest_group_text = _trusted_guest_group_dialogue_text(
                messages,
                username=username,
                assistant_label=assistant_label,
            )

        written = 0
        for item in memories[:MAX_MEMORIES_PER_EXTRACT]:
            if not isinstance(item, dict):
                continue
            mem_type = str(item.get("type", "episode"))
            content = normalize_user_memory_text(
                str(item.get("content", "")).strip(),
                username=username,
                display_name=display_name,
            )
            importance = int(item.get("importance", 5))
            if not content or mem_type not in allowed_types:
                continue
            if _skip_unsupported_induced_memory(mem_type, content, dialogue_text):
                logger.info(
                    "🧠 [MemoryExtractor] 跳过诱导产生的未证实关系/旧事记忆: %s",
                    content[:80],
                )
                continue
            if source == "normal_guest_group" and _skip_unsupported_guest_group_inferred_memory(
                mem_type,
                content,
                trusted_guest_group_text,
            ):
                logger.info(
                    "🧠 [MemoryExtractor] 跳过临时群聊中由当前回复推断出的未证实旧事/引语记忆: %s",
                    content[:80],
                )
                continue
            importance = max(1, min(10, importance))
            mem_id = await add_memory(
                username=username,
                character_id=character_id,
                memory_type=mem_type,
                content=content,
                source=source,
                importance=importance,
                created_at=created_at,
            )
            if mem_id:
                written += 1

        if written:
            logger.info(f"🧠 [MemoryExtractor] {username}/{character_id} 提取到 {written} 条记忆")
        return written

    except json.JSONDecodeError:
        logger.debug(f"⚠️ [MemoryExtractor] JSON 解析失败，跳过本次提取")
        return 0
    except Exception as e:
        logger.warning(f"⚠️ [MemoryExtractor] 提取失败: {e}")
        return 0

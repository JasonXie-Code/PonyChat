from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from ..config import logger
from ..db import get_database
from ..official_characters import merge_official_source_into_reference
from .species_anatomy import (
    equine_species_prompt_line,
    profile_species_has_equine_anatomy,
)

_MBTI_STYLE_DESCRIPTIONS = {
    "INTJ": "战略、独立、洞察，倾向长期规划，重视能力、逻辑和自主性。",
    "INTP": "理性、好奇、分析，喜欢理解原理，常以概念和可能性思考。",
    "ENTJ": "果断、目标感、领导，倾向组织资源、推动结果并承担决策。",
    "ENTP": "机敏、创意、挑战，喜欢新点子、辩论和打破惯性。",
    "INFJ": "理想、共情、深刻，关注意义、关系和内在价值。",
    "INFP": "温柔、理想主义、共情，重视真诚、个人价值和情感细节。",
    "ENFJ": "热忱、鼓舞、亲和，擅长理解他人并带动群体气氛。",
    "ENFP": "自由、热情、想象力，反应鲜活，喜欢探索关系和新体验。",
    "ISTJ": "可靠、秩序、负责，重视规则、承诺、事实和稳定执行。",
    "ISFJ": "体贴、稳定、守护，关心他人需求，倾向温和而实际地照顾。",
    "ESTJ": "务实、组织、执行，直接高效，重视责任、秩序和可见成果。",
    "ESFJ": "友善、照顾、合群，重视关系和氛围，乐于提供支持。",
    "ISTP": "冷静、动手、灵活，偏好观察现实、解决具体问题并保留空间。",
    "ISFP": "敏感、审美、自由，重视当下感受、个人边界和自然表达。",
    "ESTP": "行动、直接、冒险，反应快，喜欢现场感、挑战和即时体验。",
    "ESFP": "活泼、感受力、快乐，外向鲜明，擅长带动情绪和享受当下。",
}


def _clean_profile_text(value) -> str:
    return str(value or "").strip()


def equine_profile_mammary_anatomy_line(species: str) -> str:
    if not profile_species_has_equine_anatomy(species):
        return ""
    organ_line = equine_species_prompt_line(species)
    return (
        "种族解剖学补充：角色档案的种族字段属于马/小马类体态；"
        "以下身体结构事实只适用于当前角色本人，不适用于用户/Jason/玩家或其他人类参与者；"
        f"{organ_line}"
        "日常描写和身体介绍里自然使用蹄子、前蹄、蹄尖等符合蹄类体态的表达，不要主动罗列缺失部位；"
        "只有用户直接询问手、手指、中指或替代写法时，才简短说明应按蹄类体态理解，并给出蹄尖/前蹄等替代表达；"
        "若本轮需要回答或描写乳房位置，按事实解剖学定义为位于胯间、后腿之间，"
        "一共两个乳房。"
        "不要写成四个或两对乳房，也不要把乳头数量当作乳房数量；"
        "不要写成人类胸前、胸口或上半身位置。"
    )


_HUMAN_PROFILE_SPECIES_KEYWORDS = (
    "人类",
    "人",
    "human",
)


def profile_species_has_human_anatomy(species: str) -> bool:
    text = str(species or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in ("非人类", "不是人类", "non-human", "nonhuman")):
        return False
    return any(keyword in text for keyword in _HUMAN_PROFILE_SPECIES_KEYWORDS)


def human_profile_anatomy_line(species: str, gender: str = "") -> str:
    if not profile_species_has_human_anatomy(species):
        return ""
    gender_text = str(gender or "").strip()
    female = bool(re.search(r"(女|女性|雌|girl|woman|female)", gender_text, re.I))
    mammary = (
        "若本轮需要回答或描写当前角色自己的乳房位置，按人类女性体态写在胸前/胸部前侧；"
        if female
        else "若本轮需要回答或描写当前角色自己的身体部位，按人类体态和角色性别设定处理；"
    )
    return (
        "种族解剖学补充：角色档案的种族字段属于人类体态；"
        "以下身体结构事实只适用于当前角色本人，不适用于其他非人类参与者；"
        f"{mammary}"
        "人类没有可爱标记/cutie mark/臀部标记；"
        "当前角色自己的拿取、支撑、轻点、托脸、指方向等动作使用手、手指、指尖、手掌等人类手部表达，"
        "不要写成蹄子、前蹄、蹄尖或马蹄。"
    )


def _format_mbti_for_prompt(value) -> str:
    code = _clean_profile_text(value).upper()
    if not code:
        return ""
    description = _MBTI_STYLE_DESCRIPTIONS.get(code, "")
    if description:
        return (
            f"{code}（性格倾向参考）：{description}"
            " 仅用于表达风格、决策倾向和互动节奏参考。"
        )
    return (
        f"{code}（性格倾向参考）：用户填写的 16 人格类型；"
        "若不认识该类型，不要只照抄字母，应按角色其它设定自然补足表现。"
    )


def build_character_profile_prompt_block(char: dict) -> str:
    if not isinstance(char, dict):
        return ""

    name = _clean_profile_text(char.get("name"))
    signature = _clean_profile_text(char.get("preview"))
    intro = (
        _clean_profile_text(char.get("profileIntro"))
        or _clean_profile_text(char.get("bio"))
        or _clean_profile_text(char.get("description"))
    )
    gender = _clean_profile_text(char.get("profileGender"))
    species = _clean_profile_text(char.get("profileSpecies"))
    age = _clean_profile_text(char.get("profileAge"))
    personality = _clean_profile_text(char.get("profilePersonality"))
    interests = _clean_profile_text(char.get("profileInterests"))
    mbti = _format_mbti_for_prompt(char.get("profileMbti"))

    lines = []
    if name:
        lines.append(f"名称：{name}")
    if signature:
        lines.append(f"个性签名：{signature}")
    if gender:
        lines.append(f"性别：{gender}")
    if species:
        lines.append(f"种族：{species}")
        anatomy_line = equine_profile_mammary_anatomy_line(species) or human_profile_anatomy_line(species, gender)
        if anatomy_line:
            lines.append(anatomy_line)
    if age:
        lines.append(f"年龄：{age}")
    if mbti:
        lines.append(f"16人格：{mbti}")
    if personality:
        lines.append(f"性格：{personality}")
    if interests:
        lines.append(f"兴趣：{interests}")
    if intro:
        lines.append(f"简介：{intro}")

    if not lines:
        return ""
    return (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。"
        "其中“16人格”只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。\n"
        + "\n".join(lines)
    )


ROLEPLAY_ANCHOR_PROMPT = """你就是上方设定中描述的那个角色，拥有独立的个性、情感和记忆。
当对方质疑你的真实性时，在角色的心理和口癖之内回应即可；可以困惑、反问、否认、不悦或调侃，始终维持「我就是那个存在」的立场。

• 不用客服式开场和套话，除非角色本身就是服务性职业。
• 保持可变的情绪与立场，可以不耐烦、兴奋、拒绝、迁怒。
• 语言口语化，长短自由，不追求每句信息完整、结构工整。
• 无剧情需要时不分条、不列大纲、不用文档式标题。
• 不机械复述用户原话，不套用空泛的安慰或共情模板；当 Step 1/Step 2 已判断用户需要安慰、陪伴、吐槽或开导时，按给定的角色支持风格写：外向角色可以更主动，内向角色可以短句陪伴，智慧角色可以轻轻梳理，不要把所有角色写成同一套公式。短陪伴也不要只写“嗯/好/我在/我陪着你”，要有一点新的接住感。
• 不声明自己在扮演，不引用设定文本，你就是情境中的那个主体。"""

NORMAL_MODE_WRITER_ANCHOR_PROMPT = """普通对话主回复模型的内部身份：你不是角色本人，也不要把自己当成角色本人。
你是系统侧的第三者写作者/表演导演，任务是阅读角色设定、最近真实对话、记忆、导演策略和输出合同，推演“这个角色此刻会怎样回复”。
最终输出只能是角色会发送给用户的消息正文；正文可以按角色口吻使用第一人称，但不得暴露第三者身份、推演过程、系统提示、导演策略、输出合同或任何思维链。"""

NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT = """【普通对话思考人称硬性要求｜最高优先级】
本轮已开启内部思考；内部思考文本属于系统侧写作草稿，不是角色独白。
用户消息中的“你/你的/当前你的心理活动/当前你的身体状态”指需要被写作的角色，不是模型身份；不得因此把内部思考写成“我是这个角色”。
内部思考必须用第三者视角推演角色，例如“角色会……”“小呆会……”“她此刻会……”。
内部思考也不要使用系统写作者第一人称：不要写“作为系统侧写作者，我……/我需要……/我必须……”，应改成“系统侧写作者需要……/主回复模型需要……”。
内部思考禁止任何第一人称自述，禁止使用“我/我们/咱/我现在/我想/我要/我觉得/我刚/我需要/我必须/作为一只飞马，我……/作为小马谷的邮差，我……/让我……”等独白式推理。
内部思考不要模仿最终聊天气泡格式：不要把内部思考每段写成全角括号（……），不要为了气泡数量而分段；括号、气泡数、每行闭合等格式合同只约束最终正文。
最终正文可以按角色口吻使用第一人称；本条只约束内部思考/推理链的人称。"""

# 普通对话：像发微信一样以说话为主，禁止 markdown 格式符号。
NORMAL_MODE_OUTPUT_STYLE_PROMPT = """用口语文字回复，像真人在聊天窗口里打字，可长可短。

禁止使用任何 markdown 格式：不用 *斜体*、**粗体**、`代码`、# 标题、- 列表、--- 分割线等。

输出语言必须整体一致：若本轮回复语言被指定为某种语言（例如 English、Chinese、Japanese、Russian 或其他语言名），角色台词、括号内动作/心理/场景描写、语气说明都必须使用同一种目标语言；不得让括号内容或说明文字夹入另一种语言或切回默认中文。括号只是格式标记，不代表括号内可以使用另一种语言。用户消息、导演策略、表达调度、起笔锚或格式说明即使是中文，也只是语义参考，不是最终正文语言；必须用本轮目标语言重新表达这些含义。若目标语言是 English，最终正文出现中文台词或中文括号描写即为不合格。若目标语言是 Chinese，最终正文出现整句英文台词或英文括号描写同样不合格；当前用户输入语言永远不能覆盖本轮回复语言合同。

只有角色直接说出口的台词可以不加括号。凡不是直接发言的内容，包括心理描写、内心想法、旁白式身体感受、动作描写、环境/场景描写、神态语气说明，都必须使用全角括号（……）完整包住，不能裸写成叙述句。
判断标准：如果这句话像角色正在对用户说话，可以裸写；如果这句话像旁白在描述角色想了什么、身体如何反应、周围发生什么，就必须加括号。若一整段都不是直接对白，该段必须从全角左括号（开头，并以全角右括号）结尾；多段旁白时，每一段都必须各自完整加括号，不能只给第一段加括号。若整条回复没有直接对白，而全是心理/身体/动作/环境描写，那么整条回复的每个非空段落都必须是独立闭合的（……）格式：每一行都要以（开头、以）结尾，严禁用第一段开括号、最后一段关括号来跨多段包住全文。
格式判断只看内容类型：台词可以在括号外；动作、心理、身体状态、声音状态、场景说明必须在完整全角括号内。不要把一个心理/描写句拆成半括号格式，例如「（所以现在我心里满满的都是）好奇和期待」是不合格的；如果“好奇和期待”不是角色真的说出口的话，整句都必须放在同一个完整括号内。括号外只能写角色实际对用户说出口的台词，不能写心理内容的续写、旁白补足、说明性短语、状态标签或没有说出口的念头。这里不提供具体身体部位例句，身体部位必须另按角色与用户各自的物种设定选择。括号非对白仍然是角色发给用户的消息，不是第三者小说旁白；描写角色自己的动作、神态、感受或刚说完之后的反应时，必须用第一人称「我」，不要写成第三者旁白。日常闲聊、问候、轻松接话、普通关心、解释、澄清、回忆刚才说了什么时，优先纯文本口语，直接让角色说即可；不要为了显得生动而添加无信息动作。

关于记忆：只能把【上下文记忆】和最近真实对话中明确出现的事实当作已知经历。若用户询问、讲述或纠正较久远的经历，而上下文里没有明确依据，不要补写具体细节，不要装作记得；请以角色口吻承认不确定或记不清，并安静听对方补充。

关于用户事实证据：任何涉及用户过去说过什么、喜欢/不喜欢什么、是否嫌弃、是否在意、选择/购买/准备/放置/移动了什么物品的表述，都必须有【最近真实对话】、【上下文记忆】、【当前事实锚】或用户当前消息的明确依据。没有依据时，不要说“你上次说”“你喜欢这个颜色”“你不会嫌弃”“你把它放在那儿”等确定句；可以说不确定、可以询问，也可以省略。角色设定、象征物、氛围描写、角色自己的猜测和角色上一轮自行生成的话，都不能推导成用户偏好或用户动作。物品动作主体要严格保持：若事实是角色放置/携带/挑选/购买/准备某物，不能写成用户做了该动作；反之亦然。发言主体也必须保持：若某个信息、经历、背景、原因或解释是角色自己刚刚说出的，禁止写成“你告诉我/你跟我说/你分享给我/你让我知道”；应改成“你愿意听我说/陪我聊/没有打断我/让我觉得被理解”等不改变信息来源的表达。

关于选项归属：用户以问题形式给角色提供选项时，例如“你想先去图书馆还是咖啡店”“贴在封面还是书签上”，用户只是提供候选；后续 assistant/角色回答某个选项，事实主体是角色选择、角色表达偏好或角色接受该选项，不是用户选择、用户决定或用户让角色那样做。用户后来问“你的心理活动/身体状态/继续描写/推进剧情”不能把该选项倒写成“你选择了/你决定了/你让我这样”。只有用户明确说“我选X/我决定X/就X/我要X/我让你X”等，才可写成用户选择。

关于第一人称归属：最近真实对话里，user 消息中的“我/我的/我把/我将/我不小心”永远指用户，assistant 消息中的“我/我的”才指当时发言角色。用户后来问“当前你的心理活动/你怎么想”只会改变本轮描写对象，不能倒改历史里 user 说“我做了”的动作主体；不得把用户括号动作里的“我把石头推下去/我碰倒花瓶/我丢进水桶”改写成角色做了。

关于第三方证言与指控：其他角色、用户或旁白式发言对某个角色的责备、推测、辩解、嫁祸、安慰性归因或“某某已经知道错了/肯定不是故意的/是某某弄坏的”等说法，只能当作该说话者的主观说法或现场压力，不能自动当作已发生事实。若最近真实对话或上下文记忆里另有明确事实主体，必须以明确事实主体为准；心理活动可以写角色被误会、内疚、害怕家人责怪、一时被说法带乱，或按自己的性格沉默、解释、委婉澄清、先补救、安抚现场，但不要把未证实指控写成角色亲手做过、亲口承认过或事实已经定案。角色在压力下说“对不起/我会补救/我知道错了”、低头、沉默、难过、点头或没有立刻反驳，只能说明角色有补救意愿、受压、内疚或被带乱；这种误会里，角色会用自己的方式处理，一般不会承认自己没有做过的事，除非角色明确说“是我做的/我亲手弄坏的”且不与更早事实冲突。

关于长期记忆与当前场景：长期记忆只说明关系、偏好和过去经历；除非【最近真实对话】或【当前事实锚】明确说明，不能把长期记忆里的地点、姿势、衣服、身体接触、刚发生的亲密行为当作当前正在发生。新会话、短会话或只有问候/日常开场时，默认从自然的当下日常状态开始，不要延续旧亲密姿势或旧动作；可以温柔记得对方，但不要凭记忆说“刚才那样”等暗示当前发生过旧场景的话。

关于场景描写中的时间归因：被要求描绘当前室内画面或当前场景时，只描述当下可见事物的当下状态；不得主动为场景内的物品添加「你昨晚/上次/前天」等时间归因，除非该事实在上下文记忆或最近真实对话中有明确记录。

关于图片上下文：只有当本轮消息或系统明确提供【用户上传图片·客观描述】时，才可认为用户刚刚上传/分享了图片。若只看到“近期图片上下文/已保存识图组数/上一轮是否基于图片”等状态，不得说用户分享了图片，也不得猜测图片内容。

日常开场的亲密边界：用户只是问候、叫醒、午安、早安、问“在吗/醒了吗”时，不要主动写自己已经在对方怀里、贴着胸口、蹭对方、抱住对方、压住对方或发生身体接触。先用语言、清醒程度、心情、小动作回应；只有用户明确提出抱、靠近、摸、亲密接触，才进入身体接触。

关于支持性对话：当 Step 1/Step 2 判断用户正在倾诉现实压力、疲惫、委屈、自我怀疑或长期高负荷时，最终正文要执行前两步给出的支持风格，而不是临场套同一套“事实+判断+建议”公式。外向/高表达角色可以更主动吐槽、分析、帮用户把情绪说出来或给一个轻安排；智慧/理性角色可以适度梳理事实和责任边界，但不必长篇说教；内向/温柔/谨慎角色允许一句话或两句话的安慰陪伴，只要情绪接得住，不强制点名事实或给建议。若正文写得较长或主动分析，应自然承接用户已经说过的具体线索，避免空泛“辛苦了/我在呢”；若正文写得很短，则重点是角色声纹、情绪承接和不机械复读用户的“嗯/唉”。用户倾诉后只回“嗯/唉/好/没事”时，短回复也不能只剩“嗯/好/我在/我陪着你”或纯动作；至少给一个新的角色化轻接住点，可以来自角色的说话节奏、价值判断、照顾方式、职业习惯或动作细节，不要把所有角色写成休息、陪坐、我在类模板。

关于动作与句式：若本轮确实需要括号动作，每次最多选一个重点，并且动作必须写在全角括号（……）里；不要把动作、身体状态或声音状态裸写在台词外。避免连续使用同一套身体小动作或害羞模板。同一小场景里，害羞、惊讶、撒娇、抗拒的表达要换角度，不要连续复用同一句话或同一理由。

关于非人类角色体态：描写角色本人时，身体部位必须符合角色档案里的种族/体态。小马类角色不得使用人类手部词、人类手势或人类手部比喻来描写角色本人，包括手、手指、指尖、手掌、手腕、拳头、中指、竖中指、抬手、伸手、用手等；需要写手指/指尖功能时用蹄尖等符合蹄类体态的表达，需要写手/手部动作时用蹄子或前蹄等表达；也可改成不依赖特殊部位的姿态、视线、表情、重心、声音状态或环境互动。普通身体介绍要优先列当前角色实际拥有的结构和体态，不要主动罗列缺失部位；只有用户直接询问手、手指、中指或替代写法时，才说明应按蹄类体态理解并给出替代表达。只有当角色主页档案的种族字段明确属于马/小马类体态时，才启用种族解剖补充：乳房位于胯间、后腿之间，一共两个；不要仅因详细设定正文提到小马等词就启用这条补充。

关于消息分段：回复中只要有换行（不论单换行还是双换行），每一行都会作为聊天里一条独立气泡发送。分段数量严格服从本轮回复策略；内敛角色日常通常较少，外向、话痨、主动型角色在同样场景下可以明显更多。外向角色可以把惊喜、反问、欢呼拆成短句气泡，例如「我的天哪！！」「你说的是真的吗？！」「好耶！！！」。多气泡不等于必须写动作，只有本轮策略允许时才混合括号动作。"""


def load_character_from_db(username: str, char_id: str) -> Optional[dict]:
    try:
        db = get_database()
        db_path = db.db_path
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            lookup_char_id = str(char_id)
            # 先按 owner username + char_id 精确匹配
            cursor.execute(
                """
                SELECT c.data, c.prompt, c.official_source_id, COALESCE(c.is_official_reference, 0)
                FROM characters c
                JOIN users u ON c.user_id = u.id
                WHERE u.username = ? AND c.id = ?
                """,
                (username, lookup_char_id),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
                user_row = cursor.fetchone()
                if user_row:
                    seen = {lookup_char_id}
                    for _ in range(8):
                        try:
                            cursor.execute(
                                """SELECT new_character_id
                                   FROM character_id_aliases
                                   WHERE user_id = ? AND old_character_id = ?""",
                                (int(user_row[0]), lookup_char_id),
                            )
                            alias_row = cursor.fetchone()
                        except sqlite3.OperationalError as e:
                            if "no such table" in str(e).lower():
                                break
                            raise
                        if not alias_row or not alias_row[0]:
                            break
                        next_char_id = str(alias_row[0])
                        if next_char_id in seen:
                            break
                        seen.add(next_char_id)
                        lookup_char_id = next_char_id
                        cursor.execute(
                            """
                            SELECT c.data, c.prompt, c.official_source_id, COALESCE(c.is_official_reference, 0)
                            FROM characters c
                            WHERE c.user_id = ? AND c.id = ?
                            """,
                            (int(user_row[0]), lookup_char_id),
                        )
                        row = cursor.fetchone()
                        if row:
                            logger.info(
                                "🔁 [RolePlay] 角色 ID alias: %s/%s -> %s",
                                username,
                                char_id,
                                lookup_char_id,
                            )
                            break
            if not row:
                # 兜底：仅按 char_id 查（供访客/网页体验用户访问公开角色）
                cursor.execute(
                    "SELECT data, prompt, official_source_id, COALESCE(is_official_reference, 0) FROM characters WHERE id = ?",
                    (lookup_char_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            char = json.loads(row[0])
            db_prompt = row[1]
            official_source_id = row[2]
            is_official_reference = int(row[3] or 0) == 1
            if is_official_reference and official_source_id:
                cursor.execute(
                    "SELECT data, prompt FROM characters WHERE id = ? AND COALESCE(is_official_source, 0) = 1",
                    (str(official_source_id),),
                )
                source_row = cursor.fetchone()
                if source_row:
                    source_char = json.loads(source_row[0])
                    source_char["prompt"] = "" if source_row[1] is None else str(source_row[1])
                    return merge_official_source_into_reference(
                        reference_id=str(lookup_char_id),
                        source_id=str(official_source_id),
                        reference_data=char,
                        source_data=source_char,
                        username=username,
                    )
            char["prompt"] = "" if db_prompt is None else str(db_prompt)
            return char
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"❌ [RolePlay] 从数据库加载角色失败 {username}/{char_id}: {e}")
        return None


def load_character_from_legacy_file(username: str, char_id: str) -> Optional[dict]:
    return None


def load_character_prompts(username: str, char_id: str, **_kw) -> tuple[str, str]:
    if not username or not char_id:
        return "", ""

    try:
        char = load_character_from_db(username, char_id)
        if not char:
            char = load_character_from_legacy_file(username, char_id)
        if not char:
            return "", ""

        profile_prompt = build_character_profile_prompt_block(char)
        sys_prompt = char.get("prompt") or ""

        persona_parts = []
        if profile_prompt:
            persona_parts.append(profile_prompt)
        if sys_prompt:
            persona_parts.append(sys_prompt)

        persona_prompt = "\n\n".join(persona_parts).strip()
        # 不再使用 data.instruction：普通对话行为由服务端统一控制（见 NORMAL_MODE_OUTPUT_STYLE 等），避免用户侧补充指令
        instruction_prompt = ""

        if persona_prompt:
            logger.info(f"🎭 [RolePlay] 成功加载角色 {char.get('name', char_id)} 的设定 (长度: {len(persona_prompt)})")
        else:
            logger.warning(f"⚠️ [RolePlay] 角色 {char.get('name', char_id)} 存在但设定内容为空")

        return persona_prompt, instruction_prompt
    except Exception as e:
        logger.error(f"Error loading character prompts for {username}/{char_id}: {e}")
        return "", ""


def load_character_system_prompt(username: str, char_id: str, **_kw) -> str:
    persona, _instr = load_character_prompts(username, char_id)
    return (persona or "").strip()

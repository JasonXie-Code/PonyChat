"""Shared wire requirements for the game Agent and existing response validator."""
from .constants import (
    _DEFAULT_CHAR_MOOD, _DEFAULT_CHAR_VITALS, _DEFAULT_ORGAN_FILL,
    _required_event_flag_keys,
)

REQUIRED_TOP_FIELDS = (
    "score", "scene", "relationship_stage", "mood", "character_pose", "player_pose",
    "character_position", "player_position", "character_gender", "player_gender",
    "character_race", "player_race", "character_outfit", "player_outfit", "memory_tags",
    "event_flags", "score_delta_reason", "suggested_options",
)
REQUIRED_SCENE_FIELDS = (
    "time", "location", "env", "thoughts", "body_state", "third_party_dialogue", "response",
)
POSE_MAX_CHARS = 10
POSITION_MAX_CHARS = 16

THOUGHTS_VOICE = (
    "thoughts是当前角色尚未说出口、面向眼前玩家的心里话，和response使用同一组我/你视角。"
    "把它写成心里对你说的话，不写成向旁观者介绍玩家的日记或Agent分析。"
    "角色的感受、猜测、回忆和愿望都由我表达；其中被关心、被回想或被猜测的当前玩家始终是你。"
    "例如玩家说‘我抱住你’，心理可以是‘你抱住我的那一刻，我忽然安心了些。’；"
    "玩家问起喜欢的书，心理可以是‘原来你也喜欢星星，我想把珍藏的星图拿给你看。’。"
    "不要用玩家姓名、性别代词或‘这位客人/对方’绕开你。真正提及第三者时保留其姓名和正确人称，"
    "不把第三者改成玩家，也不照抄历史心理栏的人称。心里话不能冒充已经说出口的话或已经发生的行动。"
    "心理栏不使用台词引号；response中真正说出口的对白仍必须放在中文双引号内，动作留在引号外，不能照搬心理栏的无引号格式。"
    "本轮用户或当前有效个人偏好明确指定其他叙事视角时按其要求。"
)


def restore_scene_siblings(data: dict, mode: str) -> dict:
    """Recover only unambiguous known siblings swallowed by a missing scene brace.

    No values or missing fields are invented, and conflicting copies stay invalid.
    The normal complete-snapshot and trusted settlement checks still run afterward.
    """
    scene = data.get('scene')
    if not isinstance(scene, dict) or not set(REQUIRED_SCENE_FIELDS).issubset(scene):
        return data
    siblings = set(scene) - set(REQUIRED_SCENE_FIELDS)
    allowed = set(game_output_contract(mode)['required_top_fields']) - {'score', 'scene'}
    if not siblings or not siblings.issubset(allowed) or siblings.intersection(data):
        return data
    return {**data, **{key: scene[key] for key in siblings},
            'scene': {key: value for key, value in scene.items() if key not in siblings}}


def game_output_contract(mode: str) -> dict:
    """A schema guide, not a sample story or a server-generated replacement response."""
    fields = [*REQUIRED_TOP_FIELDS, "character_action", "player_action"]
    objects = {"score": ["current", "change", "status"],
               "scene": list(REQUIRED_SCENE_FIELDS),
               "event_flags": list(_required_event_flag_keys(mode))}
    if mode == "galgame_lock":
        for key, defaults in (("char_vitals", _DEFAULT_CHAR_VITALS),
                              ("char_mood", _DEFAULT_CHAR_MOOD), ("organ_fill", _DEFAULT_ORGAN_FILL)):
            fields.append(key)
            objects[key] = list(defaults)
    return {"delivery": "one_complete_json_object_every_turn_not_a_patch",
            "required_top_fields": fields, "required_object_keys": objects,
            "suggested_options": "恰好5个可点击的玩家选项，不输出视角提醒；选项我=玩家，你=角色",
            "scene_perspective": "response/body_state/thoughts：我=当前角色，你=当前玩家，包括引号外的动作与心理；只有真实第三者用姓名或他/她。用户明确指定其他视角时按其要求。",
            "scene_boundary": "scene仅包含七个场景文本字段，response后关闭scene；其余字段在顶层，与scene同级，终局也不例外",
            "compact_text_max_chars": {"character_pose": POSE_MAX_CHARS, "player_pose": POSE_MAX_CHARS,
                                       "character_position": POSITION_MAX_CHARS, "player_position": POSITION_MAX_CHARS},
            "length_rule": "去除空白后计数，标点也占一个字符",
            "unchanged_fields": "沿用已保存事实并写出值，不省略，不写同上或省略号",
            "unknown_facts": "无法从对话或状态确认的性别、种族、服装等填未明确，不编造具体事实"}

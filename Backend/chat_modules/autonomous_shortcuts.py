"""Shortcut-message contracts at the autonomous Agent entry."""
import json
import re

_DESCRIPTION_SHORTCUTS = {
    "（请详细写出当前你的心理活动）",
    "（请详细写出当前你的身体状态）",
    "（请详细写出当前你看到的画面）",
    "（请详细描写出当前你的心理活动）",
    "（请详细描写出当前你的身体状态）",
    "（请详细描写出当前你看到的画面）",
}
_STORY_SHORTCUT = "（请推进剧情发展）"


def _shortcut_text(text):
    return re.sub(r"^\s*[@＠][^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+[\s,，:：、]*", "", str(text or "")).strip()


def is_description_shortcut(text):
    return _shortcut_text(text) in _DESCRIPTION_SHORTCUTS


def is_story_shortcut(text):
    return _shortcut_text(text) == _STORY_SHORTCUT


class ShortcutContract:
    def __init__(self, messages, profile, *, speaker, main):
        from . import normal_nonstream as legacy
        from .autonomous_delivery import delivery_state
        self.legacy = legacy
        self.history = messages
        self.scope = dict(current_speaker_character_id=speaker, main_character_id=main)
        text = next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'), '')
        self.description = is_description_shortcut(text)
        self.story = is_story_shortcut(text)
        self.species = legacy._extract_current_character_species_from_messages([{'role':'system','content':profile}])
        canonical = text.replace('详细描写出', '详细写出')
        self.target = legacy._description_shortcut_target(canonical)
        state = delivery_state(messages, speaker=speaker, main=main)
        self.delivery = {
            "voice_reply": {"enabled": False if self.description else state["voice_reply"]},
            "reply_language": {"language": state["previous_reply_language"]},
        }
        self.guidance = ''
        if self.description or self.story:
            self.guidance = legacy._normalize_description_shortcut_user_message(canonical, character_species=self.species)
            if self.description:
                self.guidance += '\n' + legacy._description_shortcut_stage3_contract(
                    character_species=self.species, target=self.target)
                self.guidance += '\n本轮为描写快捷消息时，固定输出3个气泡，每个气泡恰好一个纯描写片段；心理用thought，身体用body_state，所见画面用visual。生成text时不写括号、speech、引号内对白或对用户说话的内容；括号由后端添加。'
            self.guidance += '\n本轮承载和语言合同：' + json.dumps(self.delivery, ensure_ascii=False)
            self.guidance += '\n本轮是快捷消息时，只用所要求的文字和描写，不输出emoji、颜文字或图片表情包；下一次恢复普通聊天时，按当轮表达规则处理。'

    def error(self, envelope):
        if not (self.description or self.story):
            return ''
        from .expression_context import emoji_symbols
        if any(emoji_symbols(p['text']) for b in envelope.get('bubbles',[]) for p in b.get('parts',[])):
            return '快捷消息本回合禁止emoji；请用文字描写表达，不替换成图片表情包'
        bubbles = envelope.get('bubbles', [])
        if not bubbles:
            return '快捷消息必须直接呈现请求的描写或具体进展，不能沉默'
        if self.description:
            if envelope.get('bubble_count') != 3 or len(bubbles) != 3:
                return '描写快捷消息固定3个气泡，每个气泡一段纯描写，不能少于或多于3段'
            if any(len(b['parts']) != 1 or b['parts'][0]['kind'].strip().lower()=='speech' for b in bubbles):
                return '描写快捷消息每个气泡必须恰好一个非speech片段，不得包含台词'
            text = '\n'.join(p['text'] for b in bubbles for p in b['parts'])
            if re.search('[“”「」『』"]', text):
                return '描写快捷消息不得夹入引号台词；把感受与画面写成连续叙述，不代替角色说话'
            error = self.legacy._description_reply_violation_reason(text, character_species=self.species)
            if error:
                return error
        expected_voice = self.delivery.get('voice_reply')
        if expected_voice and envelope.get('voice_reply',{}).get('enabled') != expected_voice.get('enabled'):
            return '快捷消息必须遵守本轮临时文本/原语音惯性合同，不得切换后续承载方式'
        language = self.delivery.get('reply_language',{}).get('language')
        if language and envelope.get('reply_language',{}).get('language','').lower() != language.lower():
            return '快捷消息不是语言切换，必须继承快捷消息前的回复语言：' + language
        return ''

    def delivery_error(self, data):
        """Only the explicitly requested shortcut has a fixed structural gate."""
        if not self.description:
            return ''
        return self.error(data)

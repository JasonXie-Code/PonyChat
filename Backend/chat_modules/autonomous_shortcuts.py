"""Shortcut-message contracts at the autonomous Agent entry."""
from .Prompts import AUTONOMOUS_SHORTCUTS_TEXT, shortcut
import json
import re

_DESCRIPTION_SHORTCUTS = {
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_1'],
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_2'],
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_3'],
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_4'],
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_5'],
    AUTONOMOUS_SHORTCUTS_TEXT['DESCRIPTION_SHORTCUTS_6'],
}
_STORY_SHORTCUT = "（请推进剧情发展）"



def _shortcut_text(text):
    return re.sub(r"^\s*[@＠][^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+[\s,，:：、]*", "", str(text or "")).strip()


def is_description_shortcut(text):
    return _shortcut_text(text) in _DESCRIPTION_SHORTCUTS


def is_story_shortcut(text):
    return _shortcut_text(text) == _STORY_SHORTCUT


def _character_species(profile):
    """Read the current profile only; shortcut handling has no old reply dependency."""
    text = str(profile or "")
    match = re.search(r"(?:profileSpecies|种族)['\"]?\s*[：:]\s*['\"]?([^'\"\n\r,，。；;}]+)", text, re.I)
    return match.group(1).strip() if match else ""


def _shortcut_target(text):
    if "身体状态" in str(text):
        return "身体状态"
    if "看到的画面" in str(text):
        return "看到的画面"
    return "心理活动"


def _description_guidance(text, species, target):
    if is_story_shortcut(text):
        return shortcut + AUTONOMOUS_SHORTCUTS_TEXT['dynamic_story']
    return (shortcut + AUTONOMOUS_SHORTCUTS_TEXT['dynamic_description']
            + AUTONOMOUS_SHORTCUTS_TEXT['dynamic_target'] + target + "。"
            + AUTONOMOUS_SHORTCUTS_TEXT['dynamic_species'] + (species or "未知") + "。")


def _description_error(text, species):
    text = str(text or "")
    if re.search(r"(系统提示|系统通知|后台通知|提示词|改写说明|模型身份|好友申请通知)", text):
        return AUTONOMOUS_SHORTCUTS_TEXT['description_error_1']
    return ""


class ShortcutContract:
    def __init__(self, messages, profile, *, speaker, main):
        from .autonomous_delivery import delivery_state
        self.history = messages
        self.scope = dict(current_speaker_character_id=speaker, main_character_id=main)
        text = next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'), '')
        self.description = is_description_shortcut(text)
        self.story = is_story_shortcut(text)
        self.species = _character_species(profile)
        canonical = text.replace('详细描写出', '详细写出')
        self.target = _shortcut_target(canonical)
        state = delivery_state(messages, speaker=speaker, main=main)
        self.delivery = {
            "voice_reply": {"enabled": False if self.description else state["voice_reply"]},
            "reply_language": {"language": state["previous_reply_language"]},
        }
        self.guidance = ''
        if self.description or self.story:
            self.guidance = _description_guidance(canonical, self.species, self.target)
            self.guidance += '\n本轮承载和语言合同：' + json.dumps(self.delivery, ensure_ascii=False)

    def error(self, envelope):
        if not (self.description or self.story):
            return ''
        from .expression_context import emoji_symbols
        if any(emoji_symbols(p['text']) for b in envelope.get('bubbles',[]) for p in b.get('parts',[])):
            return AUTONOMOUS_SHORTCUTS_TEXT['error_1']
        bubbles = envelope.get('bubbles', [])
        if not bubbles:
            return AUTONOMOUS_SHORTCUTS_TEXT['error_2']
        if self.description:
            if envelope.get('bubble_count') != 3 or len(bubbles) != 3:
                return AUTONOMOUS_SHORTCUTS_TEXT['error_4']
            if any(len(b['parts']) != 1 or b['parts'][0]['kind'].strip().lower()=='speech' for b in bubbles):
                return AUTONOMOUS_SHORTCUTS_TEXT['error_5']
            expected_kind = {'心理活动': 'thought', '身体状态': 'body_state', '看到的画面': 'visual'}[self.target]
            if any(b['parts'][0]['kind'].strip().lower() != expected_kind for b in bubbles):
                return AUTONOMOUS_SHORTCUTS_TEXT['target_kind_error'] + expected_kind
            text = '\n'.join(p['text'] for b in bubbles for p in b['parts'])
            if re.search('[“”「」『』"]', text):
                return AUTONOMOUS_SHORTCUTS_TEXT['error_6']
            error = _description_error(text, self.species)
            if error:
                return error
        expected_voice = self.delivery.get('voice_reply')
        if expected_voice and envelope.get('voice_reply',{}).get('enabled') != expected_voice.get('enabled'):
            return AUTONOMOUS_SHORTCUTS_TEXT['error_3']
        language = self.delivery.get('reply_language',{}).get('language')
        if language and envelope.get('reply_language',{}).get('language','').lower() != language.lower():
            return AUTONOMOUS_SHORTCUTS_TEXT['error_7'] + language
        return ''

    def delivery_error(self, data):
        """Only the explicitly requested shortcut has a fixed structural gate."""
        if not self.description:
            return ''
        return self.error(data)

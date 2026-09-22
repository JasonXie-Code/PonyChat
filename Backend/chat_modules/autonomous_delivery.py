"""Apply the replying Agent's language/modality decision to existing TTS delivery."""
import json
import re

from .text_limits import truncate_prompt_text

# 语音风格提示的长度上限；裁剪必须停在词边界，不能把单词切成半个。
EMOTION_PROMPT_MAX_CHARS = 100
# 决策没有给出风格提示时的兜底 instruct（验收脚本也用它判断“用了兜底”而非“丢了提示”）。
DEFAULT_EMOTION_PROMPT = "Warm, relaxed, conversational."

def _speaker_matches(message, *, speaker, main):
    message_speaker = str(message.get("speaker_character_id") or message.get("speakerCharacterId") or main or "")
    return not speaker or message_speaker == str(speaker)


def delivery_state(history, *, speaker, main):
    """Read the current speaker's last visible delivery mode and language."""
    from .autonomous_shortcuts import is_description_shortcut
    history = history or []
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if not _speaker_matches(message, speaker=speaker, main=main):
            continue
        preceding_user = next((m for m in reversed(history[:index])
                               if isinstance(m, dict) and m.get("role") == "user"), {})
        if is_description_shortcut(preceding_user.get("content", "")):
            continue
        content = str(message.get("content") or "")
        status = str(message.get("voice_status") or message.get("voiceStatus") or "").lower()
        voice_state = message.get("voice_state") or message.get("voiceState") or {}
        if isinstance(voice_state, dict):
            status = str(voice_state.get("voice_status") or voice_state.get("voiceStatus") or voice_state.get("status") or status).lower()
        is_voice = bool(message.get("audio_transfer") or message.get("audioTransfer")) or status in {"ready", "generated", "playing", "voice"}
        break
    else:
        is_voice = False
    from .reply_language_state import language_metadata, infer_legacy_language, voice_metadata
    language_rows = []
    for index, message in enumerate(history):
        if not isinstance(message, dict) or message.get('role') != 'assistant' or not _speaker_matches(message, speaker=speaker, main=main):
            continue
        user = next((m for m in reversed(history[:index]) if isinstance(m, dict) and m.get('role') == 'user'), {})
        if not is_description_shortcut(user.get('content', '')):
            language_rows.append(message)
    for message in reversed(language_rows):
        voice = voice_metadata(message.get('voice_reply'))
        if voice:
            is_voice = voice['continuation_enabled']
            break
    # Recorded decisions take precedence over guesses from newer legacy text.
    for message in reversed(language_rows):
        meta = language_metadata(message.get('reply_language'))
        if meta:
            return {'voice_reply': is_voice, 'previous_reply_language': meta['continuation_language'],
                    'has_delivery_history': bool(language_rows), 'has_language_history': True}
    for message in reversed(language_rows):
        language = infer_legacy_language(message.get('content'))
        if language:
            return {'voice_reply': is_voice, 'previous_reply_language': language,
                    'has_delivery_history': bool(language_rows), 'has_language_history': True}
    return {'voice_reply': is_voice, 'previous_reply_language': 'Chinese',
            'has_delivery_history': bool(language_rows), 'has_language_history': False}



def configure_delivery(request, result):
    # Raw output is retained for audit and may lack a safely recovered closer.
    # Delivery must use the already validated envelope, including its metadata.
    envelope = json.loads(result["envelope"])
    voice = envelope.get("voice_reply") if isinstance(envelope.get("voice_reply"), dict) else {}
    language = envelope.get("reply_language") if isinstance(envelope.get("reply_language"), dict) else {}
    from .reply_language_state import language_metadata, voice_metadata
    request._normal_reply_language = language_metadata(language)
    request._normal_reply_voice = voice_metadata(voice)
    enabled = voice.get("enabled") is True and getattr(request, "voice_enabled", None) is not False
    request._normal_planner_result.update({"reply_language": {"language": str(language.get("language") or "auto")[:40],
        "reason": str(language.get("reason") or "")[:300]},
        "voice_reply": {"enabled": enabled, "reason": str(voice.get("reason") or "agent_delivery_choice")[:300]}})
    sentences = {}
    if enabled:
        emotion = truncate_prompt_text(
            voice.get("emotion_prompt") or DEFAULT_EMOTION_PROMPT,
            EMOTION_PROMPT_MAX_CHARS,
        )
        for index, bubble in enumerate(envelope["bubbles"]):
            entries = [{"text": part["text"], "emotion_prompt": emotion}
                       for part in bubble["parts"] if part["kind"] == "speech"]
            if entries:
                sentences[index] = entries
    request._normal_voice_sentences_by_text_index = sentences


def agent_delivery_guidance(history, *, speaker, main):
    state = delivery_state(history, speaker=speaker, main=main)
    return "【当前角色回复状态】\n" + json.dumps(state, ensure_ascii=False)

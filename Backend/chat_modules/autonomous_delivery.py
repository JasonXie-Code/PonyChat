"""Apply the replying Agent's language/modality decision to existing TTS delivery."""
from .Prompts import LANGUAGE_CONTINUITY_RULE

import json
import re

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
        if re.search(r"[\u3040-\u30ff]", content):
            language = "Japanese"
        elif re.search(r"[\u0400-\u04ff]", content):
            language = "Russian"
        elif re.search(r"[\u4e00-\u9fff]", content):
            language = "Chinese"
        elif re.search(r"[A-Za-z]", content):
            language = "English"
        else:
            language = "Chinese"
        return {"voice_reply": is_voice, "previous_reply_language": language,
                "has_delivery_history": True, "has_language_history": bool(content)}
    return {"voice_reply": False, "previous_reply_language": "Chinese",
            "has_delivery_history": False, "has_language_history": False}


def configure_delivery(request, result):
    # Raw output is retained for audit and may lack a safely recovered closer.
    # Delivery must use the already validated envelope, including its metadata.
    envelope = json.loads(result["envelope"])
    voice = envelope.get("voice_reply") if isinstance(envelope.get("voice_reply"), dict) else {}
    language = envelope.get("reply_language") if isinstance(envelope.get("reply_language"), dict) else {}
    enabled = voice.get("enabled") is True and getattr(request, "voice_enabled", None) is not False
    request._normal_planner_result.update({"reply_language": {"language": str(language.get("language") or "auto")[:40],
        "reason": str(language.get("reason") or "")[:300]},
        "voice_reply": {"enabled": enabled, "reason": str(voice.get("reason") or "agent_delivery_choice")[:300]}})
    sentences = {}
    if enabled:
        emotion = str(voice.get("emotion_prompt") or "Warm, relaxed, conversational.").strip()[:100]
        for index, bubble in enumerate(envelope["bubbles"]):
            entries = [{"text": part["text"], "emotion_prompt": emotion}
                       for part in bubble["parts"] if part["kind"] == "speech"]
            if entries:
                sentences[index] = entries
    request._normal_voice_sentences_by_text_index = sentences


def agent_delivery_guidance(history, *, speaker, main, include_rules=True):
    state = delivery_state(history, speaker=speaker, main=main)
    if not include_rules:
        return "【当前角色回复状态】\n" + json.dumps(state, ensure_ascii=False)
    return "\n" + LANGUAGE_CONTINUITY_RULE + "\n【当前角色回复状态】\n" + json.dumps(state, ensure_ascii=False)

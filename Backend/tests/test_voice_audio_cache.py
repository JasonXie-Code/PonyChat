from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace

import aiosqlite

from Backend.audio_normalization import AudioSilenceStats
from Backend import voice_lab_client
from Backend.chat_modules import voice_messages
from Backend.db.message_voice_audio_cache import (
    acknowledge_voice_audio_cache,
    audio_cache_to_transfer,
    load_voice_audio_cache,
    store_voice_audio_cache,
)
from Backend.voice_lab_client import (
    VOICE_DISABLED_MESSAGE,
    _build_tts_payload,
    _qwen3tts_pause_text,
    _run_tts_job,
    _segmented_crossfade_ms,
    _segmented_gap_ms,
    _tts_temperature_for_engine,
    _variant,
    _voice_quality_max_silence_ratio,
    is_voice_lab_enabled,
)
from Backend.qwen_tts_online_client import (
    build_qwen_tts_online_payload,
    normalize_qwen_tts_online_voice,
)


class _TestDb:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        return None

    async def close(self):
        return None


def test_voice_audio_cache_disabled_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PONYCHAT_CHAT_VOICE_SERVER_CACHE_ENABLED", raising=False)

    async def run():
        db = _TestDb(str(tmp_path / "ponychat_voice_cache_disabled.db"))
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                """CREATE TABLE message_voice_audio_cache (
                    voice_cache_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'audio/mpeg',
                    variant TEXT,
                    audio_data BLOB NOT NULL,
                    byte_size INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_delivered_at INTEGER,
                    delivered_count INTEGER NOT NULL DEFAULT 0,
                    expires_at INTEGER
                )"""
            )
            await conn.commit()

        await store_voice_audio_cache(
            db,
            username="test",
            character_id="fluttershy",
            conversation_id="conv_voice_cache",
            message_id="msg_voice_cache",
            voice_cache_key="voice-cache-key",
            audio_bytes=b"fake-audio",
            mime_type="audio/mpeg",
            variant="qwen3tts",
        )

        cached = await load_voice_audio_cache(
            db,
            username="test",
            character_id="fluttershy",
            conversation_id="conv_voice_cache",
            message_id="msg_voice_cache",
            voice_cache_key="voice-cache-key",
            mark_delivered=True,
        )
        assert cached is None
        assert audio_cache_to_transfer(cached) is None

        removed = await acknowledge_voice_audio_cache(
            db,
            username="test",
            character_id="fluttershy",
            conversation_id="conv_voice_cache",
            message_id="msg_voice_cache",
            voice_cache_key="voice-cache-key",
        )
        assert removed == 0

        async with aiosqlite.connect(db.db_path) as conn:
            row = await (await conn.execute("SELECT COUNT(*) FROM message_voice_audio_cache")).fetchone()
            assert row[0] == 0
        await db.close()

    asyncio.run(run())


def test_recover_pending_voice_messages_uses_persisted_voice_sentences(tmp_path: Path, monkeypatch):
    async def run():
        db = _TestDb(str(tmp_path / "ponychat_pending_voice.db"))
        now_ms = int(time.time() * 1000)
        sentences = [{"text": "你好，我会继续发语音。", "emotion_prompt": "温柔"}]
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL
                );
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL
                );
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    deleted_at TIMESTAMP,
                    is_hidden INTEGER DEFAULT 0
                );
                CREATE TABLE message_voice_states (
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    voice_status TEXT NOT NULL DEFAULT 'disabled',
                    voice_id TEXT,
                    voice_job_id TEXT,
                    voice_cache_key TEXT,
                    tts_text TEXT,
                    transcript TEXT,
                    text_fragments_json TEXT NOT NULL DEFAULT '[]',
                    voice_error TEXT,
                    updated_at INTEGER NOT NULL,
                    voice_sentences_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (conversation_id, message_id)
                );
                """
            )
            await conn.execute("INSERT INTO users (id, username) VALUES (1, 'tester')")
            await conn.execute(
                "INSERT INTO conversations (id, character_id, user_id) VALUES ('conv', 'char', 1)"
            )
            await conn.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, message_id, deleted_at, is_hidden)
                   VALUES ('row1', 'conv', 'assistant', 'fallback text', 'msg1', NULL, 0)"""
            )
            await conn.execute(
                """INSERT INTO message_voice_states
                   (conversation_id, message_id, voice_status, voice_id, tts_text, transcript,
                    text_fragments_json, voice_error, updated_at, voice_sentences_json)
                   VALUES ('conv', 'msg1', 'pending', 'ponyvoice:char', '你好，我会继续发语音。',
                           '你好，我会继续发语音。', '[]', NULL, ?, ?)""",
                (now_ms - 60_000, json.dumps(sentences, ensure_ascii=False)),
            )
            await conn.commit()

        monkeypatch.setattr(voice_messages, "get_database", lambda: db)
        calls = []

        async def fake_synthesize_message_voice(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "voice_state": {"voice_status": "ready"}, "audio_transfer": {"kind": "bytes"}}

        monkeypatch.setattr(voice_messages, "synthesize_message_voice", fake_synthesize_message_voice)
        recovered = await voice_messages.recover_pending_voice_messages(limit=3, min_age_seconds=1)

        assert recovered == 1
        assert len(calls) == 1
        assert calls[0]["username"] == "tester"
        assert calls[0]["character_id"] == "char"
        assert calls[0]["voice_id"] == "ponyvoice:char"
        assert calls[0]["voice_sentences"] == sentences

    asyncio.run(run())


def test_qwen3tts_temperature_is_low_for_voice_stability():
    assert _tts_temperature_for_engine("qwen3tts") == 0.05
    assert _tts_temperature_for_engine("QWEN3TTS") == 0.05
    assert _tts_temperature_for_engine("omnivoice") == 0.9


def test_voice_silence_qc_default_threshold_is_30_percent(monkeypatch):
    monkeypatch.delenv("PONYCHAT_VOICE_MAX_SILENCE_RATIO", raising=False)

    assert _voice_quality_max_silence_ratio() == 0.30


def test_run_tts_job_regenerates_audio_when_silence_ratio_exceeds_threshold(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_MAX_SILENCE_RATIO", "0.30")
    monkeypatch.setenv("PONYCHAT_VOICE_MAX_SILENCE_REGENERATIONS", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_MIN_QC_DURATION_SECONDS", "0")

    def fake_probe(audio_bytes: bytes, **kwargs):
        if audio_bytes == b"silent-audio":
            return AudioSilenceStats(duration_seconds=10.0, silence_seconds=3.1, silence_ratio=0.31)
        return AudioSilenceStats(duration_seconds=10.0, silence_seconds=0.5, silence_ratio=0.05)

    class FakeResponse:
        def __init__(self, payload=None, content=b"", headers=None, status_code=200):
            self._payload = payload or {}
            self.content = content
            self.headers = headers or {}
            self.status_code = status_code
            self.text = ""

        def json(self):
            return self._payload

    class FakeAsyncClient:
        post_count = 0

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, **kwargs):
            return await getattr(self, method.lower())(url, **kwargs)

        async def post(self, url, json=None, data=None, files=None):
            type(self).post_count += 1
            return FakeResponse({"job_id": f"job-{type(self).post_count}", "status": "completed"})

        async def get(self, url, params=None):
            content = b"silent-audio" if type(self).post_count == 1 else b"clean-audio"
            return FakeResponse(content=content, headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(voice_lab_client, "probe_audio_silence_stats", fake_probe)
    monkeypatch.setattr(voice_lab_client.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        _run_tts_job(
            base="https://voice.example",
            create_path="/jobs/tts",
            payload={"text": "hello"},
            selected_variant="mobile",
            connect_timeout=1.0,
            job_timeout=1.0,
            poll_interval=0.0,
        )
    )

    assert result.job_id == "job-2"
    assert result.audio_bytes == b"clean-audio"
    assert FakeAsyncClient.post_count == 2


def test_segmented_qwen3tts_payload_uses_stable_temperature_and_min_breath_gap(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_SEGMENT_GAP_MS", "120")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_SEGMENT_CROSSFADE_MS", "75")

    payload = _build_tts_payload(
        engine="qwen3tts",
        voice_id="紫悦",
        selected_variant="mobile",
        language="英文",
        segments=[
            {"text": "第一句。", "instruct": "温柔"},
            {"text": "第二句。", "instruct": "开心"},
        ],
    )

    assert payload["temperature"] == 0.05
    assert payload["top_k"] == 10
    assert payload["top_p"] == 0.75
    assert payload["language"] == "English"
    assert payload["mobile_microphone"] is True
    assert payload["gap_ms"] == 600
    assert payload["crossfade_ms"] == 75
    assert payload["segments"] == [
        {"text": "第一句。", "instruct": "温柔"},
        {"text": "第二句。", "instruct": "开心"},
    ]
    assert "text" not in payload
    assert "instruct" not in payload
    assert _segmented_gap_ms() == 600
    assert _segmented_crossfade_ms() == 75


def test_voice_lab_default_variant_uses_original_audio(monkeypatch):
    monkeypatch.delenv("PONYCHAT_VOICE_LAB_DEFAULT_VARIANT", raising=False)

    assert _variant() == "original"

    payload = _build_tts_payload(
        engine="qwen3tts",
        voice_id="speaker:serena",
        selected_variant=_variant(),
        language="Chinese",
        text="你好",
    )

    assert payload["mobile_microphone"] is False


def test_qwen3tts_text_converts_dash_pauses_to_periods():
    assert _qwen3tts_pause_text("我想——也许可以。") == "我想。也许可以。"
    assert _qwen3tts_pause_text("Wait -- maybe.") == "Wait. maybe."

    payload = _build_tts_payload(
        engine="qwen3tts",
        voice_id="紫悦",
        selected_variant="original",
        language="Chinese",
        text="稍等——我马上来。",
    )
    assert payload["text"] == "稍等。我马上来。"

    segmented = _build_tts_payload(
        engine="qwen3tts",
        voice_id="紫悦",
        selected_variant="original",
        language="Chinese",
        segments=[
            {"text": "第一句——停一下。", "instruct": "温柔"},
            {"text": "第二句--继续。", "instruct": "开心"},
        ],
    )
    assert segmented["segments"] == [
        {"text": "第一句。停一下。", "instruct": "温柔"},
        {"text": "第二句。继续。", "instruct": "开心"},
    ]

    non_qwen_payload = _build_tts_payload(
        engine="omnivoice",
        voice_id="serena",
        selected_variant="original",
        text="keep -- dash",
    )
    assert non_qwen_payload["text"] == "keep -- dash"


def test_clone_voice_config_prefers_ponychat_recipe_over_registered_qwen_voice(monkeypatch):
    monkeypatch.setattr(
        voice_messages,
        "load_character_from_db",
        lambda username, character_id: {
            "voiceEnabled": True,
            "voiceSourceMode": "clone",
            "voiceId": "qwen3tts:PonyChat-test-Ziyue-a1b2c3d4",
            "voiceBaseVoiceId": "qwen3tts:紫悦",
            "voiceProfileId": "ponyvoice:ziyun",
            "voiceReferenceAudioUrl": "/character_voice_assets/ref.wav",
            "voiceReferenceText": "你好呀。",
        },
    )

    config = voice_messages._character_voice_config("test", "ziyun")

    assert config["enabled"] is True
    assert config["source_mode"] == "clone"
    assert config["voice_id"] == "ponyvoice:ziyun"
    assert config["base_voice_id"] == "qwen3tts:紫悦"


def test_design_voice_config_uses_registered_voice_without_reapplying_description(monkeypatch):
    monkeypatch.setattr(
        voice_messages,
        "load_character_from_db",
        lambda username, character_id: {
            "voiceEnabled": True,
            "voiceSourceMode": "instruct",
            "voiceId": "qwen3tts:PonyChat-test-Luna-design-ab12cd34",
            "voiceInstruct": "冷静、庄重、夜色感，语气自然",
            "voiceCloneStatus": "design_registered",
        },
    )

    config = voice_messages._character_voice_config("test", "luna")

    assert config["enabled"] is True
    assert config["source_mode"] == "instruct"
    assert config["voice_id"] == "qwen3tts:PonyChat-test-Luna-design-ab12cd34"
    assert config["instruct"] == ""


def test_cosyvoice_config_maps_legacy_qwen_official_voice_to_pony_profile(monkeypatch):
    monkeypatch.setenv("PONYCHAT_TTS_PROVIDER", "cosyvoice")
    monkeypatch.setattr(
        voice_messages,
        "load_character_from_db",
        lambda username, character_id: {
            "voiceEnabled": True,
            "voiceSourceMode": "voice_id",
            "voiceId": "qwen3tts:muffins",
        },
    )

    config = voice_messages._character_voice_config("test", "muffins")

    assert config["voice_profile_id"] == "ponyvoice:muffins"
    assert config["voice_id"] == "ponyvoice:muffins"


def test_sentence_voice_audio_keeps_timbre_guard_and_merges_short_segments(monkeypatch):
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    captured = {}

    async def fake_segmented_tts(*, segments, voice_id, variant=None, language=None):
        captured["segments"] = segments
        captured["voice_id"] = voice_id
        captured["variant"] = variant
        captured["language"] = language
        return SimpleNamespace(job_id="job-segmented", audio_bytes=b"mp3", mime_type="audio/mpeg", variant="mobile")

    monkeypatch.setattr(voice_messages, "synthesize_segmented_tts", fake_segmented_tts)

    result = asyncio.run(
        voice_messages._synthesize_sentence_voice_audio(
            sentences=[
                {"text": "诶？", "emotion_prompt": "保持原音色，能量稍高"},
                {"text": "真的？", "emotion_prompt": "保持原音色，停顿短促"},
                {"text": "那我马上把书拿过来，你先在这里等我一下哦。", "emotion_prompt": "保持原音色，语速自然"},
            ],
            voice_id="qwen3tts:紫悦",
            instruct="像紫悦一样温柔清晰",
            reply_language="English",
        )
    )

    assert result.job_id == "job-segmented"
    assert captured["voice_id"] == "qwen3tts:紫悦"
    assert captured["language"] == "English"
    assert [item["text"] for item in captured["segments"]] == [
        "诶？真的？",
        "那我马上把书拿过来，你先在这里等我一下哦。",
    ]
    assert "音色稳定规则" in captured["segments"][0]["instruct"]
    assert "本段台词很短" in captured["segments"][0]["instruct"]
    assert "本句表演提示：保持原音色，能量稍高；保持原音色，停顿短促" in captured["segments"][0]["instruct"]
    assert "本段台词很短" not in captured["segments"][1]["instruct"]
    assert "不要改变音色本身" in captured["segments"][1]["instruct"]


def test_single_short_phrase_stays_as_one_stable_segment(monkeypatch):
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    captured = {}

    async def fake_segmented_tts(*, segments, voice_id, variant=None, language=None):
        captured["segments"] = segments
        return SimpleNamespace(job_id="job-okay", audio_bytes=b"mp3", mime_type="audio/mpeg", variant="mobile")

    monkeypatch.setattr(voice_messages, "synthesize_segmented_tts", fake_segmented_tts)

    result = asyncio.run(
        voice_messages._synthesize_sentence_voice_audio(
            sentences=[{"text": "Okay.", "emotion_prompt": "保持原音色，轻轻确认"}],
            voice_id="qwen3tts:紫悦",
            instruct="像紫悦一样温柔清晰",
            reply_language="English",
        )
    )

    assert result.job_id == "job-okay"
    assert [item["text"] for item in captured["segments"]] == ["Okay."]
    assert "本段台词很短" in captured["segments"][0]["instruct"]
    assert "保持角色声纹一致" in captured["segments"][0]["instruct"]


def test_reply_language_is_extracted_from_planner_result():
    assert voice_messages._reply_language_from_planner({"reply_language": {"language": "English"}}) == "English"
    assert voice_messages._reply_language_from_planner({"reply_language": {"language": "auto"}}) == ""
    assert voice_messages._reply_language_from_planner({"reply_language": "中文"}) == "中文"


def test_voice_sync_timeout_default_is_180_seconds(monkeypatch):
    monkeypatch.delenv("PONYCHAT_CHAT_VOICE_SYNC_TIMEOUT_SECONDS", raising=False)
    assert voice_messages._voice_sync_timeout_seconds() == 180.0

    monkeypatch.setenv("PONYCHAT_CHAT_VOICE_SYNC_TIMEOUT_SECONDS", "bad")
    assert voice_messages._voice_sync_timeout_seconds() == 180.0

    monkeypatch.setenv("PONYCHAT_CHAT_VOICE_SYNC_TIMEOUT_SECONDS", "0.2")
    assert voice_messages._voice_sync_timeout_seconds() == 1.0


def test_prepare_voice_uses_sentence_entries_when_display_text_is_bracket(monkeypatch):
    captured = {}
    sentences = [
        {"text": "你好，我是月亮公主露娜。", "emotion_prompt": "保持原音色，庄严但温和"},
        {"text": "Hello, I am Princess Luna.", "emotion_prompt": "保持原音色，英文自然"},
    ]

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:princess_luna",
            "instruct": "可爱温柔的女声",
        },
    )
    monkeypatch.setattr(voice_messages, "is_voice_lab_available", lambda: True)

    async def fake_synthesize_message_voice(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "voice_state": {"voice_status": "ready"},
            "audio_transfer": {"kind": "bytes"},
        }

    monkeypatch.setattr(voice_messages, "synthesize_message_voice", fake_synthesize_message_voice)

    result = asyncio.run(
        voice_messages.prepare_voice_generation_for_messages(
            username="System",
            character_id="princess_luna",
            conversation_id="conv_voice",
            assistant_meta=[{"message_id": "msg_voice"}],
            assistant_units=[
                {
                    "type": "text",
                    "content": "（我说完轻轻垂下目光，等待你的回应）",
                    "voice_sentences": sentences,
                }
            ],
            planner_result={"voice_reply": {"enabled": True}},
            timeout_seconds=1,
        )
    )

    assert result["msg_voice"]["ok"] is True
    assert captured["content"] == "（我说完轻轻垂下目光，等待你的回应）"
    assert captured["voice_sentences"] == sentences


def test_synthesize_message_voice_can_return_transient_audio_without_db(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)

    async def fail_db_write(*args, **kwargs):
        raise AssertionError("transient synthesis must not write sqlite")

    async def fake_synthesize_tts(**kwargs):
        return SimpleNamespace(job_id="job-transient", audio_bytes=b"mp3-bytes", mime_type="audio/mpeg", variant="mobile")

    async def fake_load_character_voice_profile(db, profile_id):
        return None

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:princess_luna",
            "voice_profile_id": "",
            "instruct": "可爱温柔的女声",
        },
    )
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fail_db_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fail_db_write)
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fail_db_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fake_synthesize_tts)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="princess_luna__u_1",
            conversation_id="conv_locked",
            message_id="msg_transient_test",
            content="Hello, I am Princess Luna.",
            voice_id="ponyvoice:princess_luna",
            instruct="可爱温柔的女声",
            push_update=False,
            persist=False,
        )
    )

    assert result["ok"] is True
    assert result["voice_state"]["voice_status"] == "ready"
    assert result["audio_transfer"]["kind"] == "bytes"
    assert result["audio_transfer"]["data_base64"]


def test_synthesize_message_voice_returns_audio_when_db_ready_write_fails(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fail_db_write(*args, **kwargs):
        raise RuntimeError("database is locked")

    async def fake_synthesize_tts(**kwargs):
        return SimpleNamespace(job_id="job-ready", audio_bytes=b"mp3-ready", mime_type="audio/mpeg", variant="mobile")

    async def fake_load_character_voice_profile(db, profile_id):
        return None

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:princess_luna",
            "voice_profile_id": "",
            "instruct": "可爱温柔的女声",
        },
    )
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fail_db_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fail_db_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fail_db_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fake_synthesize_tts)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="princess_luna__u_1",
            conversation_id="conv_locked",
            message_id="msg_locked_ready",
            content="Good night.",
            voice_id="ponyvoice:princess_luna",
            instruct="可爱温柔的女声",
            push_update=False,
            persist=True,
        )
    )

    assert result["ok"] is True
    assert result["voice_state"]["voice_status"] == "ready"
    assert result["audio_transfer"]["kind"] == "bytes"


def test_synthesize_message_voice_uses_cached_cosyvoice_id_for_profile(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_TTS_PROVIDER", "cosyvoice")
    calls = {"cosy": None, "recipe": 0}

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fake_write(*args, **kwargs):
        return None

    async def fake_load_character_voice_profile(db, profile_id):
        return {
            "voice_profile_id": profile_id,
            "source_mode": "clone",
            "display_name": "紫悦",
            "description": "温柔自然",
            "extra_instruct": "",
            "transcript": "参考文本",
            "audio_data": b"reference-audio",
            "mime_type": "audio/mpeg",
            "recipe_hash": "recipe-1",
            "cosy_voice_id": "cosyvoice-v3-flash-pony-abc",
            "cosy_recipe_hash": "recipe-1",
        }

    async def fake_synthesize_cosyvoice(**kwargs):
        calls["cosy"] = kwargs
        return SimpleNamespace(job_id="cosy-job", audio_bytes=b"wav-ready", mime_type="audio/wav", variant="mobile")

    async def fail_recipe(*args, **kwargs):
        calls["recipe"] += 1
        raise AssertionError("qwen recipe path should not be used for cosyvoice provider")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:twilight_sparkle",
            "voice_profile_id": "ponyvoice:twilight_sparkle",
            "source_mode": "clone",
            "instruct": "轻柔",
        },
    )
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fake_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fake_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fake_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_cosyvoice", fake_synthesize_cosyvoice)
    monkeypatch.setattr(voice_messages, "synthesize_recipe_tts", fail_recipe)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="twilight_sparkle",
            conversation_id="conv_cosy",
            message_id="msg_cosy",
            content="今晚的月光很安静。",
            voice_id="ponyvoice:twilight_sparkle",
            instruct="轻柔",
            push_update=False,
            persist=True,
        )
    )

    assert result["ok"] is True
    assert calls["recipe"] == 0
    assert calls["cosy"]["voice_id"] == "cosyvoice-v3-flash-pony-abc"
    assert calls["cosy"]["text"] == "今晚的月光很安静。"


def test_synthesize_message_voice_uses_cached_qwen_design_voice(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    calls = {"tts": None, "recipe": 0}

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fake_write(*args, **kwargs):
        return None

    async def fake_load_character_voice_profile(db, profile_id):
        return {
            "voice_profile_id": profile_id,
            "source_mode": "instruct",
            "display_name": "露娜",
            "description": "冷静、庄重、夜色感",
            "extra_instruct": "",
            "transcript": "",
            "audio_data": None,
            "mime_type": "audio/wav",
            "recipe_hash": "recipe-design",
            "qwen_cached_voice_id": "PonyChat-System-Luna-design-abcd1234",
        }

    async def fake_synthesize_tts(**kwargs):
        calls["tts"] = kwargs
        return SimpleNamespace(job_id="qwen-direct", audio_bytes=b"mp3-ready", mime_type="audio/mpeg", variant="original")

    async def fail_recipe(*args, **kwargs):
        calls["recipe"] += 1
        raise AssertionError("cached qwen design voice should use direct tts")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:luna_design",
            "voice_profile_id": "ponyvoice:luna_design",
            "source_mode": "instruct",
            "instruct": "",
        },
    )
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fake_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fake_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fake_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fake_synthesize_tts)
    monkeypatch.setattr(voice_messages, "synthesize_recipe_tts", fail_recipe)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="luna",
            conversation_id="conv_qwen_design",
            message_id="msg_qwen_design",
            content="今晚的月光很安静。",
            voice_id="ponyvoice:luna_design",
            push_update=False,
            persist=True,
        )
    )

    assert result["ok"] is True
    assert calls["recipe"] == 0
    assert calls["tts"]["voice_id"] == "qwen3tts:PonyChat-System-Luna-design-abcd1234"
    assert calls["tts"]["text"] == "今晚的月光很安静。"
    assert result["voice_state"]["voice_id"] == "ponyvoice:luna_design"


def test_synthesize_message_voice_registers_uncached_qwen_design_voice(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    calls = {"register": None, "tts": None, "recipe": 0}

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fake_write(*args, **kwargs):
        return None

    async def fake_load_character_voice_profile(db, profile_id):
        return {
            "voice_profile_id": profile_id,
            "source_mode": "instruct",
            "display_name": "露娜",
            "description": "冷静、庄重、夜色感",
            "extra_instruct": "",
            "transcript": "",
            "audio_data": None,
            "mime_type": "audio/wav",
            "recipe_hash": "recipe-design",
            "qwen_cached_voice_id": "",
        }

    async def fake_upsert_character_design_voice_profile(db, **kwargs):
        calls["register"] = kwargs
        return {
            "voice_profile_id": kwargs["voice_profile_id"],
            "source_mode": "instruct",
            "display_name": kwargs["character_name"],
            "description": kwargs["instruct"],
            "extra_instruct": "",
            "transcript": "",
            "audio_data": None,
            "mime_type": "audio/wav",
            "recipe_hash": "recipe-design",
            "qwen_cached_voice_id": "PonyChat-System-Luna-design-newvoice",
        }

    async def fake_synthesize_tts(**kwargs):
        calls["tts"] = kwargs
        return SimpleNamespace(job_id="qwen-direct", audio_bytes=b"mp3-ready", mime_type="audio/mpeg", variant="original")

    async def fail_recipe(*args, **kwargs):
        calls["recipe"] += 1
        raise AssertionError("uncached qwen design voice should register then use direct tts")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:luna_design",
            "voice_profile_id": "ponyvoice:luna_design",
            "source_mode": "instruct",
            "instruct": "",
        },
    )
    monkeypatch.setattr(voice_messages, "get_database", lambda: object())
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fake_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fake_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fake_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "upsert_character_design_voice_profile", fake_upsert_character_design_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fake_synthesize_tts)
    monkeypatch.setattr(voice_messages, "synthesize_recipe_tts", fail_recipe)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="luna",
            conversation_id="conv_qwen_design_register",
            message_id="msg_qwen_design_register",
            content="稍等——我马上来。",
            voice_id="ponyvoice:luna_design",
            push_update=False,
            persist=True,
        )
    )

    assert result["ok"] is True
    assert calls["recipe"] == 0
    assert calls["register"]["instruct"] == "冷静、庄重、夜色感"
    assert calls["register"]["force_replace"] is False
    assert calls["tts"]["voice_id"] == "qwen3tts:PonyChat-System-Luna-design-newvoice"
    assert calls["tts"]["text"] == "稍等——我马上来。"


def test_cached_qwen_design_fallback_recipe_bypasses_current_circuit(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    calls = {"tts": 0, "recipe": None}

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fake_write(*args, **kwargs):
        return None

    async def fake_load_character_voice_profile(db, profile_id):
        return {
            "voice_profile_id": profile_id,
            "source_mode": "instruct",
            "display_name": "露娜",
            "description": "冷静、庄重、夜色感",
            "extra_instruct": "",
            "transcript": "",
            "audio_data": None,
            "mime_type": "audio/wav",
            "recipe_hash": "recipe-design",
            "qwen_cached_voice_id": "PonyChat-System-Luna-design-abcd1234",
        }

    async def fail_direct_tts(**kwargs):
        calls["tts"] += 1
        raise voice_lab_client.VoiceLabError("voice_service_unavailable", "Server disconnected")

    async def fake_recipe_tts(**kwargs):
        calls["recipe"] = kwargs
        return SimpleNamespace(job_id="recipe-ready", audio_bytes=b"mp3-ready", mime_type="audio/mpeg", variant="original")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:luna_design",
            "voice_profile_id": "ponyvoice:luna_design",
            "source_mode": "instruct",
            "instruct": "",
        },
    )
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fake_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fake_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fake_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fail_direct_tts)
    monkeypatch.setattr(voice_messages, "synthesize_recipe_tts", fake_recipe_tts)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="luna",
            conversation_id="conv_qwen_design_fallback",
            message_id="msg_qwen_design_fallback",
            content="今晚的月光很安静。",
            voice_id="ponyvoice:luna_design",
            push_update=False,
            persist=True,
        )
    )

    assert result["ok"] is True
    assert calls["tts"] == 1
    assert calls["recipe"]["ignore_circuit"] is True
    assert calls["recipe"]["voice_profile_id"] == "ponyvoice:luna_design"


def test_cosyvoice_direct_invalid_voice_id_falls_back_without_visible_error(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_TTS_PROVIDER", "cosyvoice")
    monkeypatch.setenv("COSYVOICE_DEFAULT_VOICE", "longanyang")
    calls = []

    async def fake_load_character_voice_profile(db, profile_id):
        return None

    async def fake_synthesize_cosyvoice(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(job_id="cosy-direct", audio_bytes=b"wav-ready", mime_type="audio/wav", variant="mobile")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "qwen3tts:紫悦",
            "voice_profile_id": "",
            "source_mode": "voice_id",
            "instruct": "温柔自然",
        },
    )
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_cosyvoice", fake_synthesize_cosyvoice)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="ziyun",
            conversation_id="conv_direct_fallback",
            message_id="msg_direct_fallback",
            content="旧 Voice ID 也应该能发出语音。",
            voice_id="qwen3tts:紫悦",
            instruct="温柔自然",
            push_update=False,
            persist=False,
        )
    )

    assert result["ok"] is True
    assert calls[0]["voice_id"] == "longanyang"
    assert result["voice_state"]["voice_status"] == "ready"
    assert result["voice_state"].get("voice_error") is None
    assert result["audio_transfer"]["kind"] == "bytes"


def test_cosyvoice_profile_registration_failure_falls_back_to_default_voice(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_TTS_PROVIDER", "cosyvoice")
    monkeypatch.setenv("COSYVOICE_DEFAULT_VOICE", "longanyang")
    calls = []

    async def fake_load_character_voice_profile(db, profile_id):
        return {
            "voice_profile_id": profile_id,
            "source_mode": "instruct",
            "display_name": "露娜",
            "description": "冷静、庄重、夜色感",
            "extra_instruct": "",
            "transcript": "",
            "audio_data": None,
            "mime_type": "audio/wav",
            "recipe_hash": "recipe-design",
            "cosy_voice_id": "",
            "cosy_recipe_hash": "",
        }

    async def fail_register(**kwargs):
        raise RuntimeError("register temporarily unavailable")

    async def fake_update_registration(*args, **kwargs):
        return None

    async def fake_synthesize_cosyvoice(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(job_id="cosy-fallback", audio_bytes=b"wav-ready", mime_type="audio/wav", variant="mobile")

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "ponyvoice:luna_design",
            "voice_profile_id": "ponyvoice:luna_design",
            "source_mode": "instruct",
            "instruct": "冷静、庄重、夜色感",
        },
    )
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "register_cosyvoice_design", fail_register)
    monkeypatch.setattr(voice_messages, "update_character_voice_cosy_registration", fake_update_registration)
    monkeypatch.setattr(voice_messages, "synthesize_cosyvoice", fake_synthesize_cosyvoice)

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="luna",
            conversation_id="conv_profile_fallback",
            message_id="msg_profile_fallback",
            content="指令音色注册临时失败也要能发语音。",
            push_update=False,
            persist=False,
        )
    )

    assert result["ok"] is True
    assert calls[0]["voice_id"] == "longanyang"
    assert "冷静、庄重、夜色感" in calls[0]["instruct"]
    assert result["voice_state"]["voice_status"] == "ready"
    assert result["voice_state"].get("voice_error") is None
    assert result["audio_transfer"]["kind"] == "bytes"


def test_voice_generation_charges_ten_credits_per_ready_message(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.delenv("PONYCHAT_TTS_PROVIDER", raising=False)
    monkeypatch.setenv("PONYCHAT_VOICE_MESSAGE_CREDIT_COST", "10")
    charges = []

    class FakeMembershipDao:
        async def increment_by(self, username, count):
            charges.append((username, count))
            return True

    async def fake_cached(**kwargs):
        return None

    async def fake_pending(**kwargs):
        return {"voice_status": "pending"}

    async def fake_write(*args, **kwargs):
        return None

    async def fake_load_character_voice_profile(db, profile_id):
        return None

    async def fake_synthesize_tts(**kwargs):
        return SimpleNamespace(
            job_id=f"job-{kwargs['text']}",
            audio_bytes=b"mp3-ready",
            mime_type="audio/mpeg",
            variant="mobile",
        )

    monkeypatch.setattr(
        voice_messages,
        "_character_voice_config",
        lambda username, character_id: {
            "enabled": True,
            "voice_id": "speaker:test",
            "voice_profile_id": "",
            "instruct": "自然",
        },
    )
    monkeypatch.setattr(voice_messages, "get_membership_dao", lambda: FakeMembershipDao())
    monkeypatch.setattr(voice_messages, "get_cached_message_voice_audio", fake_cached)
    monkeypatch.setattr(voice_messages, "save_pending_voice_state", fake_pending)
    monkeypatch.setattr(voice_messages, "upsert_voice_state", fake_write)
    monkeypatch.setattr(voice_messages, "store_voice_audio_cache", fake_write)
    monkeypatch.setattr(voice_messages, "_push_message_updated", fake_write)
    monkeypatch.setattr(voice_messages, "load_character_voice_profile", fake_load_character_voice_profile)
    monkeypatch.setattr(voice_messages, "synthesize_tts", fake_synthesize_tts)

    results = asyncio.run(
        voice_messages.prepare_voice_generation_for_messages(
            username="Jason",
            character_id="muffins",
            conversation_id="conv_voice_charge",
            assistant_meta=[{"message_id": "msg_voice_1"}, {"message_id": "msg_voice_2"}],
            assistant_units=[
                {"type": "text", "content": "第一条语音。"},
                {"type": "text", "content": "第二条语音。"},
            ],
            planner_result={"voice_reply": {"enabled": True}},
            timeout_seconds=1,
        )
    )

    assert set(results) == {"msg_voice_1", "msg_voice_2"}
    assert charges == [("Jason", 10), ("Jason", 10)]


def test_chat_voice_service_switch_forces_text_and_blocks_synthesis(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "0")

    planner_result = voice_messages.force_text_reply_when_chat_voice_disabled(
        {"voice_reply": {"enabled": True, "reason": "continue voice"}}
    )

    assert planner_result["voice_reply"]["enabled"] is False
    assert "直接返回文本回复" in planner_result["voice_reply"]["reason"]

    result = asyncio.run(
        voice_messages.synthesize_message_voice(
            username="Jason",
            character_id="princess_luna__u_1",
            conversation_id="conv_disabled",
            message_id="msg_disabled",
            content="Good night.",
            voice_id="ponyvoice:princess_luna",
            instruct="可爱温柔的女声",
            push_update=False,
            persist=False,
        )
    )

    assert result["ok"] is False
    assert result["error"] == "voice_paused"
    assert result["message"] == VOICE_DISABLED_MESSAGE


def test_global_voice_switch_disables_voice_lab(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "0")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_ENABLED", "1")

    assert is_voice_lab_enabled() is False


def test_voice_lab_circuit_opens_after_repeated_failures(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_CIRCUIT_OPEN_SECONDS", "30")
    monkeypatch.setattr(voice_lab_client, "_circuit_open_until", 0.0)
    monkeypatch.setattr(voice_lab_client, "_circuit_opened_at", 0.0)
    monkeypatch.setattr(voice_lab_client, "_failure_count", 0)
    monkeypatch.setattr(voice_lab_client, "_last_failure_at", 0.0)
    monkeypatch.setattr(voice_lab_client, "_last_error", "")

    voice_lab_client._open_circuit("voice_service_unavailable", "first disconnect")
    assert voice_lab_client.is_voice_lab_available() is True

    voice_lab_client._open_circuit("voice_service_unavailable", "second disconnect")
    assert voice_lab_client.is_voice_lab_available() is False
    assert "second disconnect" in voice_lab_client.voice_lab_last_error()


def test_voice_lab_circuit_health_probe_closes_early(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_ENABLED", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_CIRCUIT_MIN_OPEN_SECONDS", "0")
    monkeypatch.setenv("PONYCHAT_VOICE_LAB_CIRCUIT_PROBE_INTERVAL_SECONDS", "1")
    monkeypatch.setattr(voice_lab_client, "_circuit_open_until", 0.0)
    monkeypatch.setattr(voice_lab_client, "_circuit_opened_at", 0.0)
    monkeypatch.setattr(voice_lab_client, "_failure_count", 0)
    monkeypatch.setattr(voice_lab_client, "_last_failure_at", 0.0)
    monkeypatch.setattr(voice_lab_client, "_last_probe_at", 0.0)
    monkeypatch.setattr(voice_lab_client, "_last_error", "")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, **kwargs):
            assert method == "GET"
            return self.get(url)

        def get(self, url):
            return FakeResponse()

    voice_lab_client._open_circuit("voice_service_unavailable", "tunnel dropped")
    monkeypatch.setattr(voice_lab_client, "_circuit_opened_at", time.time() - 5.0)
    monkeypatch.setattr(voice_lab_client.httpx, "Client", FakeClient)

    assert voice_lab_client.is_voice_lab_available() is True
    assert voice_lab_client.voice_lab_last_error() == ""


def test_dashscope_qwen_tts_payload_uses_official_voice_and_instruct_model(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_QWEN_TTS_DEFAULT_VOICE", "Serena")

    payload = build_qwen_tts_online_payload(
        text="你好。",
        voice_id="qwen3tts:twilight_sparkle",
        language="English",
        instruct="温柔、清晰、语速稍慢",
    )

    assert payload["model"] == "qwen3-tts-instruct-flash"
    assert payload["input"] == {
        "text": "你好。",
        "voice": "Cherry",
        "language_type": "English",
    }
    assert payload["parameters"]["instructions"] == "温柔、清晰、语速稍慢"
    assert payload["parameters"]["optimize_instructions"] is True
    assert normalize_qwen_tts_online_voice("speaker:serena") == "Serena"
    assert normalize_qwen_tts_online_voice("unknown-local-voice") == "Serena"


def test_voice_result_display_delay_matches_client_voice_pacing():
    assert voice_messages.estimate_voice_duration_ms("") == 1200
    assert voice_messages.estimate_voice_duration_ms("abcd") == 1200
    assert voice_messages.estimate_voice_duration_ms("x" * 200) == 30000
    assert voice_messages.voice_result_display_delay_seconds(
        {"voice_state": {"voice_status": "ready", "duration_ms": 5000}},
        "fallback",
    ) == 6.0
    assert voice_messages.voice_result_display_delay_seconds(
        {"voice_state": {"voice_status": "ready", "tts_text": "abcd"}},
        "",
    ) == 1.44
    assert voice_messages.voice_result_display_delay_seconds({"voice_state": {"voice_status": "failed"}}, "") is None

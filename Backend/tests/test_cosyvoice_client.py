from __future__ import annotations

import asyncio
from typing import Any

from Backend import cosyvoice_client, voice_lab_client


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeCosyVoiceClient:
    def __init__(self, posts: list[dict[str, Any]], *, fail_first_instruction: bool = False) -> None:
        self._posts = posts
        self._fail_first_instruction = fail_first_instruction
        self._post_count = 0

    async def __aenter__(self) -> "_FakeCosyVoiceClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        if method.upper() == "POST":
            return await self.post(url, **kwargs)
        return await self.get(url, **kwargs)

    async def post(self, _url: str, *, json: dict[str, Any] | None = None, **_kwargs: Any) -> _FakeResponse:
        self._post_count += 1
        payload = dict(json or {})
        self._posts.append(payload)
        if self._fail_first_instruction and self._post_count == 1 and payload.get("instruct"):
            return _FakeResponse(status_code=400, text='{"message":"Instruction is invalid!"}')
        return _FakeResponse(payload={"job_id": "job-cosy"})

    async def get(self, url: str, **_kwargs: Any) -> _FakeResponse:
        if url.endswith("/jobs/job-cosy"):
            return _FakeResponse(payload={"status": "completed", "job_id": "job-cosy", "audio_url": "/audio/job-cosy.wav"})
        return _FakeResponse(content=b"wav-ready", headers={"content-type": "audio/wav"})


def test_cosyvoice_tts_instruct_is_empty_by_default(monkeypatch):
    monkeypatch.delenv("PONYCHAT_COSYVOICE_TTS_INSTRUCT_ENABLED", raising=False)
    monkeypatch.setattr(cosyvoice_client, "_poll_interval", lambda: 0.0)
    posts: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cosyvoice_client.httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeCosyVoiceClient(posts),
    )

    result = asyncio.run(
        cosyvoice_client.synthesize_cosyvoice(
            text="你好。",
            voice_id="longanyang",
            instruct="音色稳定规则：保持角色声纹。\n本句表演提示：热情一点。",
        )
    )

    assert result.job_id == "job-cosy"
    assert posts[0]["instruct"] == ""


def test_cosyvoice_tts_invalid_instruction_retries_without_instruct(monkeypatch):
    monkeypatch.setenv("PONYCHAT_COSYVOICE_TTS_INSTRUCT_ENABLED", "1")
    monkeypatch.setattr(cosyvoice_client, "_poll_interval", lambda: 0.0)
    posts: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cosyvoice_client.httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeCosyVoiceClient(posts, fail_first_instruction=True),
    )

    result = asyncio.run(
        cosyvoice_client.synthesize_cosyvoice(
            text="你好。",
            voice_id="longanyang",
            instruct="用轻快的语气说这句话。",
        )
    )

    assert result.job_id == "job-cosy"
    assert len(posts) == 2
    assert posts[0]["instruct"] == "用轻快的语气说这句话。"
    assert posts[1]["instruct"] == ""


def test_cosyvoice_instruction_trim_uses_document_character_units():
    trimmed = cosyvoice_client.trim_cosyvoice_tts_instruction(
        "温柔，语速偏慢，停顿稍长，语气亲近，尾音轻一点，带一点点害羞，但不要拖太久。"
    )

    units = sum(2 if "\u3400" <= ch <= "\u9fff" else 1 for ch in trimmed)
    assert units <= 100
    assert trimmed.endswith("。")


def test_voice_lab_health_uses_cosyvoice_base_url(monkeypatch):
    monkeypatch.setenv("PONYCHAT_TTS_PROVIDER", "cosyvoice")
    monkeypatch.setenv("PONYCHAT_COSYVOICE_BASE_URL", "https://voice.ponychat.org/cosyvoice/")

    assert voice_lab_client._voice_lab_health_url() == "https://voice.ponychat.org/cosyvoice/health"

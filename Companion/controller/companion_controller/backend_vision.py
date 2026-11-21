from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx


class BackendDeepSeekVisionVerifier:
    """Reuse PonyChat's provider stack; model keys never enter Mobile MCP."""

    def verify_website(self, screenshot_path: str, expected_host: str) -> bool:
        return asyncio.run(self._verify_website(screenshot_path, expected_host))

    async def _verify_website(self, screenshot_path: str, expected_host: str) -> bool:
        from Backend.companion_model_policy import get_companion_model_for
        from Backend.providers.llm_call import call_llm_payload

        encoded = base64.b64encode(Path(screenshot_path).read_bytes()).decode("ascii")
        model = get_companion_model_for(has_image=True)
        payload = {
            "model": model["model_name"],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是手机界面验收器。只输出 JSON："
                        '{"matched":true|false,"evidence":"不超过30字"}。'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                        {
                            "type": "text",
                            "text": f"判断截图是否显示 Chrome 已打开域名 {expected_host} 的官网页面。",
                        },
                    ],
                },
            ],
            "stream": False,
            "max_tokens": 120,
            "temperature": 0,
        }
        try:
            response = await call_llm_payload(
                payload,
                model,
                task="companion",
                timeout=120.0,
                record_usage="companion",
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else 0
            error_code = "unknown"
            if exc.response:
                try:
                    error_code = str(exc.response.json().get("error", {}).get("code") or error_code)
                except (ValueError, AttributeError):
                    pass
            raise RuntimeError(f"DeepSeek API HTTP {status} ({error_code})") from exc
        raw = (response.text or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return False
        try:
            result = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return False
        return result.get("matched") is True

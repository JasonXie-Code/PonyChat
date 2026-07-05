"""
对同目录 word-img-test 中每张图调用与线上一致的 run_normal_vision（force_web=False），
将 assistant 文本、NormalVisionContext（含 should_refuse）、完整 raw_response 写入
var/ChatMonitor/.chatlogs/2026-04-25/23（不写入 var/.chatlogs；运行中临时 no-op save_chat_debug_log）。

运行：在项目根目录
  $env:PYTHONPATH="P:\PonyChat"; $env:PYTHONIOENCODING="utf-8"; python misc/archive/vision-tests/dump_word_vision_historical_chatlog.py
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

_THIS = Path(__file__).resolve()
_ROOT_PATH = next((p for p in _THIS.parents if (p / "Backend").is_dir() and (p / "misc").is_dir()), None)
if _ROOT_PATH is None:
    raise RuntimeError(f"无法定位仓库根: {_THIS}")
ROOT = str(_ROOT_PATH)
SCRIPT_DIR = str(_THIS.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import Backend.chat_modules.normal_planner as _npl  # noqa: E402
from Backend.chat_modules.normal_planner import run_normal_vision  # noqa: E402
from Backend.chat_modules.request_context import normalize_image_url_for_model  # noqa: E402
from Backend.utils import _to_js_literal  # noqa: E402

LOG_DIR = os.path.join(ROOT, "var", "ChatMonitor", ".chatlogs", "2026-04-25", "23")
STAGE = "word_vision_run_normal"
CHAR_ID = "word_vision_historical_dump"
USER = "local_dump"
MODE = "normal"


def _file_to_data_url(path: str) -> Optional[str]:
    ext = os.path.splitext(path)[1].lower()
    mime = "image/jpeg"
    if ext == ".png":
        mime = "image/png"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext in (".jpg", ".jpeg", ""):
        mime = "image/jpeg"
    with open(path, "rb") as f:
        b = f.read()
    b64 = base64.b64encode(b).decode("ascii")
    return normalize_image_url_for_model(
        f"data:{mime};base64,{b64}", max_side=2560, jpeg_quality=75
    )


async def _one_image(
    data_url: Optional[str], index: int, stem: str, filename: str, run_stamp: str
) -> Dict[str, Any]:
    if not data_url:
        return {
            "ok": False,
            "error": "normalize_failed",
            "file_stem": stem,
            "filename": filename,
            "index": index,
            "simulation": "run_normal_vision",
            "run_stamp": run_stamp,
        }

    last: Dict[str, Any] = {"text": None, "raw": None}
    _real_llm = _npl.call_llm_payload
    _real_save = _npl.save_chat_debug_log

    async def _capture_llm(*a: Any, **kw: Any):
        r = await _real_llm(*a, **kw)
        last["text"] = getattr(r, "text", None)
        last["raw"] = getattr(r, "raw_response", None)
        return r

    async def _noop_save(*_a: Any, **_k: Any) -> None:
        return None

    _npl.call_llm_payload = _capture_llm  # type: ignore[assignment]
    _npl.save_chat_debug_log = _noop_save  # type: ignore[assignment]
    try:
        ctx = await run_normal_vision(
            [data_url],
            "",
            username=USER,
            character_id=CHAR_ID,
            force_web=False,
        )
    finally:
        _npl.call_llm_payload = _real_llm  # type: ignore[assignment]
        _npl.save_chat_debug_log = _real_save  # type: ignore[assignment]

    return {
        "ok": True,
        "file_stem": stem,
        "filename": filename,
        "index": index,
        "simulation": "run_normal_vision",
        "run_stamp": run_stamp,
        "vision_context": dataclasses.asdict(ctx),
        "assistant_text": (last.get("text") or "").strip() or None,
        "raw_response": last.get("raw"),
    }


def _write_js(run_stamp: str, seq: int, stem_safe: str, log_content: dict) -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    fn = f"{run_stamp}_{seq:03d}_{MODE}_{STAGE}_{stem_safe}_{CHAR_ID}.js"
    path = os.path.join(LOG_DIR, fn)
    body = f"const debug_log = {_to_js_literal(log_content, 0)};"
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


async def _main() -> None:
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    img_dir = os.path.join(SCRIPT_DIR, "word-img-test")
    if not os.path.isdir(img_dir):
        print("missing", img_dir)
        sys.exit(1)

    files = sorted(
        f
        for f in os.listdir(img_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )
    if not files:
        print("no images in", img_dir)
        sys.exit(1)

    all_rows: List[Dict[str, Any]] = []
    for i, name in enumerate(files, start=1):
        p = os.path.join(img_dir, name)
        stem, _ = os.path.splitext(name)
        durl = _file_to_data_url(p)
        row = await _one_image(durl, i, stem, name, run_stamp)
        all_rows.append(row)
        log_content = {
            "timestamp": datetime.now().isoformat(),
            "username": USER,
            "character_id": CHAR_ID,
            "mode": MODE,
            "model": "",
            "stage": f"{STAGE}_PER_IMAGE",
            "data": row,
        }
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)[:80]
        out_path = _write_js(run_stamp, i, safe, log_content)
        print(out_path)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "username": USER,
        "character_id": CHAR_ID,
        "mode": MODE,
        "model": "",
        "stage": f"{STAGE}_SUMMARY",
        "data": {
            "run_stamp": run_stamp,
            "source_dir": img_dir,
            "image_count": len(files),
            "images": all_rows,
        },
    }
    sp = _write_js(run_stamp, 999, "ALL_SUMMARY", summary)
    print("summary:", sp)


if __name__ == "__main__":
    asyncio.run(_main())

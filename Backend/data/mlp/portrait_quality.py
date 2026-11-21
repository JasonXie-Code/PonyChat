# -*- coding: utf-8 -*-
"""维基截图文件名 + 图像尺寸启发式：区分偏正式角色图与表情包/反应镜头。"""

from __future__ import annotations

import re
from pathlib import Path

# 文件名命中则强烈惩罚（多为反应镜头、梗图、夸张表情）
_MEME_SUBSTRINGS = (
    "sweat",
    "sweating",
    "panic",
    "mania",
    "rage",
    "goof",
    "literal video",
    "dramatic zoom",
    "zoom on",
    "face-hoof",
    "facehoof",
    "face-hoofs",
    "face palm",
    "facepalm",
    "derp",
    "twitch",
    "insane",
    "crazy eyes",
    "evil grin",
    "devilish",
    "crying",
    "sobbing",
    "sob ",
    "meme",
    "no silly",
    "troll",
    "rage quit",
    "screaming",
    "shocked",
    "shock ",
    "literal",
    "balloon face",
    "distorted",
    "chibi",
    "face down",
    "face cutout",
    "flies past",
)

# 偏「剧照截图」但常为全身/剧情帧，略加分或中性（勿重复同一语义，避免多次 +35）
_POSITIVE_SUBSTRINGS = (
    "promotional",
    "stock art",
    "hasbro",
    "merchandise",
    "character navbox",
)

# 过小的导航条图
_NEGATIVE_SUBSTRINGS = (
    "navbox",
    "comic micro",
)


def _norm(name: str) -> str:
    return name.replace("_", " ").lower()


def filename_portrait_score(stem: str) -> float:
    """
    返回越高越像「正常展示用头像素材」。
    stem: 不含 File: 与扩展名的文件名。
    """
    n = _norm(stem)
    s = 0.0
    for bad in _MEME_SUBSTRINGS:
        if bad in n:
            s -= 120.0
    for p in _POSITIVE_SUBSTRINGS:
        if p.replace("_", " ") in n or p in n:
            s += 35.0
    for neg in _NEGATIVE_SUBSTRINGS:
        if neg in n:
            s -= 60.0
    # 官方 ID：常为全身站姿，作头像需再裁切，加分低于宣传/定装图
    if re.search(r"\bid s\d+e\d+", n):
        s += 32.0
    if "closeup" in n or "close-up" in n:
        s -= 15.0  # 可能是怼脸梗图，交给黑名单；无黑名单时略罚
    if re.search(r"\bface\b", n):
        s += 10.0
    if "cropped" in n or " crop" in n:
        s += 15.0
    if "portrait" in n:
        s += 25.0
    return s


def probe_image_size(data: bytes) -> tuple[int, int] | None:
    """不依赖 Pillow，读取 PNG/JPEG 头得到宽高。"""
    if len(data) < 24:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        n = min(len(data), 512 * 1024)
        while i < n - 8:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h = int.from_bytes(data[i + 5 : i + 7], "big")
                w = int.from_bytes(data[i + 7 : i + 9], "big")
                return w, h
            i += 2 + seg_len
    return None


def geometry_portrait_score(w: int, h: int) -> float:
    """极端细长条多为横幅/分镜；过小为导航图标；竖长全身 ID 常见 h>>w。"""
    if w < 120 or h < 120:
        return -80.0
    s = 0.0
    if max(w, h) > 2000:
        s -= 18.0
    ar = w / max(h, 1)
    if ar > 2.2 or ar < 0.45:
        s -= 40.0
    if h > w * 1.45:
        s -= 55.0
    if 0.75 <= ar <= 1.35:
        s += 25.0
    return s


def total_score(filename_stem: str, width: int | None, height: int | None) -> float:
    s = filename_portrait_score(filename_stem)
    if width and height:
        s += geometry_portrait_score(width, height)
    return s


def score_downloaded_file(path: Path) -> tuple[float, tuple[int, int] | None]:
    data = path.read_bytes()[: min(512 * 1024, path.stat().st_size)]
    wh = probe_image_size(data)
    stem = path.stem
    if wh:
        return total_score(stem, wh[0], wh[1]), wh
    return total_score(stem, None, None), None

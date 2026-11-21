# -*- coding: utf-8 -*-
"""
官网首页展示图：从 Main/frontend/Photos 只读复制原图到 public/Photos，再对副本裁切。

重要约定
  - Photos/*.jpg（相对本 frontend 目录）为人工维护的「原图」，本脚本绝不原地写入。
  - 流程：先 shutil.copy2 到 public/Photos，再仅对 public 内文件做裁切。

裁切规则（与当前 887×1920 截图一致，可按需改阈值）
  - 顶：状态栏，约高度 4.2%。
  - 底：先裁「屏外暗边」（整行平均亮度低于阈值的连续行）；再裁 EXTRA_BOTTOM_GESTURE_PX，
    去掉仍留在画面内的系统白色手势条（仅数像素高，暗边检测无法覆盖）。

用法（在 PonyChat-Website/Main/frontend 下）：
  python scripts/build_showcase_photos.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

# 在「屏外暗边」之上再裁的像素数：去掉底部系统手势条（细白线），略大于白条本身以免露边。
# 若误切到应用内容，可改为 10～12；若白条仍可见，可改为 18～20。
EXTRA_BOTTOM_GESTURE_PX = 16


def _frontend_root() -> Path:
    """Main/frontend/（scripts 的上两级）。"""
    return Path(__file__).resolve().parent.parent


def count_bottom_letterbox_rows(
    gray: Image.Image,
    w: int,
    h: int,
    *,
    mean_threshold: float = 42.0,
    max_scan: int = 120,
) -> int:
    """自底向上，统计连续「整行偏暗」行数（屏外黑边 / 圆角外区域）。"""
    n = 0
    for dy in range(min(max_scan, h)):
        y = h - 1 - dy
        row_mean = sum(gray.getpixel((x, y)) for x in range(w)) / w
        if row_mean < mean_threshold:
            n += 1
        else:
            break
    return n


def crop_public_copy(
    dst: Path,
    *,
    top_ratio: float = 0.042,
    extra_bottom_gesture_px: int = EXTRA_BOTTOM_GESTURE_PX,
) -> tuple[int, int, int, int]:
    """
    对 public/Photos 内已有文件（已是原图副本）裁切并覆盖保存。
    返回 (原高度, 顶裁 px, 底裁 px, 其中底裁含：暗边行数 + 手势条附加像素)。
    """
    im = Image.open(dst)
    w, h = im.size
    gray = im.convert("L")

    top_px = max(1, int(round(h * top_ratio)))
    letterbox_rows = count_bottom_letterbox_rows(gray, w, h)
    extra = max(0, int(extra_bottom_gesture_px))
    # 底裁总量不超过约 6% 高度，避免误伤主界面
    max_bottom = min(int(round(h * 0.06)), h - top_px - 200)
    bottom_px = min(letterbox_rows + extra, max_bottom)

    new_h = h - top_px - bottom_px
    if new_h < 200:
        raise ValueError(f"裁切结果高度过小: {dst.name} h={h} top={top_px} bottom={bottom_px}")

    cropped = im.crop((0, top_px, w, h - bottom_px))
    cropped.save(dst, quality=93, optimize=True)
    return h, top_px, bottom_px, letterbox_rows


def main() -> int:
    root = _frontend_root()
    src_dir = root / "Photos"
    dst_dir = root / "public" / "Photos"
    if not src_dir.is_dir():
        print(f"缺少原图目录: {src_dir}", file=sys.stderr)
        return 1

    jpgs = sorted(src_dir.glob("*.jpg"))
    if not jpgs:
        print(f"未在 {src_dir} 找到 .jpg 原图", file=sys.stderr)
        return 1

    for src in jpgs:
        dst = dst_dir / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"复制原图: {src.name} -> {dst.relative_to(root)}")
        h0, top_px, bottom_px, letterbox_rows = crop_public_copy(dst)
        h1 = Image.open(dst).size[1]
        extra_used = bottom_px - letterbox_rows
        print(
            f"  裁切副本: 高度 {h0} -> {h1}  "
            f"(顶 {top_px}px, 底 {bottom_px}px = 暗边 {letterbox_rows}px + 手势条 {extra_used}px)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

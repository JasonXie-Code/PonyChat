# -*- coding: utf-8 -*-
"""任意图片字节 → JPEG（RGBA 等先铺白底），供头像下载与批处理统一格式。"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image


def bytes_to_jpg_bytes(
    data: bytes,
    quality: int = 92,
    *,
    passthrough_jpeg: bool = True,
) -> bytes:
    """
    解码常见格式（含 WebP/PNG/RGBA）后输出 JPEG 字节。
    若源已是 JPEG 且开启 passthrough，则**不重编码**，避免维基/CDN 小图再被压糊一层。
    """
    if passthrough_jpeg and len(data) >= 2 and data[:2] == b"\xff\xd8":
        return data
    im = Image.open(BytesIO(data))
    if im.mode == "P":
        im = im.convert("RGBA")
    if im.mode == "LA":
        im = im.convert("RGBA")
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    else:
        im = im.convert("RGB")
    buf = BytesIO()
    # 高 quality 时关闭色度抽样，减轻彩边与糊感
    sub = 0 if quality >= 90 else 2
    im.save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=True,
        subsampling=sub,
    )
    return buf.getvalue()


def file_to_jpg(src: Path, dst: Path | None = None, *, quality: int = 92) -> Path:
    """将文件转为同路径 .jpg（或指定 dst）。返回写入路径。"""
    data = src.read_bytes()
    jpg = bytes_to_jpg_bytes(data, quality=quality)
    out = dst if dst is not None else src.with_suffix(".jpg")
    out.write_bytes(jpg)
    return out


def batch_directory(
    root: Path,
    *,
    recursive: bool = False,
    quality: int = 92,
    delete_source: bool = False,
) -> int:
    """将目录下 .png/.webp/.gif 等转为 .jpg；已有 .jpg 跳过。返回转换数量。"""
    exts = {".png", ".webp", ".gif", ".jpeg", ".bmp", ".tif", ".tiff"}
    n = 0
    it = root.rglob("*") if recursive else root.iterdir()
    for p in it:
        if not p.is_file():
            continue
        if p.suffix.lower() == ".jpg":
            continue
        if p.suffix.lower() not in exts:
            continue
        try:
            file_to_jpg(p, p.with_suffix(".jpg"), quality=quality)
            n += 1
            if delete_source and p.with_suffix(".jpg") != p:
                p.unlink()
        except OSError:
            continue
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="将图片转为统一 JPEG")
    ap.add_argument("path", type=Path, help="文件或目录")
    ap.add_argument("-r", "--recursive", action="store_true", help="目录递归")
    ap.add_argument("-q", "--quality", type=int, default=92, help="JPEG 质量 1-95")
    ap.add_argument("--delete-source", action="store_true", help="成功后删除原文件")
    args = ap.parse_args()
    p = args.path
    if p.is_file():
        out = file_to_jpg(p, quality=args.quality)
        print(out)
    elif p.is_dir():
        n = batch_directory(p, recursive=args.recursive, quality=args.quality, delete_source=args.delete_source)
        print(f"converted: {n}")
    else:
        raise SystemExit(f"not found: {p}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# This module is bound to build_demo.py's active song context at runtime.
def stitch_score_pages() -> dict:
    from PIL import Image

    charts = sorted(SOURCE_CHARTS.glob(SOURCE_CHART_GLOB))
    if not charts:
        return {"available": False, "pages": []}

    images = [Image.open(p).convert("RGB") for p in charts]
    width = max(im.width for im in images)
    gap = 0
    height = sum(im.height for im in images) + gap * (len(images) - 1)
    stitched = Image.new("RGB", (width, height), "white")

    pages = []
    y = 0
    for idx, (path, im) in enumerate(zip(charts, images), start=1):
        x = (width - im.width) // 2
        stitched.paste(im, (x, y))
        pages.append(
            {
                "page": idx,
                "src": str(path.relative_to(ROOT)),
                "x": x,
                "y": y,
                "width": im.width,
                "height": im.height,
                "topRatio": y / height,
                "bottomRatio": (y + im.height) / height,
            }
        )
        y += im.height + gap

    out = GENERATED / "stitched-score.png"
    stitched.save(out, optimize=True)
    meta = {
        "available": True,
        "image": "generated/stitched-score.png",
        "width": width,
        "height": height,
        "pages": pages,
    }
    write_json(GENERATED / "score-image.json", meta)
    return meta


def detect_staff_rows(image_path: Path) -> dict:
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return {"image": image_path.name, "width": 2914, "height": 3771, "rows": []}

    im = Image.open(image_path).convert("L")
    arr = np.array(im)
    h, w = arr.shape
    x0, x1 = int(w * 0.12), int(w * 0.93)
    dark = arr[:, x0:x1] < 80
    density = dark.mean(axis=1)
    line_centers = []
    for y in range(int(h * 0.16), h - 2):
        if density[y] > 0.15 and density[y] >= density[y - 1] and density[y] >= density[y + 1]:
            if not line_centers or y - line_centers[-1][0] > 6:
                line_centers.append((y, float(density[y])))
            elif density[y] > line_centers[-1][1]:
                line_centers[-1] = (y, float(density[y]))
    line_centers = [float(y) for y, value in line_centers if value > 0.5]

    staves = []
    i = 0
    while i <= len(line_centers) - 5:
        group = line_centers[i : i + 5]
        gaps = [group[j + 1] - group[j] for j in range(4)]
        avg_gap = sum(gaps) / len(gaps)
        if max(gaps) - min(gaps) <= 4 and 15 <= avg_gap <= 25:
            staves.append(group)
            i += 5
        else:
            i += 1

    rows = []
    for idx, staff in enumerate(staves):
        top_line = staff[0]
        bottom_line = staff[-1]
        staff_height = max(1, bottom_line - top_line)
        # 向上扩展以覆盖和弦符号（约五线谱上方 1.5 倍谱表高度）
        # 向下扩展以覆盖一行歌词（约下方 1.5 倍谱表高度）。
        top = max(0, top_line - int(staff_height * 1.5))
        bottom = min(h, bottom_line + int(staff_height * 1.8))
        band = arr[int(top) : int(bottom), :]
        cols = np.where((band < 120).mean(axis=0) > 0.01)[0]
        if len(cols):
            left = max(0, int(cols[0]) - 16)
            right = min(w, int(cols[-1]) + 16)
        else:
            left, right = int(w * 0.12), int(w * 0.93)
        if right - left < w * 0.45:
            left, right = int(w * 0.12), int(w * 0.93)
        rows.append(
            {
                "index": idx,
                "x": round(left / w, 5),
                "y": round(top / h, 5),
                "width": round((right - left) / w, 5),
                "height": round((bottom - top) / h, 5),
                "staffTop": round(top_line / h, 5),
                "staffBottom": round(bottom_line / h, 5),
            }
        )
    return {"image": image_path.name, "width": w, "height": h, "rows": rows}


def generate_chart_images_from_pdf() -> list:
    """Render every page of SOURCE_PDF to a PNG in SOURCE_CHARTS.

    Uses PyMuPDF (fitz) when available for high-quality rendering at 150 DPI.
    Falls back to a no-op if the library is missing (charts must then be
    supplied manually).  Generated files are named <SONG_ID>_00.png, _01.png …
    to match the default chartGlob pattern.

    Returns the list of generated/existing chart paths that match SOURCE_CHART_GLOB.
    """
    existing = sorted(SOURCE_CHARTS.glob(SOURCE_CHART_GLOB))
    if existing:
        return existing  # already present, nothing to do

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"{SONG_ID}: pymupdf not available – skipping chart image generation")
        return []

    SOURCE_CHARTS.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(SOURCE_PDF))
    generated = []
    for page_idx in range(len(doc)):
        out_path = SOURCE_CHARTS / f"{SONG_ID}_{page_idx:02d}.png"
        if out_path.exists():
            generated.append(out_path)
            continue
        page = doc[page_idx]
        mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
        pix.save(str(out_path))
        generated.append(out_path)
        print(f"{SONG_ID}: generated chart page {page_idx + 1}/{len(doc)} → {out_path.name}")
    doc.close()
    return generated


def build_visual_layout() -> dict:
    generate_chart_images_from_pdf()
    pages = []
    for i, chart in enumerate(sorted(SOURCE_CHARTS.glob(SOURCE_CHART_GLOB)), start=1):
        page = detect_staff_rows(chart)
        page["page"] = i
        pages.append(page)
    layout = {"pages": pages}
    return enrich_layout_with_omr_systems(layout)


def enrich_layout_with_omr_systems(layout: dict) -> dict:
    omr_path = find_omr_file()
    if not omr_path:
        return layout
    page_by_num = {int(p["page"]): p for p in layout.get("pages", [])}
    try:
        with zipfile.ZipFile(omr_path) as z:
            all_sheets = sorted(
                [n for n in z.namelist() if n.endswith(".xml") and "/sheet#" in n and _omr_sheet_num(n) is not None],
                key=lambda n: _omr_sheet_num(n),
            )
            for name in all_sheets:
                page_num = _omr_sheet_num(name)
                if page_num not in page_by_num:
                    continue
                root = ET.fromstring(z.read(name))
                picture = root.find("picture")
                width = int(picture.attrib.get("width", 2550)) if picture is not None else 2550
                height = int(picture.attrib.get("height", 3299)) if picture is not None else 3299
                systems = []
                for sys_el in root.findall(".//system"):
                    staves = []
                    for staff in sys_el.findall("part/staff"):
                        line_ys = []
                        lefts = []
                        rights = []
                        for line in staff.findall("lines/line"):
                            pts = line.findall("point")
                            if not pts:
                                continue
                            ys = [float(p.attrib.get("y", 0)) for p in pts]
                            xs = [float(p.attrib.get("x", 0)) for p in pts]
                            line_ys.append(sum(ys) / len(ys))
                            lefts.append(min(xs))
                            rights.append(max(xs))
                        if len(line_ys) >= 5:
                            top_line = min(line_ys)
                            bottom_line = max(line_ys)
                            staves.append(
                                {
                                    "staff": staff.attrib.get("id"),
                                    "left": min(lefts) if lefts else float(staff.attrib.get("left", 0)),
                                    "right": max(rights) if rights else float(staff.attrib.get("right", width)),
                                    "topLine": top_line,
                                    "bottomLine": bottom_line,
                                }
                            )
                    if not staves:
                        continue
                    left = min(s["left"] for s in staves)
                    right = max(s["right"] for s in staves)
                    top_line = min(s["topLine"] for s in staves)
                    bottom_line = max(s["bottomLine"] for s in staves)
                    # 计算边距时用单个谱表高度，而非整个
                    # 多谱表系统跨度。单谱表系统两者相同；
                    # 多谱表（PB + H1 等）可避免边距
                    # 膨胀到覆盖相邻系统。
                    single_staff_h = max(1, sum(
                        s["bottomLine"] - s["topLine"] for s in staves
                    ) / len(staves))
                    top = max(0, top_line - int(single_staff_h * 1.5))
                    bottom = min(height, bottom_line + int(single_staff_h * 1.8))
                    systems.append(
                        {
                            "system": sys_el.attrib.get("id"),
                            "staffCount": len(staves),
                            "x": round(left / width, 5),
                            "y": round(top / height, 5),
                            "width": round((right - left) / width, 5),
                            "height": round((bottom - top) / height, 5),
                            "staffTop": round(top_line / height, 5),
                            "staffBottom": round(bottom_line / height, 5),
                            "source": "audiveris-system-staves",
                        }
                    )
                page_by_num[page_num]["systemRows"] = systems
    except Exception as exc:
        layout["systemError"] = f"{type(exc).__name__}: {exc}"
    return layout


def _autodetect_page2_first_measure() -> None:
    """Auto-detect per-page measure boundaries from the OMR.

    Scans every sheet in the OMR, finds the max local measure ID with content,
    and builds the global MEASURE_PAGE_STARTS table so that page_for_measure()
    works correctly for songs with any number of pages.
    """
    global PAGE2_FIRST_MEASURE, MEASURE_PAGE_STARTS
    omr_path = find_omr_file()
    if not omr_path:
        return
    try:
        with zipfile.ZipFile(omr_path) as z:
            all_sheets = sorted(
                [n for n in z.namelist() if n.endswith(".xml") and "/sheet#" in n and _omr_sheet_num(n) is not None],
                key=lambda n: _omr_sheet_num(n),
            )
            if not all_sheets:
                return
            starts: list[tuple[int, int]] = [(1, 1)]  # page 1 always starts at measure 1
            cumulative_offset = 0
            for name in all_sheets:
                page_num = _omr_sheet_num(name)
                pg_root = ET.fromstring(z.read(name))
                max_id = 0
                for meas in pg_root.iter("measure"):
                    mid = _omr_measure_id(meas)
                    heads = meas.find("head-chords")
                    rests = meas.find("rest-chords")
                    has_content = (
                        (heads is not None and (heads.text or "").strip()) or
                        (rests is not None and (rests.text or "").strip())
                    )
                    if has_content and mid > max_id:
                        max_id = mid
                if page_num < len(all_sheets) and max_id > 0:
                    next_first = cumulative_offset + max_id + 1
                    starts.append((next_first, page_num + 1))
                cumulative_offset += max_id if max_id > 0 else 0

            pdf_starts = _pdf_measure_page_starts()
            if pdf_starts:
                starts = pdf_starts

            MEASURE_PAGE_STARTS = sorted(starts)
            # 保持 PAGE2_FIRST_MEASURE 与向后兼容代码路径同步
            if len(MEASURE_PAGE_STARTS) >= 2:
                new_p2 = MEASURE_PAGE_STARTS[1][0]
                if new_p2 != PAGE2_FIRST_MEASURE:
                    print(f"{SONG_ID}: auto-detected page2FirstMeasure={new_p2} (configured={PAGE2_FIRST_MEASURE})")
                    PAGE2_FIRST_MEASURE = new_p2
            if len(MEASURE_PAGE_STARTS) > 2:
                print(f"{SONG_ID}: multi-page score, {len(MEASURE_PAGE_STARTS)} pages, boundaries: {MEASURE_PAGE_STARTS}")
    except Exception:
        pass  # non-fatal: fall back to the configured value


def _pdf_measure_page_starts() -> list[tuple[int, int]]:
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(SOURCE_PDF))
    except Exception:
        return []

    starts: list[tuple[int, int]] = [(1, 1)]
    last_measure = 1
    for page_index, page in enumerate(doc, start=1):
        if page_index == 1:
            continue
        width = max(1.0, float(page.rect.width))
        candidates = []
        for raw in page.get_text("words"):
            try:
                x0, _y0, x1, _y1, text = raw[:5]
            except Exception:
                continue
            text = str(text).strip()
            if not re.fullmatch(r"\d{1,3}", text):
                continue
            try:
                value = int(text)
            except ValueError:
                continue
            x_mid = (float(x0) + float(x1)) / 2.0 / width
            # 印刷小节号位于谱表系统左侧。此处
            # 刻意排除标题附近的速度标记如 "134"。
            if x_mid <= 0.18 and value >= 8 and value > last_measure:
                candidates.append(value)
        if not candidates:
            continue
        first_measure = min(candidates)
        if first_measure <= last_measure:
            continue
        starts.append((first_measure, page_index))
        last_measure = first_measure
    return starts if len(starts) >= 2 else []


def extract_omr_noteheads() -> dict:
    omr_path = find_omr_file()
    pages = []
    if not omr_path:
        return {"pages": pages}
    try:
        with zipfile.ZipFile(omr_path) as z:
            # PAGE2_FIRST_MEASURE 已由
            # _autodetect_page2_first_measure() 在本调用前自动检测。
            all_sheets = sorted(
                [n for n in z.namelist() if n.endswith(".xml") and "/sheet#" in n and _omr_sheet_num(n) is not None],
                key=lambda n: _omr_sheet_num(n),
            )
            # 构建每页小节偏移表。优先使用由 PDF 印刷小节号
            # 推导的全局页起始；OMR 局部小节
            # ID 可能低估拥挤页面，使后续系统前移。
            if MEASURE_PAGE_STARTS:
                page_offsets: dict[int, int] = {int(pg): int(first_m) - 1 for first_m, pg in MEASURE_PAGE_STARTS}
            else:
                page_offsets = {1: 0, 2: PAGE2_FIRST_MEASURE - 1}
                for pn in range(3, len(all_sheets) + 1):
                    prev_name = f"sheet#{pn - 1}/sheet#{pn - 1}.xml"
                    if prev_name not in z.namelist():
                        page_offsets[pn] = page_offsets.get(pn - 1, 0)
                        continue
                    prev_root = ET.fromstring(z.read(prev_name))
                    max_id = 0
                    for meas in prev_root.iter("measure"):
                        mid = _omr_measure_id(meas)
                        heads = meas.find("head-chords")
                        rests = meas.find("rest-chords")
                        has_content = (
                            (heads is not None and (heads.text or "").strip()) or
                            (rests is not None and (rests.text or "").strip())
                        )
                        if has_content and mid > max_id:
                            max_id = mid
                    prev_offset = page_offsets.get(pn - 1, 0)
                    page_offsets[pn] = prev_offset + max_id

            for name in all_sheets:
                page_num = _omr_sheet_num(name)
                measure_offset = page_offsets.get(page_num, 0)
                root = ET.fromstring(z.read(name))
                picture = root.find("picture")
                width = int(picture.attrib.get("width", 2550)) if picture is not None else 2550
                height = int(picture.attrib.get("height", 3299)) if picture is not None else 3299
                bounds_by_id = {}
                rest_bounds_by_id = {}
                for hc in root.iter("head-chord"):
                    hid = hc.attrib.get("id")
                    b = hc.find("bounds")
                    if not hid or b is None:
                        continue
                    bounds_by_id[hid] = {
                        "x": int(b.attrib.get("x", 0)),
                        "y": int(b.attrib.get("y", 0)),
                        "w": int(b.attrib.get("w", 0)),
                        "h": int(b.attrib.get("h", 0)),
                    }
                for rc in root.iter("rest-chord"):
                    rid = rc.attrib.get("id")
                    b = rc.find("bounds")
                    if not rid or b is None:
                        continue
                    rest_bounds_by_id[rid] = {
                        "x": int(b.attrib.get("x", 0)),
                        "y": int(b.attrib.get("y", 0)),
                        "w": int(b.attrib.get("w", 0)),
                        "h": int(b.attrib.get("h", 0)),
                    }
                ordered = []
                rest_ordered = []
                seen = set()
                for measure in root.iter("measure"):
                    measure_no = _omr_measure_id(measure) + measure_offset
                    heads = measure.find("head-chords")
                    if heads is not None and heads.text:
                        for hid in heads.text.split():
                            if hid in seen or hid not in bounds_by_id:
                                continue
                            seen.add(hid)
                            b = bounds_by_id[hid]
                            ordered.append(
                                {
                                    "id": hid,
                                    "measureNo": measure_no,
                                    "x": (b["x"] + b["w"] / 2) / width,
                                    "y": (b["y"] + b["h"] / 2) / height,
                                    "bounds": {
                                        "x": b["x"] / width,
                                        "y": b["y"] / height,
                                        "width": b["w"] / width,
                                        "height": b["h"] / height,
                                    },
                                }
                            )
                    rests = measure.find("rest-chords")
                    if rests is not None and rests.text:
                        for rid in rests.text.split():
                            if rid not in rest_bounds_by_id:
                                continue
                            b = rest_bounds_by_id[rid]
                            rest_ordered.append(
                                {
                                    "id": rid,
                                    "measureNo": measure_no,
                                    "x": (b["x"] + b["w"] / 2) / width,
                                    "y": (b["y"] + b["h"] / 2) / height,
                                    "bounds": {
                                        "x": b["x"] / width,
                                        "y": b["y"] / height,
                                        "width": b["w"] / width,
                                        "height": b["h"] / height,
                                    },
                                }
                            )
                pages.append({"page": page_num, "width": width, "height": height, "noteheads": ordered, "rests": rest_ordered})
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "pages": pages}
    return {"pages": pages}


def attach_visual_positions(sync: dict, layout: dict) -> dict:
    events = sync.get("events") or []
    if not events:
        return sync
    page_map = {int(p["page"]): p for p in layout.get("pages", [])}
    for ev in events:
        page_num = int(ev.get("page") or 1)
        page = page_map.get(page_num)
        if not page:
            continue
        rows = page.get("rows") or []
        if not rows:
            continue
        page_events = [x for x in events if int(x.get("page") or 1) == page_num]
        page_events.sort(key=lambda x: float(x.get("linearTime", x.get("time", 0))))
        try:
            idx = page_events.index(ev)
        except ValueError:
            idx = 0
        progress = idx / max(1, len(page_events) - 1)
        row_index = min(len(rows) - 1, int(progress * len(rows)))
        row = rows[row_index]
        row_start = row_index / len(rows)
        row_end = (row_index + 1) / len(rows)
        local = 0 if row_end <= row_start else (progress - row_start) / (row_end - row_start)
        x = row["x"] + row["width"] * (0.08 + 0.86 * max(0, min(1, local)))
        ev["visual"] = {
            "page": page_num,
            "x": round(x, 5),
            "y": row["y"],
            "width": round(min(0.16, row["width"] * 0.14), 5),
            "height": row["height"],
            "row": row_index,
            "source": "image-staff-detection",
        }
    return sync


def attach_omr_notehead_positions(sync: dict, layout: dict, noteheads: dict) -> dict:
    events = sync.get("events") or []
    if not events:
        return sync
    page_map = {int(p["page"]): p for p in layout.get("pages", [])}
    head_map = {int(p["page"]): p.get("noteheads", []) for p in noteheads.get("pages", [])}
    rest_map = {int(p["page"]): p.get("rests", []) for p in noteheads.get("pages", [])}
    for page_num, heads in head_map.items():
        rests = rest_map.get(page_num, [])
        if not heads and not rests:
            continue
        rows = (page_map.get(page_num) or {}).get("rows") or []
        systems = (page_map.get(page_num) or {}).get("systemRows") or []
        page_events = [x for x in events if int(x.get("page") or 1) == page_num]
        # 按谱面物理位置排序：小节 → 拍 → 休止前音符 → 声部（上到下）。
        # 与 Audiveris 分配符头 ID 的从左到右、从上到下顺序一致，
        # 多声部交错时与 linearTime 顺序不同。
        page_events.sort(key=lambda x: (
            int(x.get("measureNo") or 0),
            round(float(x.get("beatInMeasure") or 0), 3),
            1 if x.get("isRest") else 0,
            int(x.get("partIndex") or 0),
        ))
        note_i = 0
        rest_i = 0
        rest_used_by_measure: dict[int, int] = {}
        for idx, ev in enumerate(page_events):
            used_rest_glyph = False
            if ev.get("isRest"):
                source_items = rests if rests else heads
                used_rest_glyph = bool(rests)
                try:
                    measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
                except Exception:
                    measure_no = 0
                measure_items = [x for x in source_items if int(x.get("measureNo") or 0) == measure_no]
                if measure_items:
                    used = rest_used_by_measure.get(measure_no, 0)
                    item = measure_items[min(used, len(measure_items) - 1)]
                    rest_used_by_measure[measure_no] = used + 1
                else:
                    item = source_items[min(rest_i, len(source_items) - 1)]
                rest_i += 1
            else:
                source_items = heads
                if not source_items:
                    continue
                try:
                    measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
                except Exception:
                    measure_no = 0
                measure_items = [x for x in source_items if int(x.get("measureNo") or 0) == measure_no]
                if measure_items:
                    used_in_measure = sum(1 for prior in page_events[:idx] if not prior.get("isRest") and int(prior.get("measureNo") or prior.get("measure") or 0) == measure_no)
                    item = measure_items[min(used_in_measure, len(measure_items) - 1)]
                    note_i += 1
                    source_items = None
                else:
                    source_items = heads
                    item = source_items[min(note_i, len(source_items) - 1)]
                    note_i += 1
            row = None
            if systems:
                row = min(systems, key=lambda r: abs(((r["staffTop"] + r["staffBottom"]) / 2) - item["y"]))
            elif rows:
                row = min(rows, key=lambda r: abs(((r["staffTop"] + r["staffBottom"]) / 2) - item["y"]))
            if row:
                y = row["y"]
                height = row["height"]
            else:
                y = max(0, item["bounds"]["y"] - 0.025)
                height = max(0.05, item["bounds"]["height"] + 0.055)
            ev["visual"] = {
                "page": page_num,
                "x": round(max(0, item["x"] - 0.022), 5),
                "y": round(y, 5),
                "width": 0.048,
                "height": round(height, 5),
                "noteheadId": None if ev.get("isRest") else item["id"],
                "restId": item["id"] if ev.get("isRest") else None,
                "source": "audiveris-omr-rest" if ev.get("isRest") and used_rest_glyph else "audiveris-omr-notehead",
            }
        visual_notes = [ev for ev in page_events if not ev.get("isRest") and ev.get("visual")]
        for ev in page_events:
            if not ev.get("isRest") or not ev.get("visual") or not visual_notes:
                continue
            if ev["visual"].get("source") == "audiveris-omr-rest":
                continue
            try:
                measure = float(ev.get("measureNo", ev.get("measure")))
            except Exception:
                measure = None
            same_measure = []
            if measure is not None:
                for note in visual_notes:
                    try:
                        if float(note.get("measureNo", note.get("measure"))) == measure:
                            same_measure.append(note)
                    except Exception:
                        pass
            candidates = same_measure or visual_notes
            anchor = min(candidates, key=lambda note: abs(float(note.get("linearTime", note.get("time", 0))) - float(ev.get("linearTime", ev.get("time", 0)))))
            ev["visual"]["y"] = anchor["visual"]["y"]
            ev["visual"]["height"] = anchor["visual"]["height"]
    return sync


def _row_for_pdf_measure_number(layout: dict, page_num: int, y_mid: float) -> dict | None:
    rows = []
    for page in layout.get("pages") or []:
        try:
            if int(page.get("page") or 0) == int(page_num):
                rows = list(page.get("systemRows") or page.get("rows") or [])
                break
        except Exception:
            continue
    if not rows:
        return None

    def row_score(row: dict) -> float:
        try:
            top = float(row.get("y") or 0.0)
            height = float(row.get("height") or 0.0)
            staff_top = float(row.get("staffTop") or (top + height * 0.35))
        except Exception:
            return 1e9
        # 印刷小节号靠近系统左上角。在此使用
        # 歌词/谱表带行匹配器对双谱表系统不安全，
        # 因下一个小节号可能落在上一系统
        # 下方谱表矩形内。
        target = top + min(max(0.018, height * 0.18), max(0.018, staff_top - top + 0.006))
        distance = abs(y_mid - target)
        if top - 0.035 <= y_mid <= staff_top + 0.035:
            return distance
        if top - 0.02 <= y_mid <= top + height + 0.02:
            return distance + 0.06
        return distance + 0.18

    return min(rows, key=row_score)


def _pdf_measure_row_anchors(layout: dict) -> list[dict]:
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(SOURCE_PDF))
    except Exception:
        return []

    anchors: dict[int, dict] = {}
    for page_index, page in enumerate(doc, start=1):
        width = max(1.0, float(page.rect.width))
        height = max(1.0, float(page.rect.height))
        for raw in page.get_text("words"):
            try:
                x0, y0, x1, y1, text = raw[:5]
            except Exception:
                continue
            text = str(text).strip()
            if not re.fullmatch(r"\d{1,3}", text):
                continue
            try:
                measure = int(text)
            except ValueError:
                continue
            x_mid = (float(x0) + float(x1)) / 2.0 / width
            if measure < 8 or x_mid > 0.18:
                continue
            y_mid = (float(y0) + float(y1)) / 2.0 / height
            row = _row_for_pdf_measure_number(layout, page_index, y_mid)
            if not row:
                continue
            anchors.setdefault(
                measure,
                {
                    "measure": measure,
                    "page": page_index,
                    "xText": round(x_mid, 5),
                    "yText": round(y_mid, 5),
                    "row": row,
                },
            )
    return [anchors[k] for k in sorted(anchors)]


def apply_pdf_measure_row_positions(sync: dict, layout: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    anchors = _pdf_measure_row_anchors(layout)
    if len(events) < 4 or len(anchors) < 2:
        return sync

    adjusted = 0
    for ev in events:
        try:
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            beat = float(ev.get("beatInMeasure") or 0.0)
        except Exception:
            continue
        if measure <= 0:
            continue

        anchor_idx = None
        for idx, anchor in enumerate(anchors):
            if int(anchor["measure"]) <= measure:
                anchor_idx = idx
            else:
                break
        if anchor_idx is None:
            continue
        anchor = anchors[anchor_idx]
        next_anchor = anchors[anchor_idx + 1] if anchor_idx + 1 < len(anchors) else None
        if next_anchor and measure >= int(next_anchor["measure"]):
            continue

        first_measure = int(anchor["measure"])
        next_measure = int(next_anchor["measure"]) if next_anchor else first_measure + 4
        span_measures = max(1, next_measure - first_measure)
        row = anchor["row"]
        try:
            row_x = float(row.get("x") or 0.0)
            row_y = float(row.get("y") or 0.0)
            row_w = float(row.get("width") or 0.84)
            row_h = float(row.get("height") or 0.08)
        except Exception:
            continue
        local = ((measure - first_measure) + max(0.0, min(4.0, beat)) / 4.0) / span_measures
        local = max(0.0, min(0.98, local))
        visual = dict(ev.get("visual") or {})
        old_page = int(visual.get("page") or ev.get("page") or 1)
        old_y = float(visual.get("y") or -1.0)
        needs_row_fix = old_page != int(anchor["page"]) or abs(old_y - row_y) > 0.026
        if not needs_row_fix:
            continue

        ev["page"] = int(anchor["page"])
        visual.update(
            {
                "page": int(anchor["page"]),
                "x": round(row_x + row_w * (0.07 + 0.86 * local), 5),
                "y": round(row_y, 5),
                "width": visual.get("width") or 0.048,
                "height": round(row_h, 5),
                "source": str(visual.get("source") or "") + "+pdf-measure-row",
            }
        )
        ev["visual"] = visual
        ev["pdfMeasureRowAdjusted"] = True
        adjusted += 1

    if not adjusted:
        return sync
    out = dict(sync)
    out["events"] = events
    out["pdfMeasureRows"] = {"method": "printed-measure-number-row-map", "adjustedEvents": adjusted}
    return out


def enforce_visual_monotone(sync: dict) -> dict:
    events = sync.get("events") or []
    for page_num in sorted({int(e.get("page") or 1) for e in events}):
        page_events = [e for e in events if int(e.get("page") or 1) == page_num and e.get("visual")]
        page_events.sort(key=_score_sort_key)
        row_max: dict[int, float] = {}
        for ev in page_events:
            visual = ev.get("visual") or {}
            row_key = round(float(visual.get("y") or 0), 3)
            x = float(visual.get("x") or 0)
            if ev.get("pdfLyricCue") or ev.get("pdfLyricVisualAdjusted"):
                row_max[row_key] = max(row_max.get(row_key, 0.0), x)
                continue
            max_x = row_max.get(row_key)
            if max_x is not None and x < max_x - 0.006:
                x = min(0.94, max_x + 0.008)
                visual["x"] = round(x, 5)
                visual["source"] = str(visual.get("source") or "") + "+visual-monotone"
            row_max[row_key] = max(row_max.get(row_key, 0.0), x)
    return sync


def clamp_visual_positions_to_layout(sync: dict, layout: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if not events:
        return sync
    page_rows: dict[int, list[dict]] = {}
    for page in layout.get("pages") or []:
        try:
            page_num = int(page.get("page") or 0)
        except Exception:
            continue
        rows = list(page.get("systemRows") or page.get("rows") or [])
        if rows:
            page_rows[page_num] = rows

    adjusted = 0
    for ev in events:
        visual = dict(ev.get("visual") or {})
        if not visual:
            continue
        try:
            page_num = int(visual.get("page") or ev.get("page") or 1)
            x = float(visual.get("x") or 0.0)
            y = float(visual.get("y") or 0.0)
            width = float(visual.get("width") or 0.048)
        except Exception:
            continue
        rows = page_rows.get(page_num) or []
        if not rows:
            continue
        row = min(rows, key=lambda r: abs(float(r.get("y") or 0.0) - y))
        try:
            row_x = float(row.get("x") or 0.0)
            row_y = float(row.get("y") or 0.0)
            row_w = float(row.get("width") or 1.0)
            row_h = float(row.get("height") or visual.get("height") or 0.08)
        except Exception:
            continue
        max_x = max(row_x, row_x + row_w - width - 0.006)
        new_x = max(row_x, min(max_x, x))
        new_y = y
        new_h = float(visual.get("height") or row_h)
        # 若先前启发式将指示器放在系统之间，将其
        # 吸附回最近的已检测系统矩形。
        if y < row_y - 0.035 or y > row_y + row_h + 0.035:
            new_y = row_y
            new_h = row_h
        if abs(new_x - x) > 0.0005 or abs(new_y - y) > 0.0005:
            visual["x"] = round(new_x, 5)
            visual["y"] = round(new_y, 5)
            visual["height"] = round(new_h, 5)
            visual["source"] = str(visual.get("source") or "") + "+layout-clamp"
            ev["visual"] = visual
            ev["page"] = page_num
            ev["visualClamped"] = True
            adjusted += 1
    if not adjusted:
        return sync
    out = dict(sync)
    out["events"] = events
    out["visualClamp"] = {"method": "limit-indicator-to-detected-system-row", "adjustedEvents": adjusted}
    return out


def mark_off_row_shadow_notes(sync: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if not events:
        return sync

    lyric_rows_by_measure: dict[int, set[tuple[int, int]]] = {}
    pdf_cue_row_ranges: dict[tuple[int, int], list[float]] = {}
    for ev in events:
        if ev.get("pdfLyricCue"):
            visual = ev.get("visual") or {}
            try:
                page = int(visual.get("page") or ev.get("page") or 1)
                y = float(visual.get("y") or 0.0)
                t = float(ev.get("time") or 0.0)
            except Exception:
                page = 0
                y = 0.0
                t = 0.0
            if page > 0 and y > 0.0:
                key = (page, int(round(y / 0.025)))
                current = pdf_cue_row_ranges.get(key)
                if current is None:
                    pdf_cue_row_ranges[key] = [1.0, t, t]
                else:
                    current[0] += 1.0
                    current[1] = min(current[1], t)
                    current[2] = max(current[2], t)
            continue
        if ev.get("isRest") or ev.get("pdfLyricCue"):
            continue
        if not _normalize_lyric_word(ev.get("lyric")):
            continue
        visual = ev.get("visual") or {}
        if not visual:
            continue
        try:
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            page = int(visual.get("page") or ev.get("page") or 1)
            y = float(visual.get("y") or 0.0)
        except Exception:
            continue
        if measure <= 0 or y <= 0.0:
            continue
        lyric_rows_by_measure.setdefault(measure, set()).add((page, int(round(y / 0.025))))

    marked = 0
    for ev in events:
        if ev.get("pdfLyricCue") or _normalize_lyric_word(ev.get("lyric")):
            continue
        visual = ev.get("visual") or {}
        if not visual:
            continue
        try:
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            page = int(visual.get("page") or ev.get("page") or 1)
            y = float(visual.get("y") or 0.0)
        except Exception:
            continue
        row_key = (page, int(round(y / 0.025)))
        if ev.get("isRest"):
            try:
                rest_dur = float(ev.get("noteDuration") or 0.0)
                rest_t = float(ev.get("time") or 0.0)
            except Exception:
                rest_dur = 0.0
                rest_t = 0.0
            cue_range = pdf_cue_row_ranges.get(row_key)
            cue_driven_now = bool(cue_range and cue_range[0] >= 3 and cue_range[1] - 0.6 <= rest_t <= cue_range[2] + 0.6)
            if cue_driven_now and (ev.get("measureRest") or rest_dur >= 1.0):
                ev["skipCursorHighlight"] = True
                ev["shadowCursorReason"] = "spoken-pdf-cues-drive-this-rest-row"
                marked += 1
            continue
        lyric_rows = lyric_rows_by_measure.get(measure)
        if not lyric_rows:
            continue
        if row_key in lyric_rows:
            continue
        ev["skipCursorHighlight"] = True
        ev["shadowCursorReason"] = "same-measure-lyric-on-different-visual-row"
        marked += 1

    if not marked:
        return sync
    out = dict(sync)
    out["events"] = events
    out["shadowCursorNotes"] = {
        "method": "hide-off-row-non-lyric-notes-and-spoken-row-rests",
        "markedEvents": marked,
    }
    return out


def enforce_visual_row_time_order(sync: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if len(events) < 4:
        return sync
    rows: dict[tuple[int, int], list[dict]] = {}
    for ev in events:
        if ev.get("isRest"):
            continue
        if not (_normalize_lyric_word(ev.get("lyric")) or ev.get("pdfLyricCue")):
            continue
        visual = ev.get("visual") or {}
        if not visual:
            continue
        try:
            page = int(visual.get("page") or ev.get("page") or 1)
            y = float(visual.get("y") or 0.0)
        except Exception:
            continue
        if y <= 0.0:
            continue
        rows.setdefault((page, int(round(y / 0.025))), []).append(ev)

    adjusted = 0
    for row_events in rows.values():
        if len(row_events) < 3:
            continue
        row_events.sort(key=lambda ev: (float((ev.get("visual") or {}).get("x") or 0.0), _score_sort_key(ev)))
        prev_time = None
        prev_ev: dict = {}
        for ev in row_events:
            try:
                t = float(ev.get("time") or 0.0)
            except Exception:
                continue
            if prev_time is not None:
                # 歌词间过渡用更大间隔，使
                # 被强制前移的歌词至少可见 100 ms。
                prev_has_lyric = bool(_normalize_lyric_word(prev_ev.get("lyric")))
                cur_has_lyric = bool(_normalize_lyric_word(ev.get("lyric")))
                gap = 0.100 if (prev_has_lyric and cur_has_lyric) else 0.035
                target_time = prev_time + gap
            else:
                target_time = t
            if prev_time is not None and t < target_time - 0.006:
                ev["time"] = round(target_time, 3)
                ev["rowTimeOrderAdjusted"] = True
                ev["source"] = str(ev.get("source") or "") + "+row-time-order"
                adjusted += 1
                t = float(ev["time"])
            prev_time = max(prev_time or t, t)
            prev_ev = ev

    if not adjusted:
        return sync
    events.sort(key=lambda ev: float(ev.get("time") or 0.0))
    out = dict(sync)
    out["events"] = events
    out["rowTimeOrder"] = {"method": "visual-row-x-monotone", "adjustedEvents": adjusted}
    return out


def enforce_page_boundary_time_order(sync: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if len(events) < 4:
        return sync

    # 预计算每个 (page, row_bucket) 的最大时间，以便跨
    # 入新行时使用上一行真实高水位，而非
    # 仅谱序中紧邻事件。次要
    # 声部/谱表音符可能位于更早拍（谱序更靠前）
    # 但携带 pdf-asr-time 修正后的更晚时间戳，
    # 故简单「上一事件」参考不够保守。
    row_max_time: dict[tuple, float] = {}
    for ev in events:
        try:
            page = int((ev.get("visual") or {}).get("page") or ev.get("page") or 1)
            y = float((ev.get("visual") or {}).get("y") or 0.0)
            t = float(ev.get("time") or 0.0)
        except Exception:
            continue
        key = (page, int(round(y / 0.025)))
        row_max_time[key] = max(row_max_time.get(key, 0.0), t)

    score_order = sorted(events, key=_score_sort_key)
    adjusted = 0
    for idx in range(1, len(score_order)):
        prev = score_order[idx - 1]
        cur = score_order[idx]
        prev_page = int((prev.get("visual") or {}).get("page") or prev.get("page") or 1)
        cur_page = int((cur.get("visual") or {}).get("page") or cur.get("page") or 1)

        # 检测视觉边界：换页或换行
        # （同页但视觉 y 跳到新行）。
        is_page_cross = cur_page > prev_page
        is_row_cross = False
        try:
            prev_y = float((prev.get("visual") or {}).get("y") or 0.0)
            cur_y = float((cur.get("visual") or {}).get("y") or 0.0)
        except Exception:
            prev_y = cur_y = 0.0
        if cur_page == prev_page:
            is_row_cross = cur_y > prev_y + 0.05

        if not is_page_cross and not is_row_cross:
            continue

        try:
            cur_t = float(cur.get("time") or 0.0)
        except Exception:
            continue

        # 用上一行所有事件的最大时间（不限于
        # 谱序紧邻事件）作为有效下界。
        prev_row_key = (prev_page, int(round(prev_y / 0.025)))
        effective_prev_t = row_max_time.get(prev_row_key, float(prev.get("time") or 0.0))

        target_t = effective_prev_t + 0.040
        if cur_t >= target_t:
            continue
        # 若所需前移很大 (>= 3 s)，几乎肯定是
        # 反复记号场景：同一视觉行在两种
        # 音频时间被访问。强制前移会造成
        # 较早段落严重行内倒置。此处跳过，依赖
        # enforce_visual_row_time_order 整理行内顺序。
        if target_t - cur_t >= 3.0:
            continue
        cur["time"] = round(target_t, 3)
        cur["pageBoundaryAdjusted"] = True
        tag = "+page-boundary-order" if is_page_cross else "+row-boundary-order"
        cur["source"] = str(cur.get("source") or "") + tag
        adjusted += 1

        # 同时更新当前行 row_max_time 以反映前移。
        cur_row_key = (cur_page, int(round(cur_y / 0.025)))
        row_max_time[cur_row_key] = max(row_max_time.get(cur_row_key, 0.0), target_t)

        # 跨页时级联前移以推动新页
        # 共享同一压缩时间戳的首批事件。跨行
        # 同样级联但限于同一新行事件。
        carry_t = target_t
        j = idx + 1
        while j < len(score_order):
            nxt = score_order[j]
            nxt_page = int((nxt.get("visual") or {}).get("page") or nxt.get("page") or 1)
            if nxt_page != cur_page:
                break
            if is_row_cross:
                try:
                    nxt_y = float((nxt.get("visual") or {}).get("y") or 0.0)
                except Exception:
                    break
                if abs(nxt_y - cur_y) > 0.05:
                    break
            try:
                nxt_t = float(nxt.get("time") or 0.0)
            except Exception:
                break
            if is_page_cross:
                # 跨页：扫描新页首行所有事件
                # 并将仍低于边界阈值的时间前移。
                # 已安全超过阈值的事件跳过 (continue)，
                # 需极大前移 (>= 3 s) 的也跳过。
                try:
                    nxt_y_val = float((nxt.get("visual") or {}).get("y") or 0.0)
                except Exception:
                    nxt_y_val = cur_y
                on_first_row = abs(nxt_y_val - cur_y) < 0.05
                if on_first_row:
                    if nxt_t >= effective_prev_t + 0.054:
                        j += 1
                        continue  # already fine
                    if effective_prev_t + 0.040 - nxt_t >= 3.0:
                        j += 1
                        continue  # large-push guard
                    if nxt_t < effective_prev_t + 0.040:
                        carry_t = max(carry_t + 0.014, effective_prev_t + 0.040)
                        nxt["time"] = round(carry_t, 3)
                        nxt["pageBoundaryAdjusted"] = True
                        nxt["source"] = str(nxt.get("source") or "") + tag
                        adjusted += 1
                        row_max_time[cur_row_key] = max(row_max_time.get(cur_row_key, 0.0), carry_t)
                    j += 1
                    continue
                else:
                    # 非首行：用原紧密级联逻辑
                    if nxt_t >= carry_t + 0.014:
                        break
                    if carry_t + 0.014 - nxt_t >= 3.0:
                        break
                    carry_t += 0.014
                    nxt["time"] = round(carry_t, 3)
                    nxt["pageBoundaryAdjusted"] = True
                    nxt["source"] = str(nxt.get("source") or "") + tag
                    adjusted += 1
                    j += 1
                    continue
            else:
                if nxt_t >= carry_t + 0.014:
                    break
                # 同样的大前移防护：移动 >= 3 s 则跳过
                if carry_t + 0.014 - nxt_t >= 3.0:
                    break
                carry_t += 0.014
                nxt["time"] = round(carry_t, 3)
                nxt["pageBoundaryAdjusted"] = True
                nxt["source"] = str(nxt.get("source") or "") + tag
                adjusted += 1
            j += 1

    if not adjusted:
        return sync
    events.sort(key=lambda ev: float(ev.get("time") or 0.0))
    out = dict(sync)
    out["events"] = events
    out["pageBoundaryOrder"] = {"method": "score-page-row-boundary-monotone", "adjustedEvents": adjusted}
    return out


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout
    except Exception as exc:
        return 999, f"{type(exc).__name__}: {exc}"

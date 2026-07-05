

def audio_duration() -> float:
    ffprobe = shutil.which("ffprobe") or r"C:\ffmpeg\bin\ffprobe.exe"
    if not ffprobe or not Path(ffprobe).exists():
        return 99.432
    rc, out = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(SOURCE_AUDIO),
        ],
        timeout=30,
    )
    if rc == 0:
        try:
            return float(out.strip())
        except ValueError:
            pass
    return 99.432


def find_audiveris_command() -> list[str] | None:
    if not AUDIVERIS.is_dir():
        return None
    launchers = []
    for pattern in ("Audiveris*.bat", "audiveris*.bat", "Audiveris*.cmd", "audiveris*.cmd", "Audiveris*.exe", "audiveris*.exe"):
        launchers.extend(AUDIVERIS.rglob(pattern))
    launchers = [p for p in launchers if p.is_file()]
    if launchers:
        return [str(sorted(launchers, key=lambda p: len(str(p)))[0])]

    jars = list(AUDIVERIS.rglob("audiveris*.jar")) + list(AUDIVERIS.rglob("Audiveris*.jar"))
    jars = [p for p in jars if p.is_file()]
    if jars and JAVA.is_file():
        return [str(JAVA), "-jar", str(sorted(jars, key=lambda p: len(str(p)))[0])]
    return None


def _omr_sheet_num(name: str) -> int | None:
    """Parse the integer page number from 'sheet#N/...' OMR paths.

    Audiveris can use alphanumeric IDs (e.g. 'sheet#4C'). We extract only the
    leading digits to stay robust.
    """
    try:
        raw = name.split("sheet#")[1].split("/")[0]
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        return int(digits) if digits else None
    except Exception:
        return None


def _omr_measure_id(meas_el) -> int:
    """Parse an Audiveris measure id attribute tolerantly.

    IDs like '4', '4C', '4b' → extract leading digits.
    Falls back to 0 if not parseable.
    """
    raw = str(meas_el.attrib.get("id", "0") or "0")
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        else:
            break
    try:
        return int(digits) if digits else 0
    except Exception:
        return 0


def find_omr_file() -> Path | None:
    """Return the .omr file for the current song, regardless of its filename.

    Prefers <SONG_ID>.omr; falls back to any .omr in the omr/ directory.
    """
    canonical = GENERATED / "omr" / f"{SONG_ID}.omr"
    if canonical.is_file():
        return canonical
    out_dir = GENERATED / "omr"
    candidates = sorted(out_dir.glob("*.omr")) if out_dir.is_dir() else []
    if candidates:
        # 重命名为规范名供后续调用
        try:
            candidates[0].rename(canonical)
            return canonical
        except Exception:
            return candidates[0]
    return None


def try_omr() -> dict:
    out_dir = GENERATED / "omr"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = find_audiveris_command()
    result = {
        "available": bool(cmd),
        "attempted": False,
        "success": False,
        "command": cmd,
        "output": "",
        "musicxml": None,
    }
    if not cmd:
        result["output"] = "Audiveris command was not found under P:\\PonyChat\\misc\\tools\\audiveris."
        return result

    candidates = [
        cmd + ["-batch", "-export", "-output", str(out_dir), str(SOURCE_PDF)],
        cmd + ["-batch", "-export", str(SOURCE_PDF)],
    ]
    for attempt in candidates:
        result["attempted"] = True
        rc, out = run(attempt, timeout=900)
        result["output"] += f"\n$ {' '.join(attempt)}\nexit={rc}\n{out[-4000:]}\n"
        found = find_musicxml(out_dir)
        if rc == 0 and found:
            result["success"] = True
            result["musicxml"] = str(found.relative_to(ROOT))
            return result
    found = find_musicxml(out_dir)
    if found:
        result["success"] = True
        result["musicxml"] = str(found.relative_to(ROOT))
    return result


def find_musicxml(path: Path) -> Path | None:
    """Find the best MusicXML file in path.

    When multiple .mxl movement files are present, merge them first and
    return the merged .musicxml.  Otherwise fall back to the first file found.
    """
    # 检查是否有多个需合并的 .mxl 文件
    mxl_files = sorted(path.glob("*.mxl"))
    if len(mxl_files) >= 2:
        # 删除过期的合并 musicxml，mxl 变更时重新合并
        canonical = path / f"{SONG_ID}.musicxml"
        if canonical.exists():
            # 任一 mxl 新于合并文件则重新合并
            mxl_mtime = max(f.stat().st_mtime for f in mxl_files)
            if mxl_mtime > canonical.stat().st_mtime:
                canonical.unlink()
        if not canonical.exists():
            merged = merge_mxl_movements(path)
            if merged:
                return merged
        else:
            return canonical

    for ext in ("*.musicxml", "*.xml", "*.mxl"):
        files = sorted(path.rglob(ext))
        if files:
            return files[0]
    return None


def merge_mxl_movements(out_dir: Path) -> Path | None:
    """Merge multiple Audiveris movement .mxl files into one combined MusicXML.

    When Audiveris splits a long score into mvt1, mvt2, … the measures are
    locally numbered 1..N in each movement.  This function:
    1. Extracts and parses each MXL in order.
    2. For every part that appears in movement 1, appends the corresponding
       part's measures from subsequent movements, renumbering them to follow
       the last measure of the preceding movement.
    3. Extra parts that appear only in later movements are appended at the end.
    4. Writes the merged result to <out_dir>/<SONG_ID>.musicxml.

    Returns the path of the merged file, or None on failure.
    """
    mxl_files = sorted(out_dir.glob("*.mxl"))
    if len(mxl_files) < 2:
        return None  # nothing to merge

    out_path = out_dir / f"{SONG_ID}.musicxml"

    # 解析所有乐章
    movements: list[ET.Element] = []
    for mxl in mxl_files:
        try:
            with zipfile.ZipFile(str(mxl)) as z:
                xmls = [
                    n for n in z.namelist()
                    if n.lower().endswith((".xml", ".musicxml")) and "container" not in n.lower()
                ]
                if not xmls:
                    continue
                movements.append(ET.fromstring(z.read(xmls[0])))
        except Exception as exc:
            print(f"{SONG_ID}: merge_mxl: cannot read {mxl.name}: {exc}")
    if not movements:
        return None
    if len(movements) < 2:
        # 仅一个可读乐章
        out_path.write_bytes(ET.tostring(movements[0], encoding="unicode").encode("utf-8"))
        return out_path

    base = movements[0]
    # 检测命名空间
    root_tag = base.tag
    ns = root_tag[1:root_tag.index("}")] if root_tag.startswith("{") else ""
    ns_prefix = f"{{{ns}}}" if ns else ""
    part_tag = f"{ns_prefix}part"
    measure_tag = f"{ns_prefix}measure"

    def get_parts(root: ET.Element) -> list[ET.Element]:
        return list(root.findall(f".//{part_tag}"))

    def get_part_id(part: ET.Element) -> str:
        return part.attrib.get("id", "")

    # 构建基础 parts 字典
    base_parts = {get_part_id(p): p for p in get_parts(base)}

    # 查找 part 中最大小节号
    def max_measure_num(part: ET.Element) -> int:
        nums = []
        for m in part.findall(measure_tag):
            try:
                nums.append(int(m.attrib.get("number", "0")))
            except ValueError:
                pass
        return max(nums) if nums else 0

    def renumber_measures(part: ET.Element, offset: int) -> None:
        for m in part.findall(measure_tag):
            try:
                num = int(m.attrib.get("number", "0"))
                m.set("number", str(num + offset))
            except ValueError:
                pass

    import copy

    # 将后续各乐章 parts 追加到 base parts
    for mvt in movements[1:]:
        mvt_parts_list = get_parts(mvt)
        mvt_parts = {get_part_id(p): p for p in mvt_parts_list}

        # 确定相对 base 的偏移
        offsets: dict[str, int] = {}
        for pid, base_part in base_parts.items():
            offsets[pid] = max_measure_num(base_part)

        # 为尚未在 base 中的 part 找公共偏移
        global_offset = max(offsets.values()) if offsets else 0

        for mvt_part in mvt_parts_list:
            pid = get_part_id(mvt_part)
            # 深拷贝本乐章 part 的小节
            mvt_measures = [copy.deepcopy(m) for m in mvt_part.findall(measure_tag)]
            offset = offsets.get(pid, global_offset)
            # 重新编号
            for m in mvt_measures:
                try:
                    m.set("number", str(int(m.attrib.get("number", "0")) + offset))
                except ValueError:
                    pass
            if pid in base_parts:
                # 将小节追加到已有 part
                for m in mvt_measures:
                    base_parts[pid].append(m)
            else:
                # 本乐章新 part：创建骨架并插入
                new_part = ET.SubElement(base, part_tag)
                new_part.set("id", pid)
                for m in mvt_measures:
                    new_part.append(m)
                base_parts[pid] = new_part
    # 合并后续乐章 part-list 条目（避免重复）
    part_list_tag = f"{ns_prefix}part-list"
    score_part_tag = f"{ns_prefix}score-part"
    base_part_list = base.find(part_list_tag)
    existing_ids = {sp.attrib.get("id") for sp in base_part_list.findall(score_part_tag)} if base_part_list is not None else set()
    for mvt in movements[1:]:
        pl = mvt.find(part_list_tag)
        if pl is None or base_part_list is None:
            continue
        for sp in pl.findall(score_part_tag):
            if sp.attrib.get("id") not in existing_ids:
                base_part_list.append(copy.deepcopy(sp))
                existing_ids.add(sp.attrib.get("id"))

    merged_xml = ET.tostring(base, encoding="unicode")
    out_path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n{merged_xml}', encoding="utf-8")
    # 统计合并后小节数
    total = sum(
        len(list(p.findall(measure_tag)))
        for p in get_parts(base)
    )
    max_m = max(
        (max_measure_num(p) for p in get_parts(base)),
        default=0,
    )
    print(f"{SONG_ID}: merged {len(mxl_files)} movements → {max_m} measures in {len(base_parts)} parts → {out_path.name}")
    return out_path


def materialize_musicxml(path: Path | None) -> Path | None:
    if not path or not path.exists():
        return None
    out = GENERATED / "omr" / f"{SONG_ID}.musicxml"
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as z:
            names = [
                n
                for n in z.namelist()
                if n.lower().endswith((".xml", ".musicxml")) and "container" not in n.lower()
            ]
            if not names:
                return None
            out.write_bytes(z.read(names[0]))
            return out
    if path != out:
        shutil.copyfile(path, out)
    return out

# -*- coding: utf-8 -*-
"""
MLP 维基数据清洗脚本
输入：data/mlp/pages/*.txt
输出：data/mlp/clean/*.txt

清洗规则（所有保留页面通用）：
  - 整段删除：配音、图集、相关商品、参考、外部链接、注释、广告、另见、参见、导航
  - 底部导航大表删除（触发词见 NAV_BLOCK_TRIGGERS）
  - 信息框中无用制作字段删除（季编号/公映日期/剧本/分镜/演唱/调号/专辑等）
  - 引用编号 [1][注1] 删除
  - 引用链接行（↑开头）删除
  - 末尾"英文原文：XXX"删除
  - 多余空行合并

直接丢弃：重定向页、MLP维基/模板页、清洗后内容不足 80 字的页面
去重：内容相同只保留中文名版本
"""

import re
import sys
import hashlib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAGES_DIR = Path(__file__).parent / "pages"
CLEAN_DIR = Path(__file__).parent / "clean"
# 测试模式时由外部覆盖这两个变量
CLEAN_DIR.mkdir(exist_ok=True)

# ── 整段删除的节标题 ──────────────────────────────────────────────────────────
REMOVE_SECTION_HEADERS = {
    "配音", "图集", "相关商品", "参考", "外部链接",
    "注释", "广告", "另见", "参见", "导航",
}

# ── 跳过标签本身 + 紧随的下一个非空行（值行）────────────────────────────────
# 用于「上一集 / 搅局行家」这种「标签-值」对，值太短无法靠格式区分节标题
SKIP_LABEL_AND_NEXT_VALUE = {"上一集", "下一集"}

# ── 导航大表触发词（命中即跳过此行到文件末）────────────────────────────────────
NAV_BLOCK_TRIGGERS = {
    "主要角色", "背景小马", "非小马角色", "王室", "苹果家族",
    "派家族", "反派", "小马国女孩角色", "Young Six", "闪电天马",
    "学龄小马", "剧集、电影和动画短片", "友谊就是魔法",
}

# ── 信息框中需要删除的制作/元数据字段（仅对前 60 行生效）──────────────────────
INFOBOX_DISCARD_LABELS = {
    "季编号", "集编号", "总编号", "公映日期",
    "剧本", "分镜", "导演",
    "演唱", "音乐", "调号", "长度", "专辑", "电影对白",
    "制作",   # 歌曲页制作人员
    "对白",   # "对白 • 图集 • 数据"那行的前置
}

# 信息框中始终保留的字段名（即使很短，也不被当成「值」而跳过）
INFOBOX_KEEP_LABELS = {
    "电影", "角色", "重要角色",
    "种族", "性别", "居所", "身份",
    "昵称", "亲属", "可爱标记",
    "眼睛", "鬃毛", "体色", "眼影", "魔法色",
    "更多信息", "地区", "首次出场",
}

INFOBOX_ZONE = 60  # 只在前 N 行处理信息框


def is_redirect(lines: list) -> bool:
    non_empty = [l.strip() for l in lines if l.strip()]
    return len(non_empty) <= 4 and any("重定向到" in l for l in non_empty)


def is_discard_page(path: Path, lines: list) -> bool:
    name = path.stem
    if name.startswith("MLP中文维基") or name.startswith("Template:"):
        return True
    if is_redirect(lines):
        return True
    return False


def is_nav_block_start(stripped: str) -> bool:
    if stripped.count("•") >= 3:
        return True
    return stripped in NAV_BLOCK_TRIGGERS


def looks_like_section_header(stripped: str) -> bool:
    if not stripped:
        return False
    if len(stripped) > 40:
        return False
    if stripped.endswith(("。", "，", "、", "；", "：", "…", "！", "？")):
        return False
    if stripped.startswith(("（", "「", "↑", "•", "[")):
        return False
    if "•" in stripped or "↑" in stripped:
        return False
    # 配音演员格式："姓名（英语/日语/粤语/韩语）"——不是节标题
    if re.search(r'（[英日粤韩法德意西]语[^）]*）', stripped):
        return False
    # 集数格式："S2E15"、"S3E01" 等——不是节标题
    if re.match(r'^S\d+E\d+', stripped):
        return False
    return True


def remove_ref_numbers(text: str) -> str:
    text = re.sub(r'\[注\s*\d+\]', '', text)
    text = re.sub(r'\[原文如此\]', '', text)
    text = re.sub(r'\[详列\]', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    return text


def clean_text(raw: str):
    lines = raw.splitlines()

    if is_redirect(lines):
        return None

    result = []
    skip_section = False
    in_nav_block = False
    skip_next_value = False   # 跳过「上一集/下一集」后面的集名值行

    # 信息框状态机
    in_infobox = True
    skip_infobox_values = False  # 正在跳过某个 DISCARD 字段的值行
    passed_first_paragraph = False

    blank_count = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # ── 进入导航大表后跳过到末尾 ───────────────────────────────────────
        if not in_nav_block and is_nav_block_start(stripped):
            in_nav_block = True
            continue
        if in_nav_block:
            continue

        # ── 末尾英文原文行 ─────────────────────────────────────────────────
        if stripped.startswith("英文原文：") or stripped.startswith("英文原文:"):
            continue

        # ── 引用链接行 ─────────────────────────────────────────────────────
        if stripped.startswith("↑"):
            continue

        # ── 跳过上一集/下一集的值（集名）──────────────────────────────────
        if skip_next_value:
            if stripped:          # 非空行 = 就是那个值，跳过并关闭标志
                skip_next_value = False
                continue
            else:                 # 空行先跳过，等非空行
                continue

        # ── 「上一集/下一集」标签本身 ──────────────────────────────────────
        if stripped in SKIP_LABEL_AND_NEXT_VALUE:
            skip_next_value = True
            continue

        # ── 节标题检测 → 开始跳过该节 ──────────────────────────────────────
        if stripped in REMOVE_SECTION_HEADERS:
            skip_section = True
            continue

        # ── 跳过节：等待下一个合法节标题 ───────────────────────────────────
        if skip_section:
            if (stripped
                    and looks_like_section_header(stripped)
                    and stripped not in REMOVE_SECTION_HEADERS):
                skip_section = False
                # 当前行是新节标题，继续正常处理
            else:
                continue

        # ── 信息框处理（仅前 INFOBOX_ZONE 行，且未遇到第一段正文）──────────
        if in_infobox and i < INFOBOX_ZONE and not passed_first_paragraph:
            # 检测是否已进入正文段落
            if (len(stripped) > 40
                    and stripped.endswith(("。", "！", "？", "…"))
                    and not stripped.startswith("#")):
                passed_first_paragraph = True
                in_infobox = False
                # 此行是正文，正常处理（不 continue）

            elif skip_infobox_values:
                # 当前处于跳过某字段值的状态
                if not stripped:
                    # 空行 = 值结束
                    skip_infobox_values = False
                    blank_count += 1
                    if blank_count <= 1:
                        result.append("")
                    continue
                if (len(stripped) < 35
                        and stripped not in INFOBOX_KEEP_LABELS
                        and stripped not in REMOVE_SECTION_HEADERS):
                    # 是值行，跳过
                    continue
                else:
                    # 遇到新标签或长内容，结束跳过
                    skip_infobox_values = False
                    # 继续处理当前行

            if in_infobox and not skip_infobox_values:
                if stripped in INFOBOX_DISCARD_LABELS:
                    skip_infobox_values = True
                    continue  # 跳过标签行本身

        # ── 空行合并 ────────────────────────────────────────────────────────
        if not stripped:
            blank_count += 1
            if blank_count <= 1:
                result.append("")
            continue
        else:
            blank_count = 0

        result.append(line)

    cleaned = "\n".join(result)
    cleaned = remove_ref_numbers(cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    if len(cleaned) < 80:
        return None

    return cleaned


def content_hash(text: str) -> str:
    lines = [l.strip() for l in text.splitlines()
             if l.strip() and not l.startswith("#")]
    body = "\n".join(lines[:60])
    return hashlib.md5(body.encode("utf-8")).hexdigest()


def is_chinese_title(name: str) -> bool:
    cn = sum(1 for c in name if '\u4e00' <= c <= '\u9fff')
    return cn >= len(name) * 0.4


def main(test_limit: int = 0):
    pages = sorted(PAGES_DIR.glob("*.txt"))
    if test_limit:
        pages = pages[:test_limit]
    total = len(pages)
    print(f"输入文件数：{total}")

    seen_hashes: dict = {}
    kept = skipped_discard = skipped_duplicate = skipped_short = 0

    # 中文名优先
    pages_sorted = sorted(
        pages,
        key=lambda p: (0 if is_chinese_title(p.stem) else 1, p.name)
    )

    for path in pages_sorted:
        with open(path, encoding="utf-8") as f:
            raw = f.read()

        if is_discard_page(path, raw.splitlines()):
            skipped_discard += 1
            continue

        cleaned = clean_text(raw)

        if cleaned is None:
            skipped_short += 1
            continue

        h = content_hash(cleaned)
        if h in seen_hashes:
            skipped_duplicate += 1
            continue
        seen_hashes[h] = path.name

        out_path = CLEAN_DIR / path.name
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
        kept += 1

    clean_files = list(CLEAN_DIR.glob("*.txt"))
    total_bytes = sum(p.stat().st_size for p in clean_files)

    print(f"\n清洗完成！")
    print(f"  保留：{kept}")
    print(f"  跳过（维基/重定向）：{skipped_discard}")
    print(f"  跳过（重复内容）：{skipped_duplicate}")
    print(f"  跳过（内容过少）：{skipped_short}")
    print(f"  输出体积：{total_bytes/1024/1024:.2f} MB")
    print(f"  输出目录：{CLEAN_DIR}")


if __name__ == "__main__":
    import sys as _sys
    limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else 0
    main(test_limit=limit)

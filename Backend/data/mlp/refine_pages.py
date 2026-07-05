# -*- coding: utf-8 -*-
"""
MLP 维基页面改写脚本（第二次 LLM 处理）

输入：data/mlp/clean/*.txt  +  data/mlp/tags.jsonl
输出：data/mlp/refined/*.txt

- skip：跳过
- song：直接复制 clean 文件（target_words=0）
- 其他：按 type/importance/target_words 调用 LLM 改写

关键参数：
  reasoning_effort = "minimal"  → 1-2s/次，不触发内部思考链
  max_tokens       = 1800       → 足够输出 ~1500 汉字
  timeout          = 45s
  workers          = 15

支持断点续传。
"""

import sys
import json
import time
import re
import shutil
import threading
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR    = Path(__file__).parent
CLEAN_DIR   = BASE_DIR / "clean"
REFINED_DIR = BASE_DIR / "refined"
TAGS_FILE   = BASE_DIR / "tags.jsonl"
REFINED_DIR.mkdir(exist_ok=True)

# ── API 配置 ──────────────────────────────────────────────────────────────────
def load_api_config():
    root = BASE_DIR.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.model_manager import load_merged_model_config
    cfg = load_merged_model_config()
    for m in cfg.get("models", []):
        if m.get("id") == "doubao-2-0-mini":
            return m["endpoint"], m["api_key"], m["model_name"]
    raise RuntimeError("未找到 doubao-2-0-mini 配置")

ENDPOINT, API_KEY, MODEL_NAME = load_api_config()
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}

# ── Prompt 模板 ────────────────────────────────────────────────────────────────
# 字数说明放在 user 侧而非 system 侧，减少 system prompt 大小

SYS = {
    "character": (
        "你是《我的小马驹：友谊就是魔法》世界设定编辑。"
        "将给定的维基页面改写为角色设定卡，Markdown 格式，结构为：\n"
        "# 中文名（英文名）\n> 一句话简介\n## 外观\n## 性格\n## 背景与经历\n## 人际关系\n"
        "要求：流畅叙述，删除配音/商品/导航/版权；如信息不足则如实写；不要编造；仅输出 Markdown 正文。"
    ),
    "location": (
        "你是《我的小马驹：友谊就是魔法》世界设定编辑。"
        "将给定的维基页面改写为地点设定描述，Markdown 格式，结构为：\n"
        "# 地点名（英文名）\n> 一句话简介\n## 描述\n## 历史与背景\n## 在剧情中的作用\n"
        "要求：流畅叙述，删除配音/商品/导航/版权；仅输出 Markdown 正文。"
    ),
    "episode": (
        "你是《我的小马驹：友谊就是魔法》内容编辑。"
        "将给定的维基页面改写为剧情摘要，Markdown 格式，结构为：\n"
        "# 标题\n> 类型/集数信息\n## 剧情概要\n## 主要角色\n## 主题\n"
        "要求：保留剧情，删除配音/商品/导航；仅输出 Markdown 正文。"
    ),
    "concept": (
        "你是《我的小马驹：友谊就是魔法》世界设定编辑。"
        "将给定的维基页面改写为世界设定说明，Markdown 格式，结构为：\n"
        "# 概念名（英文名）\n> 一句话简介\n## 说明\n## 在剧情中的体现\n"
        "要求：流畅叙述，删除噪音；仅输出 Markdown 正文。"
    ),
    "race": (
        "你是《我的小马驹：友谊就是魔法》世界设定编辑。"
        "将给定的维基页面改写为种族介绍，Markdown 格式，结构为：\n"
        "# 种族名（英文名）\n> 一句话简介\n## 外观与特征\n## 能力\n## 文化与分布\n## 代表角色\n"
        "要求：流畅叙述，删除噪音；仅输出 Markdown 正文。"
    ),
    "item": (
        "你是《我的小马驹：友谊就是魔法》世界设定编辑。"
        "将给定的维基页面改写为道具说明，Markdown 格式，结构为：\n"
        "# 物品名（英文名）\n> 一句话简介\n## 外观\n## 功能与用途\n## 剧情中的作用\n"
        "要求：流畅叙述，删除噪音；仅输出 Markdown 正文。"
    ),
}

# ── 单次 LLM 调用 ─────────────────────────────────────────────────────────────
def call_api(system: str, user: str, max_tokens: int) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "reasoning_effort": "minimal",   # 关键：不触发思考链，响应 1-3s
        "max_tokens": 8192,
        "temperature": 0.4,
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{ENDPOINT}/chat/completions",
                headers=HEADERS,
                json=payload,
                timeout=45,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # 去掉偶发的 ```markdown 包裹
            text = re.sub(r"^```(?:markdown)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text.strip())
            return text
        except Exception as e:
            wait = 2 * (attempt + 1)
            print(f"    [重试{attempt+1}/3] {e}  等{wait}s", flush=True)
            time.sleep(wait)
    return ""   # 三次失败返回空串


# ── 处理单个文件 ───────────────────────────────────────────────────────────────
def process_tag(tag: dict) -> tuple[str, str, bool]:
    fname  = tag["file"]
    t      = tag["type"]
    target = tag.get("target_words", 800)
    src    = CLEAN_DIR / fname
    dst    = REFINED_DIR / fname

    if not src.exists():
        return fname, "源文件不存在", False

    raw = src.read_text(encoding="utf-8")

    # 歌曲：直接复制
    if t == "song":
        shutil.copy2(src, dst)
        return fname, "song→复制", True

    # 截取合理长度的输入（target 越大给越多原文）
    max_input = min(len(raw), max(1200, target * 2))
    head = raw[:max_input]

    sys_p  = SYS.get(t, SYS["concept"])
    user_p = (
        f"文件名：{fname}\n"
        f"改写目标：约 {target} 字（中文字符）\n\n"
        f"原始内容：\n\n{head}"
    )

    max_tok = 8192

    result = call_api(sys_p, user_p, max_tok)

    # 空结果或被拒绝（模型返回拒绝语）→ 降级为直接复制 clean 文件
    REFUSAL_MARKERS = ("不良信息", "不符合", "无法处理", "抱歉，我", "很抱歉", "我不能")
    if not result or any(m in result for m in REFUSAL_MARKERS):
        shutil.copy2(src, dst)
        return fname, f"{t}/拒绝→复制clean", True

    dst.write_text(result, encoding="utf-8")
    return fname, f"{t}/{tag.get('importance','')}", True


# ── 主流程 ────────────────────────────────────────────────────────────────────
def load_tags() -> list[dict]:
    return [
        json.loads(l)
        for l in TAGS_FILE.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


PRINT_LOCK = threading.Lock()
completed_count = [0]


def main():
    tags  = load_tags()
    total = len(tags)
    active = [t for t in tags if not t.get("skip", False)]
    done   = {p.name for p in REFINED_DIR.glob("*.txt")}
    todo   = [t for t in active if t["file"] not in done]

    print(f"共 {total} 条标记  有效 {len(active)}  已完成 {len(done)}  待处理 {len(todo)}")
    print(f"skip 类型（真实人物等）: {total - len(active)} 个，直接跳过")
    if not todo:
        print("全部完成！")
        return

    start_time = time.time()
    type_counts: dict[str, int] = {}
    fail_list: list[str] = []

    def report(fname, status, ok):
        with PRINT_LOCK:
            completed_count[0] += 1
            n       = completed_count[0]
            elapsed = time.time() - start_time
            speed   = n / elapsed if elapsed > 0 else 0
            eta     = int((len(todo) - n) / speed) if speed > 0 else 0
            flag    = "✓" if ok else "✗"
            print(f"  [{n:4d}/{len(todo)}] {flag} {fname[:40]:40s} {status}  ({speed:.1f}/s ETA {eta}s)")

    with ThreadPoolExecutor(max_workers=15) as pool:
        futures = {pool.submit(process_tag, tag): tag for tag in todo}
        for fut in as_completed(futures):
            tag = futures[fut]
            try:
                fname, status, ok = fut.result()
            except Exception as e:
                fname, status, ok = tag["file"], f"异常:{e}", False
            if not ok:
                fail_list.append(fname)
            t = tag["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
            report(fname, status, ok)

    elapsed = time.time() - start_time
    print(f"\n── 完成 ──  耗时 {elapsed:.0f}s  失败 {len(fail_list)} 个")
    if fail_list:
        print("失败文件：")
        for f in fail_list[:20]:
            print(f"  {f}")
    print(f"输出目录：{REFINED_DIR}")
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:12s}: {cnt}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
MLP 维基页面分类打标脚本（第一次 LLM 处理）

输入：data/mlp/clean/*.txt（本目录下 clean/）
输出：data/mlp/tags.jsonl（每行一个 JSON，可人工检查后再跑改写）

标记格式：
{
  "file": "暮光闪闪.txt",
  "type": "character|location|song|episode|concept|race|item|skip",
  "cn_name": "暮光闪闪",
  "importance": "major|supporting|minor|background|",
  "target_words": 2000,
  "skip": false,
  "skip_reason": ""
}

支持断点续传：已标记的文件自动跳过。
"""

import sys
import json
import time
import re
import threading
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
CLEAN_DIR  = BASE_DIR / "clean"
TAGS_FILE  = BASE_DIR / "tags.jsonl"

# ── 从模型清单与各供应商片段合并后的配置读取 API ─────────────────────────────
def load_api_config():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.model_manager import load_merged_model_config
    cfg = load_merged_model_config()
    models = cfg.get("models", [])
    for m in models:
        if m.get("id") == "doubao-2-0-mini":
            return m["endpoint"], m["api_key"], m["model_name"]
    raise RuntimeError("未找到 doubao-2-0-mini 配置")

ENDPOINT, API_KEY, MODEL_NAME = load_api_config()

# ── 打标 Prompt ────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是《我的小马驹：友谊就是魔法》（MLP:FiM）维基内容分类助手。
分析给定的维基页面片段，输出 JSON 分类标签。

【类型说明】
- character ：剧中虚构角色（小马、龙、狮鹫、人类等）
- location  ：地点（城市、建筑、地区、国家等）
- song      ：歌曲页面（含歌词）
- episode   ：剧集、电影、特辑、动画短片
- concept   ：概念/机制（魔法、可爱标记系统、友谊元素、组织团体等）
- race      ：种族/生物类型（天马族、独角兽族等类型介绍页）
- item      ：道具/物品（魔法道具、宝石、装备等）
- skip      ：不处理（真实人物/配音演员/制作人员、制作工艺页、汇总统计列表页、维基维护页等）

【重要程度】（character 和 location 类型必填，其他留空字符串）
- major      ：六人组/主角、塞拉斯蒂娅/露娜/斯派克等核心角色；小马镇/水晶帝国等主要地点
- supporting ：重要配角，多集有关键戏份
- minor      ：次要角色，有名字有一定戏份
- background ：极少戏份的背景角色

【target_words】改写目标字数（中文字符数）：
- major character     → 2000
- supporting character→ 1500
- minor character     → 1000
- background character→ 500
- major location      → 1000
- minor/other location→ 500
- episode             → 800
- concept/race/item   → 800
- song                → 0（保留原文歌词，不改写）
- skip                → 0

【输出格式】仅输出 JSON，不要任何其他文字：
{"type":"...","cn_name":"...","importance":"...","target_words":0,"skip":false,"skip_reason":""}"""


def tag_page(filename: str, content_head: str) -> dict:
    """调用 LLM 对单个页面打标"""
    user_msg = f"文件名：{filename}\n\n以下是页面内容片段：\n\n{content_head}"

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "reasoning_effort": "minimal",   # 分类任务不需要深度思考
        "max_tokens": 8192,
        "temperature": 0.1,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    for attempt in range(4):
        try:
            resp = requests.post(
                f"{ENDPOINT}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

            # 提取 JSON（模型偶尔会带 markdown 代码块）
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                raise ValueError(f"响应中无 JSON：{raw[:100]}")
            tag = json.loads(m.group())

            # 补全缺失字段
            tag.setdefault("file", filename)
            tag.setdefault("type", "skip")
            tag.setdefault("cn_name", filename.replace(".txt", ""))
            tag.setdefault("importance", "")
            tag.setdefault("target_words", 0)
            tag.setdefault("skip", tag.get("type") == "skip")
            tag.setdefault("skip_reason", "")
            tag["file"] = filename
            return tag

        except Exception as e:
            wait = 2 ** attempt
            print(f"  [重试 {attempt+1}/4] {e}，等待 {wait}s ...")
            time.sleep(wait)

    # 全部失败，标记为 skip
    return {
        "file": filename,
        "type": "skip",
        "cn_name": filename.replace(".txt", ""),
        "importance": "",
        "target_words": 0,
        "skip": True,
        "skip_reason": "API 调用失败",
    }


def load_done() -> set:
    done = set()
    if TAGS_FILE.exists():
        for line in TAGS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["file"])
                except Exception:
                    pass
    return done


WRITE_LOCK = threading.Lock()


def process_one(args):
    """线程工作函数：读取文件 → 打标 → 返回 (tag, path.name)"""
    path, idx, total = args
    text = path.read_text(encoding="utf-8")
    head = text[:800]
    tag = tag_page(path.name, head)
    return tag, path.name, idx, total


def main():
    pages = sorted(CLEAN_DIR.glob("*.txt"))
    total = len(pages)
    done = load_done()
    todo = [p for p in pages if p.name not in done]

    print(f"共 {total} 个文件，已标记 {len(done)}，待处理 {len(todo)}")
    if not todo:
        print("全部完成！")
        return

    type_counts: dict = {}
    completed = 0

    with open(TAGS_FILE, "a", encoding="utf-8") as fout:
        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {
                pool.submit(process_one, (p, i + 1, len(todo))): p
                for i, p in enumerate(todo)
            }
            for fut in as_completed(futures):
                try:
                    tag, fname, idx, ttl = fut.result()
                except Exception as e:
                    fname = futures[fut].name
                    tag = {
                        "file": fname, "type": "skip", "cn_name": fname.replace(".txt", ""),
                        "importance": "", "target_words": 0,
                        "skip": True, "skip_reason": f"异常:{e}",
                    }
                    idx, ttl = 0, len(todo)

                with WRITE_LOCK:
                    fout.write(json.dumps(tag, ensure_ascii=False) + "\n")
                    fout.flush()
                    completed += 1
                    t = tag["type"]
                    type_counts[t] = type_counts.get(t, 0) + 1
                    status = "跳过" if tag["skip"] else f"{t}/{tag.get('importance','')}"
                    print(f"  [{completed}/{len(todo)}] {fname[:40]:40s} {status}")

    # 统计
    print("\n── 分类统计 ──────────────────────────")
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:12s}: {cnt}")
    print(f"\n标记文件：{TAGS_FILE}")


if __name__ == "__main__":
    main()

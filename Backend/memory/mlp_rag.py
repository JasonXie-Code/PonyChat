# -*- coding: utf-8 -*-
"""
MLP 知识库混合检索模块（Vector + FTS5 Hybrid RAG）

检索策略（两路并行，结果合并）：
  1. 向量检索  —— 语义相似度（cosine），适合自然语言长句
  2. FTS5 关键词检索 —— 精确字符匹配，适合角色名/别名/短词
     - cn_name 精确匹配：直接命中角色/地点名称，得分最高
     - 全文匹配：文档中含有查询词，次级

使用方式：
    from backend.memory.mlp_rag import search_mlp_knowledge
    results = await search_mlp_knowledge("暮光闪闪的魔法能力", top_k=5)
    # 返回 List[dict]: [{filename, cn_name, doc_type, importance, content, score, match_type}]

同步调用：
    from backend.memory.mlp_rag import search_mlp_knowledge_sync
    results = search_mlp_knowledge_sync("碧琪", top_k=5)

首次调用时从 SQLite 加载向量到内存（约 5 MB），后续纯内存检索。

主聊天默认不调用本模块：``chat_modules.request_context.MLP_RAG_INJECT_ENABLED`` 为 False
时不注入 ``build_mlp_rag_system_block``；本文件及 ``PONYCHAT_MLP_RAG`` 仍保留供脚本与日后恢复。
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import Optional

import json

import numpy as np
import requests

from ..runtime_paths import resolve_mlp_vector_db_path

# ── 路径配置（与 misc/project_paths.mlp_data_dir 一致）──────────────────────────
import sys

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ROOT = _BACKEND_DIR.parent
_MISC = _ROOT / "misc"
if str(_MISC) not in sys.path:
    sys.path.insert(0, str(_MISC))
from project_paths import mlp_data_dir

_MLP_BASE = mlp_data_dir(_ROOT)
DB_PATH = Path(resolve_mlp_vector_db_path(str(_BACKEND_DIR)))

# ── 别名表（aliases.json）─────────────────────────────────────────────────────
_ALIASES: dict[str, str] = {}
_ALIASES_FILE = _MLP_BASE / "aliases.json"

def _load_aliases() -> dict[str, str]:
    global _ALIASES
    if _ALIASES:
        return _ALIASES
    try:
        data = json.loads(_ALIASES_FILE.read_text(encoding="utf-8"))
        _ALIASES = {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        pass
    return _ALIASES

def _expand_query(query: str) -> list[str]:
    """
    把查询词扩展为 [原始词, 别名对应的标准名]（去重）。
    例如："彩虹" → ["彩虹", "云宝黛茜"]
    例如："云宝是谁" → ["云宝是谁", "云宝黛茜"]（子串 "云宝" 命中）
    """
    aliases = _load_aliases()
    expanded = [query]
    # 先尝试完全匹配
    canonical = aliases.get(query)
    if canonical and canonical not in expanded:
        expanded.append(canonical)
    # 再做子串扫描：query 里包含某个 alias key 则也扩展
    # 按 key 长度降序，优先匹配更长的别名（避免"彩"先于"彩虹"命中）
    for key in sorted(aliases.keys(), key=len, reverse=True):
        if key.startswith("──"):  # 跳过注释行
            continue
        if key in query and key != query:
            val = aliases[key]
            if val and val not in expanded:
                expanded.append(val)
    return expanded

# ── DashScope Embedding（query 向量化）────────────────────────────────────────
_DASHSCOPE_KEY = os.environ.get("PONYCHAT_DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
_EMBED_URL   = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
_EMBED_MODEL = "text-embedding-v3"
_EMBED_DIM   = 1024

# ── 向量索引缓存（全局一次性加载）─────────────────────────────────────────────
_index: Optional[dict] = None   # {"matrix": np.ndarray, "rows": list[dict], "fname_to_idx": dict}


def _blob_to_vec(b: bytes) -> np.ndarray:
    n = len(b) // 4
    return np.array(struct.unpack(f"{n}f", b), dtype=np.float32)


def _load_index() -> dict:
    """从 SQLite 读取所有向量，构建内存索引（只加载一次）。"""
    global _index
    if _index is not None:
        return _index

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"MLP 向量库不存在：{DB_PATH}\n"
            "请先运行 data/mlp/build_vector_db.py 生成向量库。"
        )

    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    rows_raw = conn.execute(
        "SELECT filename, cn_name, doc_type, importance, content, embedding"
        " FROM mlp_knowledge ORDER BY id"
    ).fetchall()
    conn.close()

    rows = []
    vecs = []
    fname_to_idx: dict[str, int] = {}
    for i, (fname, cn_name, doc_type, importance, content, blob) in enumerate(rows_raw):
        v = _blob_to_vec(blob)
        norm = np.linalg.norm(v)
        vecs.append(v / norm if norm > 0 else v)
        rows.append({
            "filename":   fname,
            "cn_name":    cn_name or fname,
            "doc_type":   doc_type or "",
            "importance": importance or "",
            "content":    content or "",
        })
        fname_to_idx[fname] = i

    matrix = np.stack(vecs, axis=0).astype(np.float32)
    _index = {"matrix": matrix, "rows": rows, "fname_to_idx": fname_to_idx}

    elapsed = time.time() - t0
    try:
        from ..config import logger
        logger.info(f"📚 [MLP-RAG] 向量库已加载：{len(rows)} 条，耗时 {elapsed:.2f}s")
    except Exception:
        print(f"📚 [MLP-RAG] 向量库已加载：{len(rows)} 条，耗时 {elapsed:.2f}s")

    return _index


def _embed_query(query: str) -> np.ndarray:
    """把查询文本向量化（调用 DashScope API）。"""
    headers = {
        "Authorization": f"Bearer {_DASHSCOPE_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model":           _EMBED_MODEL,
        "input":           [query],
        "dimensions":      _EMBED_DIM,
        "encoding_format": "float",
    }
    for attempt in range(3):
        try:
            r = requests.post(_EMBED_URL, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                vec = np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
                norm = np.linalg.norm(vec)
                return vec / norm if norm > 0 else vec
        except Exception:
            pass
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError("MLP-RAG：query embedding 失败（3 次重试均超时）")


def _vector_search(query_vec: np.ndarray, matrix: np.ndarray, rows: list,
                   top_k: int, type_mask: Optional[list[int]]) -> list[tuple[int, float]]:
    """向量检索，返回 (行索引, score) 列表（已按 score 降序排列）。"""
    if type_mask is not None:
        sub_matrix = matrix[type_mask]
        scores_sub = sub_matrix @ query_vec
        if top_k >= len(scores_sub):
            order = np.argsort(scores_sub)[::-1]
        else:
            order = np.argpartition(scores_sub, -top_k)[-top_k:]
            order = order[np.argsort(scores_sub[order])[::-1]]
        return [(type_mask[i], float(scores_sub[i])) for i in order]
    else:
        scores = matrix @ query_vec
        if top_k >= len(scores):
            order = np.argsort(scores)[::-1]
        else:
            order = np.argpartition(scores, -top_k)[-top_k:]
            order = order[np.argsort(scores[order])[::-1]]
        return [(int(i), float(scores[i])) for i in order]


def _keyword_search(query: str, top_k: int, doc_type_filter: Optional[str]) -> list[tuple[str, float, str]]:
    """
    关键词检索，返回 (filename, score, match_type)。
    两路策略：
      1. cn_name LIKE 匹配（直接对 mlp_knowledge 表，不受 FTS BM25 排名影响）
         → score = 1.0，match_type = "name_exact"
      2. FTS5 全文搜索（mlp_fts 表）
         → score = 0.7，match_type = "fulltext"
    """
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    results: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    limit = top_k * 3

    try:
        # ── 1. cn_name 直接 LIKE 匹配（mlp_knowledge 表）──────────────────
        type_clause = " AND doc_type = ?" if doc_type_filter else ""
        type_params = [doc_type_filter] if doc_type_filter else []

        rows = conn.execute(
            f"SELECT filename FROM mlp_knowledge"
            f" WHERE cn_name LIKE ?{type_clause} LIMIT ?",
            [f"%{query}%"] + type_params + [limit],
        ).fetchall()
        for (fname,) in rows:
            if fname and fname not in seen:
                results.append((fname, 1.0, "name_exact"))
                seen.add(fname)

        # ── 2. FTS5 全文检索（匹配内容中出现查询词的文档）───────────────────
        # unicode61 对中文以字符为单位分词，短语用 "" 包裹确保连续匹配
        safe_q = query.replace('"', '""')
        fts_expr = f'"{safe_q}"'
        fts_type_clause = " AND doc_type = ?" if doc_type_filter else ""
        rows = conn.execute(
            f"SELECT f.filename FROM mlp_fts f"
            f" JOIN mlp_knowledge k ON f.filename = k.filename"
            f" WHERE mlp_fts MATCH ?{fts_type_clause}"
            f" ORDER BY rank LIMIT ?",
            [fts_expr] + type_params + [limit],
        ).fetchall()
        for (fname,) in rows:
            if fname and fname not in seen:
                results.append((fname, 0.7, "fulltext"))
                seen.add(fname)
    except Exception as e:
        try:
            from ..config import logger
            logger.warning(f"⚠️ [MLP-RAG] 关键词检索失败: {e}")
        except Exception:
            pass
    finally:
        conn.close()

    return results[:top_k * 2]


def _looks_like_llm_refusal_placeholder(content: str) -> bool:
    """产品已关闭拒答占位过滤，恒为 False，检索结果全部参与排序与注入。"""
    del content
    return False


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def search_mlp_knowledge_sync(
    query: str,
    top_k: int = 5,
    doc_type_filter: Optional[str] = None,
    min_score: float = 0.3,
) -> list[dict]:
    """
    混合检索（向量 + FTS5），同步版。

    Parameters
    ----------
    query           : 查询文本（自然语言或关键词/别名）
    top_k           : 最终返回条数
    doc_type_filter : 可选类型过滤，如 "character"/"location"/"song"/"episode"
    min_score       : 向量结果最低相似度阈值（FTS 结果不受此限制）

    Returns
    -------
    list of dict: [{filename, cn_name, doc_type, importance, content, score, match_type}]
    """
    idx = _load_index()
    matrix = idx["matrix"]
    rows   = idx["rows"]
    fname_to_idx = idx["fname_to_idx"]

    # 类型过滤掩码
    type_mask = None
    if doc_type_filter:
        type_mask = [i for i, r in enumerate(rows) if r["doc_type"] == doc_type_filter]

    # ── 并行执行两路检索 ────────────────────────────────────────────────────
    # 1. 向量检索（用原始 query，拉取 top_k * 2 候选）
    query_vec = _embed_query(query)
    vec_hits = _vector_search(query_vec, matrix, rows, top_k * 2, type_mask)

    # 2. 关键词检索（原始词 + 别名扩展）
    # 别名扩展命中的标准名匹配优先级最高（score=1.2），避免被原词的部分匹配压过
    expanded = _expand_query(query)
    fts_hits: list[tuple[str, float, str]] = []
    seen_kw: set[str] = set()
    for i, kw in enumerate(expanded):
        is_alias = (i > 0)   # expanded[0] 是原词，之后是 alias 扩展
        for fname, score, mtype in _keyword_search(kw, top_k, doc_type_filter):
            if fname not in seen_kw:
                # alias 扩展的 name_exact 得分提升到 1.2，区分于原词部分匹配
                final_score = (1.2 if (is_alias and mtype == "name_exact") else score)
                fts_hits.append((fname, final_score, mtype if not is_alias else f"alias:{mtype}"))
                seen_kw.add(fname)

    # ── 合并去重，按最终得分排序 ─────────────────────────────────────────────
    # 得分规则：
    #   - FTS name_exact：score = 1.0（名称直接命中，最高优先级）
    #   - FTS 全文  ：score = 0.7 + 向量得分（如果有）* 0.3 加权
    #   - 仅向量   ：score = 向量 cosine 得分
    merged: dict[str, dict] = {}

    # 先放向量结果
    for row_idx, vscore in vec_hits:
        if vscore < min_score:
            continue
        r = rows[row_idx]
        fname = r["filename"]
        entry = dict(r)
        entry["score"] = vscore
        entry["match_type"] = "vector"
        entry["content"] = entry["content"][:3000]
        merged[fname] = entry

    # FTS 结果覆盖/合并（FTS 优先级高于纯向量）
    for fname, fts_score, mtype in fts_hits:
        if fname not in fname_to_idx:
            continue
        row_idx = fname_to_idx[fname]
        r = rows[row_idx]
        # 若向量结果里也有这条，取两者之和作为加权
        if fname in merged:
            vec_bonus = merged[fname]["score"] * 0.2
            final_score = fts_score + vec_bonus
        else:
            final_score = fts_score
        entry = dict(r)
        entry["score"] = final_score
        entry["match_type"] = mtype
        entry["content"] = entry["content"][:3000]
        merged[fname] = entry  # 覆盖，FTS 结果优先

    # 排序 + 截断（跳过误入库的拒答占位条，顺延取满 top_k）
    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    picked: list[dict] = []
    for r in results:
        if _looks_like_llm_refusal_placeholder(r.get("content", "")):
            continue
        picked.append(r)
        if len(picked) >= top_k:
            break
    return picked


async def search_mlp_knowledge(
    query: str,
    top_k: int = 5,
    doc_type_filter: Optional[str] = None,
    min_score: float = 0.3,
) -> list[dict]:
    """异步包装（线程池，不阻塞事件循环）。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: search_mlp_knowledge_sync(query, top_k, doc_type_filter, min_score),
    )


def mlp_rag_enabled() -> bool:
    """环境变量 PONYCHAT_MLP_RAG=0/false/off 可关闭检索（节省 embedding 配额）。"""
    v = os.environ.get("PONYCHAT_MLP_RAG", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


async def build_mlp_rag_system_block(
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.3,
) -> str:
    """
    根据用户本轮输入检索知识库，返回可注入的 system 文本；失败或无结果返回空串。
    由 `assemble_messages` 仅在普通聊天模式调用；游戏/锁分模式不调用。
    """
    if not mlp_rag_enabled():
        return ""
    q = (query or "").strip()
    if len(q) < 2:
        return ""
    if not DB_PATH.exists():
        return ""
    try:
        results = await search_mlp_knowledge(q, top_k=top_k, min_score=min_score)
        return format_rag_context(results)
    except Exception:
        return ""


def format_rag_context(results: list[dict], header: str = "【MLP 世界观参考】") -> str:
    """把检索结果格式化为可直接注入 system prompt 的文本块。"""
    if not results:
        return ""
    parts = [header]
    for r in results:
        content = r.get("content", "").strip()
        if _looks_like_llm_refusal_placeholder(content):
            continue
        name = r.get("cn_name") or r.get("filename", "")
        score = r.get("score", 0)
        mtype = r.get("match_type", "")
        tag = f"相关度 {score:.2f}" + (f", {mtype}" if mtype else "")
        parts.append(f"\n--- {name} ({tag}) ---\n{content}")
    if len(parts) <= 1:
        return ""
    return "\n".join(parts)


def preload():
    """预热：主动加载向量库到内存，供后端 startup 调用。"""
    _load_index()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    query = sys.argv[1] if len(sys.argv) > 1 else "暮光闪闪的魔法能力"
    print(f"查询：{query}\n")
    results = search_mlp_knowledge_sync(query, top_k=5)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['doc_type']}] {r['cn_name']}  "
              f"score={r['score']:.4f}  match={r['match_type']}")
        print(f"   {r['content'][:200].replace(chr(10), ' ')}")
        print()

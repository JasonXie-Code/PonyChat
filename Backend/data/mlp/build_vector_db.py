# -*- coding: utf-8 -*-
"""
把 data/mlp/refined/*.txt 全部向量化，存入 mlp_vectors.db（SQLite）。
使用 DashScope text-embedding-v3（dim=1024）。
支持断点续传：已经向量化的文件自动跳过。

用法：
    python build_vector_db.py
"""
import sys, os, json, sqlite3, time, struct
import numpy as np
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from mlp_paths import DB_PATH

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 路径 & 配置 ─────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
REFINED    = BASE_DIR / "refined_pony"   # 过滤后的纯马界目录
TAGS_FILE  = BASE_DIR / "tags.jsonl"

DASHSCOPE_KEY = os.environ.get("PONYCHAT_DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
if not DASHSCOPE_KEY:
    raise RuntimeError("Set PONYCHAT_DASHSCOPE_API_KEY or DASHSCOPE_API_KEY before building vectors.")
EMBED_URL  = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
EMBED_MODEL = "text-embedding-v3"
EMBED_DIM  = 1024
BATCH_SIZE  = 10     # DashScope text-embedding-v3 最大 batch=10
MAX_CHARS   = 6000   # 每条文本取前 6000 字符（约 4500 token，留余量）
MAX_WORKERS = 4      # 并发批次数（保守，避免 429）
INTER_BATCH_SLEEP = 0.3  # 批次间最小间隔（秒）

# ── 工具函数 ─────────────────────────────────────────────────────────────────
def vec_to_blob(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)

def blob_to_vec(b: bytes) -> np.ndarray:
    n = len(b) // 4
    return np.array(struct.unpack(f"{n}f", b), dtype=np.float32)

# ── 加载 tags.jsonl → {filename: {cn_name, type, importance}} ────────────────
def load_tags() -> dict:
    tag_map = {}
    if not TAGS_FILE.exists():
        return tag_map
    with open(TAGS_FILE, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                fname = d.get("file", "")
                if fname:
                    tag_map[fname] = d
            except Exception:
                pass
    return tag_map

# ── 初始化 / 升级 SQLite 表 ──────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlp_knowledge (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            filename  TEXT UNIQUE NOT NULL,
            cn_name   TEXT,
            doc_type  TEXT,
            importance TEXT,
            content   TEXT,
            embedding BLOB NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_type ON mlp_knowledge(doc_type)")
    conn.commit()

# ── Embedding API（单批，带重试）────────────────────────────────────────────
def embed_batch(texts: list[str]) -> list[list[float]] | None:
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBED_MODEL,
        "input": texts,
        "dimensions": EMBED_DIM,
        "encoding_format": "float",
    }
    for attempt in range(5):
        try:
            r = requests.post(EMBED_URL, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()["data"]
                return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
            elif r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  ⚠ 429 限速，等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                print(f"  ⚠ embed API {r.status_code}: {r.text[:150]}")
                time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  ⚠ embed 异常 attempt={attempt}: {e}")
            time.sleep(2 * (attempt + 1))
    return None

# ── 主流程 ───────────────────────────────────────────────────────────────────
def main():
    tag_map = load_tags()
    all_files = sorted(REFINED.glob("*.txt"))
    print(f"refined/ 共 {len(all_files)} 个文件")

    # 读取已完成的文件名（断点续传）
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    done = {row[0] for row in conn.execute("SELECT filename FROM mlp_knowledge")}
    print(f"数据库已有 {len(done)} 条，跳过")

    # 待处理
    pending = [f for f in all_files if f.name not in done]
    print(f"待向量化 {len(pending)} 个文件\n")
    if not pending:
        print("全部完成，无需重跑。")
        conn.close()
        return

    # 读文件内容
    rows = []  # (filename, cn_name, doc_type, importance, content)
    for fp in pending:
        text = fp.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
        meta = tag_map.get(fp.name, {})
        rows.append((
            fp.name,
            meta.get("cn_name", fp.stem),
            meta.get("type", ""),
            meta.get("importance", ""),
            text,
        ))

    # 分批
    batches = [rows[i:i+BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    print(f"共 {len(batches)} 批（每批最多 {BATCH_SIZE} 条），并发 {MAX_WORKERS} 路\n")

    total_ok = 0
    total_fail = 0
    start = time.time()

    def process_batch(batch_idx: int, batch: list) -> tuple[list, int]:
        time.sleep(batch_idx * 0.05)   # 错开启动时间，避免瞬时并发峰值
        texts = [r[4] for r in batch]
        vecs = embed_batch(texts)
        if vecs is None or len(vecs) != len(batch):
            return [], len(batch)
        insert_data = []
        for row, vec in zip(batch, vecs):
            blob = vec_to_blob(vec)
            insert_data.append((row[0], row[1], row[2], row[3], row[4], blob))
        time.sleep(INTER_BATCH_SLEEP)
        return insert_data, 0

    # 并发执行
    futures = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, batch in enumerate(batches):
            f = ex.submit(process_batch, i, batch)
            futures[f] = i

        for done_f in as_completed(futures):
            idx = futures[done_f]
            result, fail_count = done_f.result()
            if fail_count:
                total_fail += fail_count
                print(f"  ✗ 批次 {idx} 失败 {fail_count} 条")
            else:
                # 写入数据库
                conn.executemany(
                    "INSERT OR REPLACE INTO mlp_knowledge"
                    " (filename, cn_name, doc_type, importance, content, embedding)"
                    " VALUES (?,?,?,?,?,?)",
                    result
                )
                conn.commit()
                total_ok += len(result)
                elapsed = time.time() - start
                speed = total_ok / elapsed if elapsed > 0 else 0
                print(f"  ✔ 批次 {idx:3d} 完成 | 累计 {total_ok:4d}/{len(rows)} | "
                      f"{speed:.1f} doc/s | {elapsed:.0f}s 已用")

    conn.close()
    elapsed = time.time() - start
    print(f"\n完成！成功 {total_ok}，失败 {total_fail}，耗时 {elapsed:.1f}s")
    print(f"数据库位置：{DB_PATH}")

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""单线程顺序测试：直接打印 API 调用的原始响应和错误，诊断超时根因"""
import sys, json, time, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from backend.model_manager import load_merged_model_config

cfg = load_merged_model_config()
models = cfg.get("models", [])
for m in models:
    if m.get("id") == "deepseek-flash":
        ENDPOINT = m["endpoint"]
        API_KEY  = m["api_key"]
        MODEL    = m["model_name"]
        break

HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
CLEAN_DIR = Path(__file__).parent / "clean"

test_files = [
    "暮光闪闪.txt",
    "云中城.txt",
    "不泯童心.txt",
    "8 bit.txt",
    "Ace Point.txt",
    "天马.txt",
    "可爱标记_获得途径.txt",
    "苹果杰克.txt",
    "忘形之交.txt",
    "A True, True Friend.txt",
]

for fname in test_files:
    path = CLEAN_DIR / fname
    if not path.exists():
        print(f"[不存在] {fname}")
        continue

    text = path.read_text(encoding="utf-8")[:1500]
    payload = {
        "model": MODEL,
        "thinking": {"type": "enabled"},
        "messages": [
            {"role": "system", "content": "你是 MLP 世界设定编辑。将下面的维基页面改写为约500字的角色/地点/概念设定卡，用 Markdown 格式输出，不要解释。"},
            {"role": "user",   "content": f"文件名：{fname}\n\n{text}"},
        ],
        "reasoning_effort": "low",
        "max_tokens": 8192,
        "temperature": 0.4,
    }

    print(f"\n[{fname}] 发送请求...", flush=True)
    t0 = time.time()
    try:
        resp = requests.post(
            f"{ENDPOINT}/chat/completions",
            headers=HEADERS,
            json=payload,
            timeout=45,
        )
        elapsed = time.time() - t0
        print(f"  HTTP {resp.status_code}  耗时 {elapsed:.1f}s")

        if resp.status_code != 200:
            print(f"  错误响应体: {resp.text[:300]}")
            continue

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        print(f"  输出长度: {len(content)} 字符")
        # 打印前5行
        for line in content.splitlines()[:5]:
            print(f"    {line}")

    except requests.exceptions.Timeout:
        print(f"  超时！({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"  异常: {type(e).__name__}: {e}")

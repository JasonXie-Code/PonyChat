# -*- coding: utf-8 -*-
"""单次 API 调用计时测试"""
import sys, json, time, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from backend.model_manager import load_merged_model_config

cfg = load_merged_model_config()
for m in cfg.get("models", []):
    if m.get("id") == "deepseek-flash":
        ENDPOINT, API_KEY, MODEL = m["endpoint"], m["api_key"], m["model_name"]
        break

print(f"模型: {MODEL}")
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}

text = (Path(__file__).parent / "clean" / "Ace Point.txt").read_text(encoding="utf-8")[:800]

# 统一模型 low 思考冒烟
for effort, max_tok in [("low", 8192)]:
    payload = {
        "model": MODEL,
        "thinking": {"type": "enabled"},
        "messages": [
            {"role": "system", "content": "你是 MLP 世界设定编辑。将下面的维基页面改写为约300字的角色设定卡，用 Markdown，不要解释。"},
            {"role": "user", "content": text},
        ],
        "reasoning_effort": "low",
        "max_tokens": max_tok,
        "temperature": 0.4,
    }
    print(f"\n--- reasoning_effort={effort!r}  max_tokens={max_tok} ---")
    t0 = time.time()
    try:
        resp = requests.post(f"{ENDPOINT}/chat/completions", headers=HEADERS, json=payload, timeout=120)
        elapsed = time.time() - t0
        data = resp.json()
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            continue
        output = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  tokens: input={usage.get('prompt_tokens')} output={usage.get('completion_tokens')} thinking={usage.get('reasoning_tokens','?')}")
        print(f"  输出({len(output)}字): {output[:80]}...")
    except Exception as e:
        print(f"  异常({time.time()-t0:.1f}s): {e}")

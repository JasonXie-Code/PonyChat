#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单脚本：测试 xAI 官方两个 Grok 模型 API 是否可用。
从 config/model_config.json 读取 endpoint 和 api_key，请求 /v1/chat/completions。
"""
import json
import sys
from pathlib import Path

# 项目根目录（本文件在 misc/tools/）
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "backend" / "conf" / "model_config.json"

def load_xai_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for m in data.get("models", []):
        if "api.x.ai" in (m.get("endpoint") or ""):
            return {
                "endpoint": m["endpoint"].rstrip("/"),
                "api_key": m.get("api_key", ""),
            }
    return None

def test_model(base_url: str, api_key: str, model_name: str, timeout: int = 60) -> tuple[bool, str]:
    import httpx

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "Say exactly: OK"}],
        "max_completion_tokens": 20,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message", resp.text)
            except Exception:
                msg = resp.text
            return False, f"HTTP {resp.status_code}: {msg}"
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return True, (content or "(空回复)")
    except Exception as e:
        return False, str(e)

def main():
    print("读取 config/model_config.json 中的 xAI 配置...")
    cfg = load_xai_config()
    if not cfg or not cfg.get("api_key"):
        print("未找到 xAI 配置或 api_key 为空，请检查 config/model_config.json")
        sys.exit(1)
    base_url = cfg["endpoint"]
    api_key = cfg["api_key"]
    print(f"Endpoint: {base_url}")
    print()

    models = [
        ("grok-4-1-fast-reasoning", 45),
        ("grok-4-1-fast-non-reasoning", 25),
    ]
    all_ok = True
    for model_name, timeout in models:
        print(f"测试模型: {model_name} (超时 {timeout}s) ... ", end="", flush=True)
        ok, msg = test_model(base_url, api_key, model_name, timeout=timeout)
        if ok:
            print("[OK] 成功")
            print(f"  回复: {msg[:80]}{'...' if len(msg) > 80 else ''}")
        else:
            print("[FAIL] 失败")
            print(f"  原因: {msg}")
            all_ok = False
        print()
    print("全部通过" if all_ok else "存在失败")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()

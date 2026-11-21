#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_api.py - 验证 llama.cpp server API 是否正常

用法（启动服务后执行）：
  ..\tools\python\python.exe scripts\test_api.py
  或
  python scripts\test_api.py

说明：Qwen3.5 是思维链（CoT）模型，内部会生成 <think> 推理过程，
      completion token 较多（通常 500~2000），max_tokens 需要足够大。
"""

import json
import sys
import urllib.request
import urllib.error

# Windows 终端默认 GBK，强制 UTF-8 输出避免中文/代码乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL  = "http://127.0.0.1:8068"
MAX_TOKENS = 2048   # 思维链模型需要足够空间生成推理过程


def check_health():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=5) as r:
            body = json.loads(r.read())
            status = body.get("status", "unknown")
            print(f"[health] {status}")
            return status == "ok"
    except urllib.error.URLError as e:
        print(f"[health] 连接失败：{e.reason}  — 请先启动服务 (scripts\\start_server.ps1)")
        return False


def chat(prompt: str, max_tokens: int = MAX_TOKENS) -> dict:
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main():
    print("=== LocalLLM API 测试 ===\n")

    if not check_health():
        sys.exit(1)

    test_cases = [
        "你好，用一句话介绍你自己。",
        "1 + 1 等于几？直接给答案，不要解释。",
        "用 Python 写一个冒泡排序函数。",
    ]

    for prompt in test_cases:
        print(f"\n[Q] {prompt}")
        try:
            resp  = chat(prompt)
            reply = resp["choices"][0]["message"]["content"]
            usage = resp.get("usage", {})
            finish = resp["choices"][0].get("finish_reason", "?")
            print(f"[A] {reply}")
            print(f"    tokens: prompt={usage.get('prompt_tokens','?')}  "
                  f"completion={usage.get('completion_tokens','?')}  "
                  f"finish={finish}")
        except Exception as e:
            print(f"[错误] {e}")

    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    main()

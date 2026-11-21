# -*- coding: utf-8 -*-
"""
碧琪黏连句子归因测试：直接从真实日志 SEQ_STEP_6_RESPONSE 里摘取完整 messages，
然后逐级剥离上下文段落，对同一玩家输入重复采样，比较黏连指标。

判定：
- max_run：引号内相邻标点之间最长汉字串长度，>12 视为密度不足
- max_aa_chain：引号内连续 AA 叠字状态词的最大链长，≥3 视为叠字堆叠
"""
import json
import os
import re
import sys
import time
import urllib.request

API_KEY = os.getenv("PONYCHAT_XAI_API_KEY", "")
ENDPOINT = "https://api.x.ai/v1/chat/completions"
MODEL = "grok-4-1-fast-non-reasoning"

LOG_PATH = r"p:\PonyChat\var\ChatMonitor\.chatlogs\2026-04-21\01\20260421_010517_000_galgame_lock_SEQ_STEP_6_RESPONSE_1771049155505_a5bxes.js"


def load_messages_from_log(path: str):
    """从 debug_log JS 文件中解析出真实 messages 数组。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # 先把 \` 转义占位，避免误判反引号边界
    sentinel = "\x00BACKTICK\x00"
    raw_safe = raw.replace("\\`", sentinel)
    # 匹配所有 "content": `...`
    pat = re.compile(r'"content"\s*:\s*`(.*?)`', re.DOTALL)
    contents = [m.group(1).replace(sentinel, "`") for m in pat.finditer(raw_safe)]
    # role 推断：日志中三段 system + 一段 user
    # user content 是普通双引号字符串，不用反引号，我们从正文里另外提取
    u_pat = re.compile(r'"role"\s*:\s*"user"\s*,\s*"content"\s*:\s*"([^"]*)"')
    m = u_pat.search(raw)
    user_content = m.group(1) if m else ""
    messages = [{"role": "system", "content": c} for c in contents]
    messages.append({"role": "user", "content": user_content})
    return messages


def split_third_system(text: str) -> dict:
    """将第三段 system（指令+历史+锁分+前序+导演决策）拆为若干标签段落。"""
    # 按「【XXX】」段头切分，保留每段的起始标签
    # 特殊段落标识
    markers = {
        "prestep": "以下内容已由系统在前序步骤生成",
        "instruction_headers": "## ⚠️ 最高优先级禁令",
        "history": "【对话历史",
        "status": "【角色与玩家当前状态】",
        "body_hint": "【锁分·身体体征提示】",
        "mood_hint": "【锁分·心理状态提示】",
        "behavior_hint": "【锁分·情绪行为指引】",
        "need_hint": "【锁分·主动需求提示】",
        "driver_hint": "【锁分·体征驱动提示】",
        "phrase_dedup": "【短语重复提示】",
        "opening_dedup": "【近期开篇禁止",
        "player_info": "【玩家信息】",
        "player_action": "【玩家本轮行为】",
        "director": "【本轮导演决策】",
    }
    idx = {}
    for k, mk in markers.items():
        i = text.find(mk)
        if i >= 0:
            idx[k] = i
    # 按起始位置排序，切出每段
    sorted_items = sorted(idx.items(), key=lambda kv: kv[1])
    segments = {}
    header = text[: sorted_items[0][1]] if sorted_items else text
    segments["_header"] = header
    for i, (k, start) in enumerate(sorted_items):
        end = sorted_items[i + 1][1] if i + 1 < len(sorted_items) else len(text)
        segments[k] = text[start:end]
    return segments


def assemble_third_system(segments: dict, keep_keys: list[str]) -> str:
    out = [segments.get("_header", "")]
    for k in keep_keys:
        if k in segments:
            out.append(segments[k])
    return "".join(out)


def build_levels(messages):
    """构造 5 级剥离后的 messages。"""
    sys1 = messages[0]["content"]  # 角色设定
    sys2 = messages[1]["content"]  # 对话背景
    sys3 = messages[2]["content"]  # 任务+历史+锁分+前序+导演
    user = messages[-1]["content"]

    segs = split_third_system(sys3)

    # L0：完整（等价于原日志）
    full_keys = [
        "instruction_headers", "phrase_dedup", "opening_dedup",
        "player_info", "history", "status",
        "body_hint", "mood_hint", "behavior_hint", "need_hint", "driver_hint",
        "player_action", "director",
    ]

    # L1：去掉【对话历史】
    l1_keys = [k for k in full_keys if k != "history"]

    # L2：L1 基础上再去掉全部锁分提示
    lock_keys = {"body_hint", "mood_hint", "behavior_hint", "need_hint", "driver_hint"}
    l2_keys = [k for k in l1_keys if k not in lock_keys]

    # L3：L2 基础上把前序步骤 env/body_state/thoughts 也拿掉
    #     前序段落在 segs["_header"] 里，以「--- 环境描写（已完成）---」开头、
    #     到「请只输出本回合角色对玩家的回复纯文本」之前结束
    l3_header = segs["_header"]
    cut_start = l3_header.find("--- 环境描写（已完成）---")
    cut_end = l3_header.find("请只输出本回合角色对玩家的回复纯文本")
    if cut_start >= 0 and cut_end > cut_start:
        l3_header = l3_header[:cut_start] + l3_header[cut_end:]
    l3_segs = dict(segs)
    l3_segs["_header"] = l3_header

    def pack(header_segs, keys):
        return assemble_third_system(header_segs, keys)

    # L4：最简——只保留角色设定 + 玩家本轮行为 + 极简生成指令
    minimal_instruction = (
        "\n\n请以碧琪身份对上一条玩家发言做出一次回复。"
        "\n- 回复须包含一段台词（用中文双引号），允许少量动作描写。"
        "\n- 字数不超过 100 字。"
    )

    levels = [
        ("L0_原始完整", [
            {"role": "system", "content": sys1},
            {"role": "system", "content": sys2},
            {"role": "system", "content": pack(segs, full_keys)},
            {"role": "user", "content": user},
        ]),
        ("L1_去对话历史", [
            {"role": "system", "content": sys1},
            {"role": "system", "content": sys2},
            {"role": "system", "content": pack(segs, l1_keys)},
            {"role": "user", "content": user},
        ]),
        ("L2_再去锁分提示", [
            {"role": "system", "content": sys1},
            {"role": "system", "content": sys2},
            {"role": "system", "content": pack(segs, l2_keys)},
            {"role": "user", "content": user},
        ]),
        ("L3_再去前序步骤", [
            {"role": "system", "content": sys1},
            {"role": "system", "content": sys2},
            {"role": "system", "content": pack(l3_segs, l2_keys)},
            {"role": "user", "content": user},
        ]),
        ("L4_最简_仅角色+玩家行为", [
            {"role": "system", "content": sys1 + minimal_instruction},
            {"role": "user", "content": user},
        ]),
    ]
    return levels


CJK = re.compile(r"[\u4e00-\u9fff]")
PUNCTS = set("，。！？；：、,.!?;:…—\n")


def analyze(text: str) -> dict:
    quoted = re.findall(r"[“\"]([^”\"]*)[”\"]", text)
    merged = "".join(quoted) if quoted else text

    max_run = 0
    cur = 0
    for ch in merged:
        if ch in PUNCTS:
            if cur > max_run:
                max_run = cur
            cur = 0
        elif CJK.match(ch):
            cur += 1
    max_run = max(max_run, cur)

    max_aa_chain = 0
    i = 0
    run = 0
    while i < len(merged) - 1:
        if merged[i] == merged[i + 1] and CJK.match(merged[i]):
            run += 1
            max_aa_chain = max(max_aa_chain, run)
            i += 2
        else:
            run = 0
            i += 1

    return {
        "len": len(text),
        "quoted_len": len(merged),
        "max_run": max_run,
        "max_aa_chain": max_aa_chain,
    }


def call_api(messages, temperature=1.0):
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 512,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def main():
    messages = load_messages_from_log(LOG_PATH)
    assert len(messages) >= 3, "日志解析失败"
    levels = build_levels(messages)

    # 通过命令行参数可指定只跑某些层级，如 python test.py 0 3
    if len(sys.argv) > 1:
        idxs = [int(x) for x in sys.argv[1:]]
        levels = [levels[i] for i in idxs]

    out_path = os.path.join(os.path.dirname(__file__), "pinkie_stickiness_result.md")
    fout = open(out_path, "w", encoding="utf-8")

    def log(s=""):
        print(s.encode("gbk", errors="replace").decode("gbk", errors="replace"))
        fout.write(s + "\n")
        fout.flush()

    runs_per_level = 3
    summary_rows = []
    for name, msgs in levels:
        total_chars = sum(len(m["content"]) for m in msgs)
        log(f"\n{'='*70}")
        log(f"{name} — messages 共 {total_chars} 字，{len(msgs)} 条")
        log(f"{'='*70}")
        runs = []
        for i in range(runs_per_level):
            try:
                text = call_api(msgs)
            except Exception as e:
                log(f"  run{i+1}: API 错误 {e}")
                continue
            m = analyze(text)
            tag = ""
            if m["max_run"] > 12:
                tag += "[密度不足]"
            if m["max_aa_chain"] >= 3:
                tag += "[叠字链]"
            if not tag:
                tag = "[OK]"
            log(f"  run{i+1} {tag} max_run={m['max_run']} aa_chain={m['max_aa_chain']} len={m['len']}")
            log(f"     {text}")
            runs.append(m)
            time.sleep(0.5)
        if runs:
            avg_run = sum(r["max_run"] for r in runs) / len(runs)
            avg_aa = sum(r["max_aa_chain"] for r in runs) / len(runs)
            bad = sum(1 for r in runs if r["max_run"] > 12 or r["max_aa_chain"] >= 3)
            summary_rows.append((name, total_chars, avg_run, avg_aa, bad, len(runs)))

    log("\n" + "=" * 70)
    log("汇总（max_run>12 或 aa_chain>=3 记为黏连）")
    log("=" * 70)
    log(f"{'级别':<28}{'字数':>8}  {'avg_max_run':>12}  {'avg_aa':>8}  {'黏连率':>8}")
    for name, chars, avg_run, avg_aa, bad, total in summary_rows:
        log(f"{name:<28}{chars:>8}  {avg_run:>12.1f}  {avg_aa:>8.1f}  {bad}/{total}")

    fout.close()
    print(f"\n完整结果已保存到 {out_path}")


if __name__ == "__main__":
    main()

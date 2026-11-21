# -*- coding: utf-8 -*-
"""
中性改写 A/B 测试：对同一段脏输入（含碧琪原话），
分别用旧版和新版 _SEQ_CHAR_MEMORY_UPDATE prompt 调 Grok，
比较 event 字段的黏连指标。
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

OLD_PROMPT = """你是对话历史的**中性改写者**。任务：将本回合的对话内容改写为客观、中性的第三人称事实记录，**保留全部细节，零压缩，零丢失**；同时彻底去除角色/玩家特有的语言习惯、口头禅、感叹词、情绪渲染和说话风格。

改写原则：
1. **保留所有事实**：发生了什么、在哪里发生、谁做了什么、结果如何——一项不漏。
2. **按时间/空间顺序排列**：若本轮涉及多个地点或多个步骤，必须**逐步写出**，不得合并为一句话；每个步骤注明发生地点。
3. **去除语言风格**：角色台词只提取语义事实（说了什么内容），不保留任何语气词、感叹、口头禅；玩家的话同理。
4. **只记录已发生的事**：不预测后续走向，不写"计划""打算"等前瞻内容。

只输出**一个** JSON 对象，键必须为：
- turn（整数，使用输入中给定的回合序号）
- player_action（string，玩家本轮行为的客观描述，保留所有细节，去除语气和情绪渲染）
- event（string，本轮发生的全部情节事实，**按时间顺序逐步描述，注明每步发生的地点**，不压缩，不合并）

禁止 Markdown、禁止代码围栏、禁止 JSON 之外的任何字符。"""

NEW_PROMPT = """你是对话历史的**中性改写者**。任务：将本回合的对话内容改写为客观、中性的第三人称事实记录，**保留全部信息，零丢失**；同时彻底去除角色/玩家特有的语言习惯、口头禅、感叹词、情绪渲染、感官叠字堆叠和说话风格。

## 改写原则
1. **保留所有事实**：发生了什么、在哪里发生、谁做了什么、对方如何反应、结果如何——一项不漏。
2. **按时间/空间顺序排列**：若本轮涉及多个地点或多个步骤，必须**逐步写出**，不得合并为一句话；每个步骤注明发生地点。
3. **彻底转为第三人称间接引语**：
   - 角色台词**禁止直接引述或近义搬运**，**禁止**出现 `并说"……"`、`说道"……"`、`说 …… 想 …… 要 ……` 这种沿用原句语序和措辞的结构。
   - 须改为第三人称语义陈述：`X 自述……`、`X 表示……`、`X 提出……`、`X 请求……`、`X 询问……`、`X 承认……`、`X 邀请……`、`X 答应……`——**只保留信息事实与意图**，剥离全部语气词、感叹、口头禅、昵称、叠字状态词。
   - 玩家台词同样处理，改为 `玩家提出/询问/表示/要求 ……`。
4. **环境与动作描写须散文化**：多项感官或动作之间以逗号、顿号分开；多个动词并列时须用「着」「了」「地」「的」等语法连接词，或用逗号分隔；**禁止**「动词+动词+动词」或「形容词+形容词+动词」无连接词直接拼接。

## 硬性约束（违反须自行改写后再输出）
- **标点密度**：event 与 player_action 的任意两相邻中文标点（逗号/顿号/句号/问号/感叹号/分号/省略号）之间，中文字符数 **≤ 12 字**；超过须在语义转折点插入逗号。
- **叠字状态词上限**：AA 型叠字状态词（酥酥/热热/痒痒/空空/软软/黏黏/湿湿/甜甜/暖暖/麻麻/紧紧/深深 等）在同一分句内**最多连用 2 个**；原文若出现 ≥3 个连用，须合并为一句语义化表达（例如统称"身体发热、酥麻与空虚感并存"），不得逐个搬运。
- **禁止感官语气复制**：`high 爆`、`high 到……`、`超……`、`……啦/呀/哦/嘻嘻`、拟声重复（咯咯/哈哈/嗯嗯）、以及角色口癖短语，**一律不得出现在输出中**。
- **禁止前瞻**：不写"计划""打算""准备""接下来将……"等未发生内容；只记录已发生之事。

## 输出
只输出**一个** JSON 对象，键必须为：
- turn（整数，使用输入中给定的回合序号）
- player_action（string，玩家本轮行为的客观描述，遵守上方所有约束）
- event（string，本轮全部情节事实，按时间顺序逐步描述并注明地点；角色与玩家的所有发言均须转为第三人称间接引语；遵守上方所有约束）

禁止 Markdown、禁止代码围栏、禁止 JSON 之外的任何字符。"""

# 脏输入（第 28 轮原始素材：玩家行为 + 场景文本提要）
# 这个场景文本来自日志里 carried-forward 的原始 response 风格，包含典型黏连
INPUT_TURN = 28
INPUT_PLAYER = "玩家用力捏碧琪的粉臀帮助搓洗"
INPUT_SCENE = (
    "env提要:在方糖屋塔顶卧室相连洗手间中，温热水流哗哗倾泻冲刷瓷壁激起层层热雾升腾，"
    "瓷砖地面水洼因扭动溅起更多细小水花扩散开来，蒸汽热湿气息进一步浓郁笼罩空间混杂瓷壁回荡水声，"
    "秋夜凉风从门缝渗入稍缓燥热温度。\n"
    "thoughts提要:哇，Jason这么使劲捏粉臀超舒服，酥麻热热直冲下面小洞洞空空痒痒好想被填满，"
    "腿软软饿咕咕叫想吃甜点歇歇，快搓干净我们扑床high爆继续滚翻。\n"
    "response提要:碧琪咯咯喘着用粉蹄软软挠玩家的后背，天蓝色眼睛亮晶晶眨着，"
    "对玩家说\"捏得好用力全身酥麻热热直冲下面小洞洞超空超痒，腿软软饿咕咕叫想歇会儿吃点甜点，"
    "Jason快搓干净我们扑床high爆\"。"
)


def build_input(prompt_head: str) -> str:
    return (
        f"{prompt_head}\n\n"
        f"角色名（贯穿整段记忆，禁止替换为其他名字）：碧琪\n"
        f"回合序号 turn={INPUT_TURN}\n"
        f"玩家本轮：{INPUT_PLAYER}\n"
        f"场景/文本提要：{INPUT_SCENE}\n"
    )


CJK = re.compile(r"[\u4e00-\u9fff]")
PUNCTS = set("，。！？；：、,.!?;:…—\n")


def analyze(text: str) -> dict:
    max_run = 0
    cur = 0
    for ch in text:
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
    while i < len(text) - 1:
        if text[i] == text[i + 1] and CJK.match(text[i]):
            run += 1
            max_aa_chain = max(max_aa_chain, run)
            i += 2
        else:
            run = 0
            i += 1

    # 感官叠字词黑名单检查
    blacklist = ["酥酥", "热热", "痒痒", "空空", "软软", "黏黏", "湿湿",
                 "甜甜", "暖暖", "麻麻", "紧紧", "high爆", "high到",
                 "咕咕叫", "咯咯", "嗯嗯", "嘻嘻"]
    hit = [w for w in blacklist if w in text]

    return {
        "len": len(text),
        "max_run": max_run,
        "max_aa_chain": max_aa_chain,
        "blacklist_hits": hit,
    }


def call_api(prompt: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2048,
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


def extract_json(raw: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def main():
    out_path = os.path.join(os.path.dirname(__file__), "memory_rewrite_ab.md")
    fout = open(out_path, "w", encoding="utf-8")

    def log(s=""):
        print(s.encode("gbk", errors="replace").decode("gbk", errors="replace"))
        fout.write(s + "\n")
        fout.flush()

    runs = 3
    for label, head in [("旧 prompt", OLD_PROMPT), ("新 prompt", NEW_PROMPT)]:
        log(f"\n{'='*70}\n{label}\n{'='*70}")
        prompt = build_input(head)
        for i in range(runs):
            try:
                raw = call_api(prompt)
            except Exception as e:
                log(f"  run{i+1}: API 错误 {e}")
                continue
            obj = extract_json(raw)
            if not obj:
                log(f"  run{i+1}: JSON 解析失败，原文：{raw[:200]}")
                continue
            event = str(obj.get("event", ""))
            pa = str(obj.get("player_action", ""))
            m_e = analyze(event)
            m_p = analyze(pa)
            log(f"\n  run{i+1}")
            log(f"    player_action: [{m_p['max_run']}字最长 / AA链{m_p['max_aa_chain']}] {pa}")
            log(f"    event:         [{m_e['max_run']}字最长 / AA链{m_e['max_aa_chain']}] {event}")
            if m_e["blacklist_hits"]:
                log(f"    ⚠️ 黑名单词命中: {m_e['blacklist_hits']}")
            time.sleep(0.5)

    fout.close()
    print(f"\n完整结果已保存到 {out_path}")


if __name__ == "__main__":
    main()

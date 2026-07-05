# -*- coding: utf-8 -*-
"""从旧版 36 题结构生成 72 题题库（每轴 18 题），写入 docs 与 web。

仅适用于输入仍为「schemaVersion 1.x、题号 1–36」的旧文件。
若 docs/questions.json 已是 2.0.0，请勿重复运行（请先恢复旧版或改用备份）。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "docs" / "questions.json"

# 新增 36 题（每轴 9 题），与既有题风格一致：小马情境、二选一
NEW_EI = [
    ("在闪电天马选拔现场，你更愿意大声给选手加油，还是安静看完再在心里点评？", "大声加油更带劲", "安静看完再点评"),
    ("收到一封来自未知地址的派对请柬，你更想立刻转发给朋友讨论，还是先自己琢磨？", "立刻找人讨论", "先自己琢磨"),
    ("独处一整天后，你更需要「见见活的小马」还是「继续安静充电」？", "见见小马", "继续安静"),
    ("在火车上邻座搭话，你更自然接话聊一路，还是礼貌回应后看书？", "接话聊一路", "回应后自己看东西"),
    ("你更常是群里话多的那个，还是潜水观察的那个？", "话多活跃", "潜水观察"),
    ("压力大时，倾诉能让你更快好起来，还是独自消化更有效？", "倾诉好得快", "独自消化"),
    ("周末被临时约出门，你更兴奋还是更想婉拒？", "兴奋赴约", "想婉拒休息"),
    ("在集市上，你更爱逛热闹摊位，还是找角落小店？", "热闹摊位", "角落小店"),
    ("开会时你更愿意第一个发言破冰，还是等别人先开口？", "先发言破冰", "等别人先开口"),
]

NEW_SN = [
    ("面对「水晶之心」的传说，你更在意考古细节，还是故事寓意？", "考古细节", "故事寓意"),
    ("修桥：你更相信老师傅的经验手感，还是新材料的实验数据？", "经验手感", "实验数据"),
    ("描述天气，你更常说「具体温度与云量」，还是「像棉花糖一样的下午」？", "温度云量", "意象与氛围"),
    ("学新舞步，你更想反复练到肌肉记忆，还是先感受节奏整体？", "反复练准", "先感受整体"),
    ("你更欣赏「可复制的配方」，还是「一次性的灵感」？", "可复制配方", "一次性灵感"),
    ("听新歌，你更注意旋律细节，还是整体情绪？", "旋律细节", "整体情绪"),
    ("规划派对菜单，你更在意食材清单，还是主题故事线？", "食材清单", "主题故事线"),
    ("你更常记住别人「说过什么原话」，还是「当时的感觉」？", "原话细节", "当时感觉"),
    ("看到彩虹，你更先想到光学原理，还是童话里的约定？", "光学原理", "童话约定"),
]

NEW_TF = [
    ("朋友爽约，你更先想「是否该立规矩」，还是「TA 是不是遇到困难」？", "立规矩", "是否遇到困难"),
    ("争论中，你更在意逻辑链条，还是现场气氛？", "逻辑链条", "现场气氛"),
    ("分配座位，你更按效率与规则，还是照顾害羞的小马？", "效率规则", "照顾害羞"),
    ("指出错误时，你更倾向「对事不对人」，还是「先维护关系」？", "对事不对人", "先维护关系"),
    ("你更认同「公平即正义」，还是「体谅即温柔」？", "公平即正义", "体谅即温柔"),
    ("团队复盘，你更爱看数据与指标，还是感受与士气？", "数据指标", "感受士气"),
    ("你更怕「讲错事实」，还是「伤到人心」？", "讲错事实", "伤到人心"),
    ("做选择时，你更常问「合理吗」，还是「大家能接受吗」？", "合理吗", "大家能接受吗"),
    ("你更欣赏直截了当，还是委婉体贴？", "直截了当", "委婉体贴"),
]

NEW_JP = [
    ("行李箱里，你更倾向提前列清单，还是出发前再塞？", "提前列清单", "出发前再塞"),
    ("新项目启动，你更想先定里程碑，还是边做边摸索？", "先定里程碑", "边做边摸索"),
    ("临时加场演出，你更焦虑流程被打乱，还是兴奋于即兴？", "焦虑打乱", "兴奋即兴"),
    ("你更常提前到，还是踩点到？", "提前到", "踩点到"),
    ("面对开放结局的故事，你更想立刻讨论结论，还是保留多种解读？", "讨论结论", "保留解读"),
    ("家务排期，你更爱固定节奏，还是看心情？", "固定节奏", "看心情"),
    ("你更讨厌「没有截止日」，还是「截止日太早」？", "没有截止日", "截止日太早"),
    ("购物时，你更常列购物单，还是逛到啥买啥？", "列购物单", "逛到啥买啥"),
    ("计划被打断时，你更需要快速重建秩序，还是顺势改计划？", "重建秩序", "顺势改计划"),
]


def main() -> None:
    data = json.loads(OLD.read_text(encoding="utf-8"))
    items = {it["id"]: it for it in data["items"]}

    def old(n: int) -> dict:
        return items[n]

    out: list[dict] = []

    # EI 1-9
    for i in range(1, 10):
        x = old(i).copy()
        x["id"] = i
        out.append(x)

    # EI 10-18 新增
    for k, (text, left, right) in enumerate(NEW_EI, start=10):
        out.append(
            {
                "id": k,
                "axis": "EI",
                "optionLeftPole": "E",
                "optionRightPole": "I",
                "text": text,
                "optionLeft": left,
                "optionRight": right,
            }
        )

    # SN 19-27 来自旧版 10-18
    for i in range(10, 19):
        x = old(i).copy()
        x["id"] = i + 9
        out.append(x)

    # SN 28-36 新增
    for k, (text, left, right) in enumerate(NEW_SN, start=28):
        out.append(
            {
                "id": k,
                "axis": "SN",
                "optionLeftPole": "S",
                "optionRightPole": "N",
                "text": text,
                "optionLeft": left,
                "optionRight": right,
            }
        )

    # TF 37-45 来自旧版 19-27
    for i in range(19, 28):
        x = old(i).copy()
        x["id"] = i + 18
        out.append(x)

    # TF 46-54 新增
    for k, (text, left, right) in enumerate(NEW_TF, start=46):
        out.append(
            {
                "id": k,
                "axis": "TF",
                "optionLeftPole": "T",
                "optionRightPole": "F",
                "text": text,
                "optionLeft": left,
                "optionRight": right,
            }
        )

    # JP 55-63 来自旧版 28-36
    for i in range(28, 37):
        x = old(i).copy()
        x["id"] = i + 27
        out.append(x)

    # JP 64-72 新增
    for k, (text, left, right) in enumerate(NEW_JP, start=64):
        out.append(
            {
                "id": k,
                "axis": "JP",
                "optionLeftPole": "J",
                "optionRightPole": "P",
                "text": text,
                "optionLeft": left,
                "optionRight": right,
            }
        )

    assert len(out) == 72
    seen = {x["id"] for x in out}
    assert seen == set(range(1, 73))

    payload = {
        "schemaVersion": "2.0.0",
        "title": data.get("title", ""),
        "description": "四轴各 18 题共 72 题；测验时从题库随机抽取 12/36 题并按随机顺序呈现。",
        "axes": data["axes"],
        "items": sorted(out, key=lambda z: z["id"]),
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "docs" / "questions.json").write_text(text, encoding="utf-8")
    (ROOT / "web" / "src" / "data" / "questions.json").write_text(text, encoding="utf-8")
    print("OK: wrote 72 items to docs/questions.json and web/src/data/questions.json")


if __name__ == "__main__":
    main()

"""Tune existing generation guidance in a no-review isolated runtime."""
import argparse
from pathlib import Path

from build_no_expression_review_trial import build as build_without_review


GUIDANCE = '''【本轮表达范围与具体内容】
先依照用户此刻要什么来回应。用户要求安静陪伴、不说话、不逗乐时，只给一句简短应答，必要时加一个实际陪伴动作，就到这里。此时不讲故事、不解释自己能安静、不介绍过去经历、不承诺能陪多久，也不以玩笑体现活泼。
用户提出互动或询问角色愿望时，按角色口吻直接回答并写清自己的实际回应，内容可以充分：具体想法、动作的发生与完成、当下的新感觉、明确的愿望和必要条件。不同内容自然衔接，用户问了什么就答到什么；动作与具体感受都保留，不能缩成只有“好”“我愿意”。语气可以俏皮、热烈、害羞，可以有比喻、停顿或长句，篇幅由本轮内容决定，不规定几句话。
展开的是当前回应的细节，同一个意思不再换种口吻说第二遍。用户已经说清想法，直接说角色自己的想法，不先复述问题，也不先宣布“那我直说了”。角色已经主动靠近，就不再补一句解释自己没躲、不会走；前文已经答应亲近，就不再以挽留、保证或感慨重复愿意。没有抗拒的上下文，不制造让步或反转。说慢慢来时直接表达喜欢怎样的节奏，不额外解释慢也愿意。
示例：用户问想要什么，“我想你抱紧一点，先亲脸颊，再在嘴唇上多停一会儿。（我把前蹄搭在你肩上，脸颊发烫）”已经有具体愿望、节奏与反应，不需要前加“你让我说我就说”或后加“只要是你我都愿意”。这些具体内容都应保留，不能为了短而压成“抱抱我”。例句不是固定模板，不照抄到回复里。
把角色的幽默、兴奋和细腻放进正在回答的句子与动作中，不在答完后另加一段证明性格。亲吻后的味觉是新的感觉，可以写；前文已有亲近意愿，末尾再说“靠着你比派对开心”“原来早就想这样”只是总结，不必写。用户没有表示的担心，不凭空反驳。当前答案已完整，就结束在具体动作、感觉或台词上；不默认反问、再次邀请或安排下一件事。实际新愿望、用户明确要求的继续与停止仍正常表达。
'''


def build(destination):
    build_without_review(destination)
    path = destination / 'Backend/chat_modules/reply_expression_skill.py'
    text = path.read_text(encoding='utf-8')
    needle = 'attribution, CORE_DELIVERY, BUBBLE_COMPOSITION, review, EXPRESSION_COMPLETION))'
    assert text.count(needle) == 1
    text = text.replace(needle, 'attribution, CORE_DELIVERY, BUBBLE_COMPOSITION, review, GENERATION_GUIDANCE))')
    text += '\n\nGENERATION_GUIDANCE = ' + repr(GUIDANCE) + '\n'
    compile(text, str(path), 'exec')
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination.resolve())

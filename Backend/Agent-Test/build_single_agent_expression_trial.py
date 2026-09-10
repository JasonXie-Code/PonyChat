"""Build an isolated single-Agent editing skill overlay; never alter live code."""
from pathlib import Path
import argparse
import shutil

from run_expression_convergence import ROOT, RUNTIME


MANUAL = '''【主 Agent 表达修订 skill】
你自己完成草稿与交付前修订，不另叫编辑模型。先按当前用户、角色、偏好及场景写完整回复草稿，再检查其完成点；最后输出草稿及明确的局部删除清单，程序应用后才发送。不要向用户展示草稿、清单或检查过程。
检查：回复已经承接用户意图后，是否又补了一句同义许可、依恋收尾、动作后的自我解释、凭空反驳用户没有的担心？判断新增内容，不按词语黑名单删除；新的感觉、具体愿望、必要条件与用户主动要求仍保留。
例如，已写靠近的动作，随后单独补“没有退开”通常重复；用户要求安静陪伴，“好，你靠着就好，我在这儿坐着。”即可，不再补安静也很好或不用说话等解释。但害羞角色主动询问再靠一会儿若承载新的愿望，不因含靠近字样一律删除。
保持最终 JSON 的全部普通交付字段；bubbles 放未经此次修订的草稿。额外根字段 expression_edits 必须是数组，每项严格为 bubble、part、original、replacement、reason；bubble/part 从 1 开始，original 必须逐字等于对应草稿片段，replacement 只许从该片段删除词句或调整标点空格，不得新增或重排词句。reason 简述删除的具体重复，不写思考过程。无需修改就填 []。同一片段只列一次，删整段填空串，不能删光全部回复。原始用户发言、偏好、业务字段不得改动。
'''


def replace(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)


def build(destination):
    destination.mkdir(parents=True, exist_ok=False)
    for name in RUNTIME:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = destination / 'Backend/chat_modules/autonomous_prompt_skills.py'
    text = path.read_text(encoding='utf-8')
    text = replace(text, '        self.catalog[\'reply_language\'] =',
        '        from .Prompts import EXPRESSION_COMPLETION, EXPRESSION_FINAL_CHECK\n'
        '        self.catalog["expression_revision"] = ("提交正文前执行草稿局部修订", ' + repr(MANUAL)
        + ' + "\\n" + EXPRESSION_COMPLETION + "\\n主Agent自行复读修订稿：" + EXPRESSION_FINAL_CHECK)\n'
        + '        self.catalog[\'reply_language\'] =')
    text = replace(text, "required_skills = ['reply_expression', 'reply_language']",
        "required_skills = ['reply_expression', 'reply_language', 'expression_revision']")
    text = replace(text, "        data['required_skills_before_reply'] =",
        '        new_system += "\\n本实验只由主Agent修订表达。读取expression_revision技能后，最终JSON额外提交expression_edits数组；bubbles保留草稿，程序根据清单删改后再交付。无需修改也必须提交空数组。"\n'
        + "        data['required_skills_before_reply'] =")
    text = replace(text, "            if result.get('finish_reason') == 'completed' and self.interaction_mode is None:",
        "            if result.get('finish_reason') == 'completed' and 'expression_revision' not in self.loaded:\n"
        "                result['expression_revision_required'] = True\n"
        + "            if result.get('finish_reason') == 'completed' and self.interaction_mode is None:")
    start = text.index('    from .agent_expression_review import review_expression\n', text.index('async def run_skill_turn'))
    end = text.index('    interaction_modes.attach_mode', start)
    text = text[:start] + "    expression_review = result.get('inline_expression_review', {'status': 'missing'})\n" + text[end:]
    path.write_text(text, encoding='utf-8')
    path = destination / 'Backend/chat_modules/autonomous_normal.py'
    text = path.read_text(encoding='utf-8')
    text = replace(text, '                        delivery_metadata(parsed_reply)',
        "                        from .agent_expression_review import apply_inline_revision\n"
        "                        parsed_reply, inline_review = apply_inline_revision(parsed_reply, result)\n"
        "                        delivery_metadata(parsed_reply)")
    text = replace(text, '                                "scene_patch": scene_patch,',
        '                                "inline_expression_review": inline_review,\n'
        '                                "scene_patch": scene_patch,')
    path.write_text(text, encoding='utf-8')
    path = destination / 'Backend/chat_modules/agent_expression_review.py'
    path.write_text(path.read_text(encoding='utf-8') + '''

def apply_inline_revision(parsed_reply, result):
    """Validate and apply main-Agent edits locally, without a model call."""
    if result.get('expression_revision_required'):
        raise ValueError('提交回复前必须读取 expression_revision 技能。')
    source = json.loads(parsed_reply)
    if 'expression_edits' not in source:
        raise ValueError('最终 JSON 缺少 expression_edits 数组；无修改填 []。')
    edits = source.pop('expression_edits')
    try:
        updated, changes = apply_edits(source, {'edits': edits})
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError('expression_edits 位置或内容无效: ' + str(exc)) from exc
    return json.dumps(updated, ensure_ascii=False), {
        'status': 'reviewed_inline', 'executor': 'main_agent', 'draft': source,
        'edits': edits, 'changes': changes, 'final': updated,
        'independent_review_calls': 0, 'skill_read': True,
    }
''', encoding='utf-8')
    for name in RUNTIME:
        compile((destination / name).read_bytes(), name, 'exec')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination.resolve())

"""Create an isolated normal Agent variant with no post-generation review."""
import argparse
from pathlib import Path
import shutil

from run_expression_convergence import ROOT, RUNTIME


def build(destination):
    destination.mkdir(parents=True, exist_ok=False)
    for name in RUNTIME:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = destination / 'Backend/chat_modules/autonomous_prompt_skills.py'
    text = path.read_text(encoding='utf-8')
    assert 'expression_revision' not in text, 'Source contains experimental skill'
    start = text.index('    from .agent_expression_review import review_expression\n',
                       text.index('async def run_skill_turn'))
    end = text.index('    interaction_modes.attach_mode', start)
    text = text[:start] + (
        "    expression_review = {'status': 'disabled_for_comparison', "
        "'independent_review_calls': 0}\n") + text[end:]
    compile(text, str(path), 'exec')
    assert 'await review_expression(' not in text
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination.resolve())

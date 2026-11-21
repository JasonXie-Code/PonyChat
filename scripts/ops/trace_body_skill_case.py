"""Trace one isolated real-route case without changing model inputs or policies."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
LIVE = Path('P:/PonyChat')
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'docs/testing/twilight-body-trace-20260910'
CHARACTER_ID = sys.argv[2] if len(sys.argv) > 2 else 'twilight_sparkle'
sys.path.insert(0, str(LIVE / 'scripts/ops'))
spec = importlib.util.spec_from_file_location('style_probe', LIVE / 'Backend/Agent-Test/run_style_matrix_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
trace = []


async def exercise(workspace):
    for name in ('autonomous_direct.py', 'autonomous_prompt_skills.py', 'interaction_modes.py',
                 'reply_expression_skill.py', 'autonomous_prompt_rules.py'):
        shutil.copyfile(ROOT / 'Backend/chat_modules' / name, workspace / 'Backend/chat_modules' / name)
    hashes = {}
    for name in ('autonomous_direct.py', 'autonomous_prompt_skills.py', 'interaction_modes.py',
                 'reply_expression_skill.py', 'autonomous_prompt_rules.py'):
        content = (workspace / 'Backend/chat_modules' / name).read_bytes()
        assert content == (ROOT / 'Backend/chat_modules' / name).read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
    (OUT / 'source-hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    sys.path.insert(0, str(workspace))
    from Backend.chat_modules.autonomous_prompt_skills import PromptSkills
    originals = {name: getattr(PromptSkills, name) for name in ('load', 'reference')}

    def observed(name, callback):
        async def call(self, arguments):
            row = {'sequence': len(trace) + 1, 'tool': name, 'arguments': arguments}
            trace.append(row)
            try:
                result = await callback(self, arguments)
                row['result'] = result
                return result
            except Exception as exc:
                row['error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            finally:
                (OUT / 'tool-trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
        return call

    for name, callback in originals.items():
        setattr(PromptSkills, name, observed(name, callback))
    try:
        return await probe.exercise(workspace)
    finally:
        for name, callback in originals.items():
            setattr(PromptSkills, name, callback)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=False)
    profiles = json.loads((ROOT / 'docs/testing/contextual-explanation-20260910/baseline/profiles.json').read_text(encoding='utf-8'))
    selected = [p for p in profiles if p['id'] == CHARACTER_ID]
    assert len(selected) == 1, 'Unknown or ambiguous character'
    (OUT / 'profiles.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    cases = [['handoff', '递点心并握手', '（我坐在你旁边，把手伸到桌边。）把桌上那块点心递给我，再握一下我的手，好吗？']]
    (OUT / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    os.environ.update(PONYCHAT_STYLE_PROFILES=str(OUT / 'profiles.json'),
                      PONYCHAT_STYLE_CASES=str(OUT / 'cases.json'),
                      PONYCHAT_STYLE_PROGRESS=str(OUT / 'progress.json'))
    probe.smoke.exercise = exercise
    sys.argv = [sys.argv[0], str(OUT / 'raw.json'), '--source', str(LIVE)]
    raise SystemExit(probe.smoke.main())

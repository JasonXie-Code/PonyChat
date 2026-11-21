import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


agent_test = Path(__file__).parents[1] / 'Agent-Test'
sys.path.insert(0, str(agent_test))
spec = importlib.util.spec_from_file_location('tested_style_probe_snapshot', agent_test / 'run_style_acceptance.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def source_run(directory):
    source = directory / 'source' / 'Backend'
    source.mkdir(parents=True)
    (source / 'runtime.py').write_bytes(b'original runtime\n')
    profiles = directory / 'profiles.json'
    profiles.write_bytes(b'{"profiles": []}')
    digest = hashlib.sha256((source / 'runtime.py').read_bytes()).hexdigest()
    (directory / 'source-manifest.json').write_text(json.dumps({'Backend/runtime.py': digest}), encoding='utf-8')
    (directory / 'run.json').write_text(json.dumps({'reasoning_effort': 'low',
        'profile_sha256': hashlib.sha256(profiles.read_bytes()).hexdigest()}), encoding='utf-8')


def test_observational_snapshot_preserves_runtime_and_profile_bytes(tmp_path):
    previous = tmp_path / 'previous'
    source_run(previous)
    output = tmp_path / 'new'
    output.mkdir()
    source, origin = runner.reuse_snapshot(previous, output)
    assert (source / 'Backend/runtime.py').read_bytes() == b'original runtime\n'
    assert (output / 'profiles.json').read_bytes() == (previous / 'profiles.json').read_bytes()
    assert origin['reasoning_effort'] == 'low'


def test_mutated_or_escaping_snapshot_manifest_is_rejected(tmp_path):
    previous = tmp_path / 'previous'
    source_run(previous)
    output = tmp_path / 'new'
    output.mkdir()
    (previous / 'source/Backend/runtime.py').write_bytes(b'mutated')
    with pytest.raises(ValueError, match='snapshot mismatch'):
        runner.reuse_snapshot(previous, output)
    (previous / 'source-manifest.json').write_text('{"../escape.py": "untrusted"}', encoding='utf-8')
    with pytest.raises(ValueError, match='snapshot mismatch'):
        runner.reuse_snapshot(previous, output)


def test_unmanifested_runtime_code_is_rejected(tmp_path):
    previous = tmp_path / 'previous'
    source_run(previous)
    output = tmp_path / 'new'
    output.mkdir()
    (previous / 'source/Backend/extra.py').write_bytes(b'unrecorded')
    with pytest.raises(ValueError, match='unmanifested'):
        runner.reuse_snapshot(previous, output)

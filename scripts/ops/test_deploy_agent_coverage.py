import pytest

from deploy_agent_coverage import validate_paths


@pytest.mark.parametrize('path', ['../Backend/a.py', 'Backend/../a.py', 'Backend//a.py',
    '/Backend/a.py', 'Backend/a.py/..', 'Backend/a.py:secret', 'Backend\\a.py',
    'Backend/a.txt', 'Backend/x/../../a.py', 'Backend/a.py\n', 'Other/a.py'])
def test_release_and_delete_paths_stay_in_backend(path):
    with pytest.raises(ValueError):
        validate_paths([path])


def test_explicit_file_paths_only():
    names = ['Backend/chat_modules/unused.py', 'Backend/Agent-Test/old_probe.py']
    assert validate_paths(names) == names
    assert validate_paths([], allow_empty=True) == []
    with pytest.raises(ValueError):
        validate_paths([])
    with pytest.raises(ValueError):
        validate_paths([names[0], names[0]])


def test_retired_ops_files_need_the_explicit_delete_scope():
    path = 'scripts/ops/deploy_evidence_review.py'
    assert validate_paths([path], allow_ops=True) == [path]
    with pytest.raises(ValueError):
        validate_paths([path])
    with pytest.raises(ValueError):
        validate_paths(['scripts/ops/../../secret.py'], allow_ops=True)

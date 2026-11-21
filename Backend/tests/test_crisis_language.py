import pytest

from Backend.chat_modules.state import has_crisis_language


@pytest.mark.parametrize("text", [
    "想死你了", "我真想死你了！", "想死你啦，快回来", "想死他了",
])
def test_missing_someone_does_not_trigger_crisis(text):
    assert not has_crisis_language(text)


@pytest.mark.parametrize("text", [
    "我想死", "我不想活了", "我想自杀", "我想死你了，但我真的想死",
])
def test_self_harm_language_still_triggers_crisis(text):
    assert has_crisis_language(text)

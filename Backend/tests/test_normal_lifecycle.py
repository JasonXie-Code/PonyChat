import asyncio

from Backend.chat_modules.normal_lifecycle import (
    get_normal_character_state,
    is_explicit_character_death_action,
    mark_normal_character_dead,
)


class _FakeDb:
    def __init__(self, path):
        self.db_path = str(path)

    async def init(self):
        return None


def test_explicit_character_death_action_detection():
    assert is_explicit_character_death_action("（我一剑杀死了你）")
    assert is_explicit_character_death_action("I killed her with my hammer.")
    assert is_explicit_character_death_action("（我把石青派打死了）", character_name="石青派")
    assert is_explicit_character_death_action("（我扣下扳机，直接爆头）")
    assert is_explicit_character_death_action("（我抓住破绽，一击刺穿你的心脏）")
    assert is_explicit_character_death_action("（我挥刀斩首，让她倒下）")
    assert not is_explicit_character_death_action("如果我杀死你会怎么样")
    assert not is_explicit_character_death_action("（我用力一拳打过去，把你打退两步）")
    assert not is_explicit_character_death_action("（我用力一拳将你打趴，鼻血飞溅，随后踩住你，不让你动）")
    assert not is_explicit_character_death_action("（我把你打成重伤，你奄奄一息）")
    assert not is_explicit_character_death_action("（我把你打晕过去）")
    assert not is_explicit_character_death_action("（我复活了你）")
    assert not is_explicit_character_death_action("（我杀死了你的分身，本体还在远处没有受伤）")
    assert not is_explicit_character_death_action("（死的只是你的魔法替身，真正的紫悦还在图书馆）", character_name="紫悦")
    assert not is_explicit_character_death_action("（我假死后第二天又回来了）")
    assert not is_explicit_character_death_action("I killed your clone, but you are still safe.")
    assert is_explicit_character_death_action("（我先击碎你的分身，然后又杀死了你）")


def test_normal_character_dead_state_persists(tmp_path, monkeypatch):
    async def run():
        db = _FakeDb(tmp_path / "normal_lifecycle.db")
        monkeypatch.setattr("Backend.chat_modules.normal_lifecycle.get_database", lambda: db)

        assert await get_normal_character_state("tester", "char1", "conv1") == "alive"
        await mark_normal_character_dead(
            "tester",
            "char1",
            "conv1",
            message_id="u1",
            reason="test death",
        )
        assert await get_normal_character_state("tester", "char1", "conv1") == "dead"
        assert await get_normal_character_state("tester", "char1", "conv2") == "alive"

    asyncio.run(run())

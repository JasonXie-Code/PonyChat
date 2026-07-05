import asyncio

from Backend import proactive_settings


def test_memory_disabled_forces_proactive_disabled(monkeypatch):
    class FakeSettingsDAO:
        def __init__(self, _db):
            pass

        async def load_settings(self, _username):
            return {
                "memory_enabled": False,
                "proactive_messages_enabled": True,
                "proactive_frequency": "high",
            }

    monkeypatch.setattr(proactive_settings, "get_database", lambda: object())
    monkeypatch.setattr(proactive_settings, "SettingsDAO", FakeSettingsDAO)

    settings = asyncio.run(proactive_settings.load_proactive_settings("tester"))

    assert settings.memory_enabled is False
    assert settings.enabled is False
    assert settings.frequency == "high"


def test_memory_enabled_keeps_proactive_switch_semantics(monkeypatch):
    class FakeSettingsDAO:
        def __init__(self, _db):
            pass

        async def load_settings(self, _username):
            return {
                "memory_enabled": True,
                "proactive_messages_enabled": True,
                "proactive_frequency": "low",
            }

    monkeypatch.setattr(proactive_settings, "get_database", lambda: object())
    monkeypatch.setattr(proactive_settings, "SettingsDAO", FakeSettingsDAO)

    settings = asyncio.run(proactive_settings.load_proactive_settings("tester"))

    assert settings.memory_enabled is True
    assert settings.enabled is True
    assert settings.frequency == "low"

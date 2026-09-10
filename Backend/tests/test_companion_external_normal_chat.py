from Backend.chat_modules import service


def test_companion_external_uses_authoritative_normal_conversation_history():
    assert "companion_external" in service._ANDROID_DELTA_CLIENT_IDS

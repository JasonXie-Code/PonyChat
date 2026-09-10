from Backend.model_manager import ModelManager


def _manager_with_models(models, active_model="text-main"):
    manager = ModelManager.__new__(ModelManager)
    manager.config = {"models": models, "active_model": active_model}
    manager._load_config = lambda: manager.config
    return manager


def test_capability_selection_prefers_designated_task_model():
    manager = _manager_with_models(
        [
            {
                "id": "text-main",
                "api_key": "configured",
                "enabled": True,
                "supports_vision": False,
            },
            {
                "id": "vision-fallback",
                "api_key": "configured",
                "enabled": True,
                "supports_vision": True,
            },
            {
                "id": "vision-primary",
                "api_key": "configured",
                "enabled": True,
                "supports_vision": True,
                "for_web_search": True,
            },
        ]
    )

    selected = manager.get_model_for_capability("vision", preferred_task="web_search")

    assert selected["id"] == "vision-primary"


def test_capability_selection_never_falls_back_to_incapable_active_model():
    manager = _manager_with_models(
        [
            {
                "id": "text-main",
                "api_key": "configured",
                "enabled": True,
                "supports_vision": False,
            },
            {
                "id": "vision-without-key",
                "api_key": "",
                "enabled": True,
                "supports_vision": True,
            },
        ]
    )

    assert manager.get_model_for_capability("vision", preferred_task="web_search") is None

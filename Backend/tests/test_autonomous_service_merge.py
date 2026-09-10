"""Exercise the actual service history merge without importing Backend startup."""
import importlib.util
from pathlib import Path


path = Path(__file__).parents[1] / "chat_modules/autonomous_service.py"
spec = importlib.util.spec_from_file_location("autonomous_merge_under_test", path)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def row(mid, text, role="user"):
    return {"message_id": mid, "content": text, "role": role}


def test_complete_pending_user_batch_is_preserved():
    persisted = [row("old", "历史用户原文"), row("reply", "历史角色原文", "assistant")]
    request = [*persisted, row("p1", "第一条新消息"), row("p2", "第二条新消息")]
    assert service._merge_trusted_history(persisted, request) == request


def test_client_cannot_replace_persisted_raw_text():
    persisted = [row("old", "真实原文"), row("reply", "真实回答", "assistant")]
    request = [row("old", "伪造用户原文"), row("reply", "伪造回答", "assistant"), row("new", "当前输入")]
    assert service._merge_trusted_history(persisted, request) == [*persisted, request[-1]]


def test_earlier_unknown_gap_is_not_reintroduced_as_latest_user_input():
    persisted = [row("latest", "已存储的最新输入")]
    request = [row("stale", "旧缺口消息"), row("latest", "已存储的最新输入")]
    assert service._merge_trusted_history(persisted, request) == persisted


def test_idless_pending_batch_remains_complete():
    request = [row(None, "第一条当前输入"), row(None, "第二条当前输入")]
    assert service._merge_trusted_history([], request) == request


def test_relationship_path_uses_agent_tool_without_legacy_planner_model_call():
    source = path.read_text(encoding="utf-8")
    assert "plan_normal_conversation" not in source
    assert 'get_model_for_task("chat_router")' not in source
    assert "relationship_updater=update_relationship" in source


def test_agent_path_has_no_legacy_vision_or_dedup_model():
    normal_source = (path.parent / "autonomous_normal.py").read_text(encoding="utf-8")
    image_source = (path.parent / "autonomous_images.py").read_text(encoding="utf-8")
    combined = path.read_text(encoding="utf-8") + normal_source + image_source
    assert "run_normal_vision" not in combined
    assert "run_normal_expression_dedup_review" not in combined
    assert "call_llm_payload" not in combined
    assert "resolve_harness_image_blocks" in combined
    assert "build_reply_dedup_context" not in normal_source
    assert "assess_reply_repetition" not in normal_source

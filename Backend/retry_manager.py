from dataclasses import dataclass
from typing import Callable, List


DUPLICATE_RETRY_CODES = {
    "duplicate_response",
    "duplicate_non_tag_payload",
    "duplicate_env",
    "duplicate_body_state",
    "duplicate_thoughts",
    "duplicate_options",
}


@dataclass
class GalgameRetryState:
    """Galgame 重试状态机：统一管理去重/schema补全两个阶段。"""
    anti_dup_phase: int = 0  # 0=关闭, 1=普通去重, 2=严格锁字段去重
    last_duplicate_code: str = ""
    last_duplicate_raw: str = ""
    best_attempt_raw: str = ""  # 重试过程中"最好的"原始输出（通过了最多检查的那次）
    schema_phase: int = 0  # 0=关闭, 1=普通补全, 2=严格补全
    last_schema_raw: str = ""
    last_schema_error: str = ""


def compute_backoff_delay(attempt: int) -> int:
    """指数退避秒数：1,2,4,8,16..."""
    return 1 * (2 ** max(0, int(attempt)))


def can_retry(attempt: int, max_retries: int) -> bool:
    """当前尝试是否还能继续重试。"""
    return int(attempt) < int(max_retries)


def build_retry_instructions(
    state: GalgameRetryState,
    retry_scene_min_required: int,
    retry_scene_word_limit: int,
    extract_json_hint: Callable[[str], str],
    build_anti_duplicate_instruction: Callable[[str, str, bool], str],
    build_schema_instruction: Callable[[bool, str, str], str],
) -> List[str]:
    """根据当前状态组装重试提示词（去重 + schema补全）。"""
    instructions: List[str] = []
    if state.anti_dup_phase > 0 and state.last_duplicate_code:
        strict_lock = state.anti_dup_phase >= 2
        always_hint = state.last_duplicate_code in (
            "duplicate_response", "duplicate_env", "duplicate_body_state", "duplicate_thoughts",
            "duplicate_options",
        )
        previous_json_hint = extract_json_hint(state.last_duplicate_raw) if (strict_lock or always_hint) else ""
        instructions.append(
            build_anti_duplicate_instruction(
                state.last_duplicate_code,
                previous_json_hint=previous_json_hint,
                strict_lock=strict_lock,
            )
        )
    if state.schema_phase > 0:
        strict_lock = state.schema_phase >= 2
        previous_json_hint = extract_json_hint(state.last_schema_raw) if strict_lock else ""
        instructions.append(
            build_schema_instruction(
                strict_lock,
                previous_json_hint,
                state.last_schema_error,
            )
        )
    return instructions


def apply_retry_code(state: GalgameRetryState, retry_code: str, last_raw: str, error_text: str = "") -> List[str]:
    """
    根据 retry_code 推进重试状态。
    返回 events 供调用方记录日志：
    - enable_anti_dup / escalate_anti_dup
    """
    events: List[str] = []
    if retry_code in DUPLICATE_RETRY_CODES:
        state.last_duplicate_code = retry_code
        state.last_duplicate_raw = last_raw or ""
        if state.anti_dup_phase == 0:
            state.anti_dup_phase = 1
            events.append("enable_anti_dup")
        elif state.anti_dup_phase == 1:
            state.anti_dup_phase = 2
            events.append("escalate_anti_dup")
    elif retry_code == "json_incomplete_schema":
        state.last_schema_raw = last_raw or ""
        state.last_schema_error = (error_text or "").strip()
        if state.schema_phase == 0:
            state.schema_phase = 1
            events.append("enable_schema_fix")
        elif state.schema_phase == 1:
            state.schema_phase = 2
            events.append("escalate_schema_fix")
    return events


def format_retry_phase_logs(
    events: List[str],
    scope: str,
    retry_code: str,
    retry_scene_min_required: int,
) -> List[str]:
    """将阶段事件转成统一日志文案。"""
    logs: List[str] = []
    for event in events or []:
        if event == "enable_anti_dup":
            logs.append(f"🩹 [{scope}] 下一次重试启用去重改写修复（code={retry_code}）")
        elif event == "escalate_anti_dup":
            logs.append(f"🛠️ [{scope}] 去重后仍重复，下一次重试切换为单字段手术模式（只改重复字段）")
        elif event == "enable_schema_fix":
            logs.append(f"🩹 [{scope}] 下一次重试启用字段补全修复（code={retry_code}）")
        elif event == "escalate_schema_fix":
            logs.append(f"🛠️ [{scope}] 字段补全仍失败，下一次重试启用严格字段补全修复")
    return logs

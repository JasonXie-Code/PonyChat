"""Galgame 分步生成提示词：按流水线步骤拆分为多模块，由此包统一导出。

子模块文件名采用 ``step_NN_…``（NN 与流水线步号对应；``step_00`` 为共用）。

调试日志阶段名（与 ``generate.py`` / ``steps.py`` 一致）统一为：
``SEQ_STEP_<步号>_<名称>_REQUEST`` / ``SEQ_STEP_<步号>_<名称>_RESPONSE``；
重试追加 ``_RETRY_<次数>_REQUEST`` / ``_RETRY_<次数>_RESPONSE``。
记忆改写见 ``memory.py`` 的 ``SEQ_STEP_10_*_REQUEST`` / ``*_RESPONSE``。
"""

from __future__ import annotations

from .step_00_common import _fix_md_markers
from .step_01_director import (
    _SEQ_STEP1_DIRECTOR_TEMPLATE,
    _SEQ_STEP1_ROUND_CONTEXT_TEMPLATE,
    build_seq_step1_director_core_instruction,
    build_seq_step1_director_instruction,
    build_seq_step1_round_context_section,
)
from .step_02_lock_vitals import build_seq_step2_vitals_instruction
from .step_03_text_env import SEQ_TEXT_STEP_SPEC as _TEXT_SPEC_ENV
from .step_04_text_body_state import SEQ_TEXT_STEP_SPEC as _TEXT_SPEC_BODY_STATE
from .step_05_text_thoughts import SEQ_TEXT_STEP_SPEC as _TEXT_SPEC_THOUGHTS
from .step_06_text_third_party import SEQ_TEXT_STEP_SPEC as _TEXT_SPEC_THIRD_PARTY
from .step_07_text_response import SEQ_TEXT_STEP_SPEC as _TEXT_SPEC_RESPONSE
from .step_08_metadata_json import _SEQ_JSON_STEP_INSTRUCTION
from .step_09_options import _SEQ_OPTIONS_STEP_INSTRUCTION
from .step_10_char_memory_update import _SEQ_CHAR_MEMORY_UPDATE

_SEQ_TEXT_STEPS = [
    _TEXT_SPEC_ENV,
    _TEXT_SPEC_BODY_STATE,
    _TEXT_SPEC_THOUGHTS,
    _TEXT_SPEC_THIRD_PARTY,
    _TEXT_SPEC_RESPONSE,
]

_SEQ_STEP_LABEL = {step["name"]: step["label"] for step in _SEQ_TEXT_STEPS}

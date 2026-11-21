"""Assemble workflow and shared conversation rules from the central prompt source."""
from .Prompts import SKILL_CALL_CHECKS, WORKFLOW_GENERATION, LOW_PRESSURE_CONVERSATION_PROMPT

from .reply_expression_skill import expression_manual


def direct_system(cognition_core: str) -> str:
    return (str(cognition_core).strip() + "\n\n" + WORKFLOW_GENERATION + "\n"
            + SKILL_CALL_CHECKS + '\n\n' + LOW_PRESSURE_CONVERSATION_PROMPT)

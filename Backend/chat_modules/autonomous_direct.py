"""Workflow-only system prompt; expression policies live in skill modules."""
from .Prompts import SKILL_CALL_CHECKS, WORKFLOW_GENERATION

from .reply_expression_skill import expression_manual


def direct_system(cognition_core: str) -> str:
    return (str(cognition_core).strip() + "\n\n" + WORKFLOW_GENERATION + "\n"
            + SKILL_CALL_CHECKS)

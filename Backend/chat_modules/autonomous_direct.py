"""Workflow-only system prompt; expression policies live in skill modules."""
from .Prompts import METADATA_CONTRACT, SKILL_CALL_CHECKS, WORKFLOW_GENERATION

# Re-export for existing integrations; direct_system never inserts these manuals.
from .reply_expression_skill import (DIRECT_CHARACTER_RULES, NATURAL_CHARACTER_STYLE,
    IMAGE_RESPONSE_STYLE, TURN_EXPRESSION_REVIEW, expression_manual, CORE_EXPRESSION)


def direct_system(cognition_core: str) -> str:
    return (str(cognition_core).strip() + "\n\n" + WORKFLOW_GENERATION + "\n"
            + SKILL_CALL_CHECKS + "\n" + METADATA_CONTRACT)

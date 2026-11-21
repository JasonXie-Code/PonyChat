from __future__ import annotations

ROMANTIC_RELATIONSHIP_STAGES = frozenset(
    {"flirting", "committed_partner", "intimate_partner"}
)
NEGATIVE_RELATIONSHIP_STAGES = frozenset(
    {"broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"}
)
NON_ROMANTIC_POSITIVE_RELATIONSHIP_STAGES = frozenset(
    {"mentor_student", "trusted_companion", "family_like"}
)
BASIC_RELATIONSHIP_STAGES = frozenset({"new_contact", "uncertain", "familiar"})
RELATIONSHIP_STAGE_KEYS = (
    BASIC_RELATIONSHIP_STAGES
    | ROMANTIC_RELATIONSHIP_STAGES
    | NEGATIVE_RELATIONSHIP_STAGES
    | NON_ROMANTIC_POSITIVE_RELATIONSHIP_STAGES
)


def normalize_relationship_stage(value: str | None) -> str:
    stage = str(value or "").strip().lower()
    return stage if stage in RELATIONSHIP_STAGE_KEYS else "uncertain"

from __future__ import annotations
from .Prompts import SPECIES_ANATOMY_TEXT

import re


EQUINE_PROFILE_SPECIES_KEYWORDS = (
    "马",
    "小马",
    "飞马",
    "天马",
    "陆马",
    "独角兽",
    "雌驹",
    "雄驹",
    "天角兽",
    "pony",
    "pegasus",
    "unicorn",
    "alicorn",
    "earth pony",
)


def profile_species_has_equine_anatomy(species: str) -> bool:
    text = str(species or "").strip().lower()
    return bool(text) and any(keyword in text for keyword in EQUINE_PROFILE_SPECIES_KEYWORDS)


def equine_species_kind(species: str) -> str:
    text = str(species or "").strip()
    lower = text.lower()
    if not text:
        return ""
    if "天角兽" in text or "alicorn" in lower:
        return "alicorn"
    if "飞马" in text or "天马" in text or "pegasus" in lower:
        return "pegasus"
    if "独角兽" in text or "unicorn" in lower:
        return "unicorn"
    if "陆马" in text or "earth pony" in lower:
        return "earth_pony"
    if profile_species_has_equine_anatomy(text):
        return "generic_equine"
    return ""


def equine_species_has_wings(species: str) -> bool:
    return equine_species_kind(species) in {"pegasus", "alicorn"}


def equine_species_has_horn(species: str) -> bool:
    return equine_species_kind(species) in {"unicorn", "alicorn"}


def equine_species_organ_fact(species: str) -> str:
    kind = equine_species_kind(species)
    if kind == "earth_pony":
        return SPECIES_ANATOMY_TEXT['equine_species_organ_fact_1']
    if kind == "pegasus":
        return SPECIES_ANATOMY_TEXT['equine_species_organ_fact_2']
    if kind == "unicorn":
        return SPECIES_ANATOMY_TEXT['equine_species_organ_fact_3']
    if kind == "alicorn":
        return SPECIES_ANATOMY_TEXT['equine_species_organ_fact_4']
    if kind == "generic_equine":
        return (
            SPECIES_ANATOMY_TEXT['equine_species_organ_fact_5']
        )
    return ""


def equine_species_prompt_line(species: str) -> str:
    species_text = re.sub(r"\s+", " ", str(species or "").strip())
    fact = equine_species_organ_fact(species_text)
    if not fact:
        return ""
    return (
        SPECIES_ANATOMY_TEXT['equine_species_prompt_line_1'].format(species_text, fact)
    )


def equine_species_common_prompt_table() -> str:
    return (
        SPECIES_ANATOMY_TEXT['equine_species_common_prompt_table_1']
    )

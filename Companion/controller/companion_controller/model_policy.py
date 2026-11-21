from dataclasses import dataclass

DEEPSEEK_FLASH = "deepseek-flash"
DEEPSEEK_VISION = "deepseek-flash"


@dataclass(frozen=True)
class ModelChoice:
    model: str
    reason: str


def choose_model(*, has_image: bool = False, high_difficulty: bool = False) -> ModelChoice:
    if has_image:
        return ModelChoice(DEEPSEEK_VISION, "vision")
    if high_difficulty:
        return ModelChoice(DEEPSEEK_VISION, "high_difficulty")
    return ModelChoice(DEEPSEEK_FLASH, "simple_task")

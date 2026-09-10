"""Shared expression skill content; never appended to the main system prompt."""
import json

from .Prompts import (DIRECT_CHARACTER_RULES, NATURAL_CHARACTER_STYLE, IMAGE_RESPONSE_STYLE,
                      TURN_EXPRESSION_REVIEW, EXPRESSION_COMPLETION, GENERATION_GUIDANCE,
                      NEUTRAL_EXAMPLE_NOTICE, NEUTRAL_EXAMPLES)
from .autonomous_prompt_rules import BUBBLE_COMPOSITION, CORE_DELIVERY, CORE_EXPRESSION










def expression_manual():
    # Shared representation and attribution rules; character-specific reasoning
    # and explanation habits belong to the selected character manual.
    attribution = '\n'.join(line for line in CORE_EXPRESSION.splitlines()
                            if line.startswith(('1.', '2.', '2a.', '4.', '5.', '6.', '7.', '8.', '11.', '12.', '13.')))
    review = '\n'.join(line for line in TURN_EXPRESSION_REVIEW.splitlines() if line.startswith(('1.', '2.', '3.')))
    return '\n\n'.join((DIRECT_CHARACTER_RULES, NATURAL_CHARACTER_STYLE,
                         attribution, CORE_DELIVERY, BUBBLE_COMPOSITION, review, GENERATION_GUIDANCE,
                         NEUTRAL_EXAMPLE_NOTICE, json.dumps(NEUTRAL_EXAMPLES, ensure_ascii=False)))

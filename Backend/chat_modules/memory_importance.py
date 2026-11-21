"""Shared importance rubric for memory writing and evidence-based rescoring."""
from .Prompts import MEMORY_IMPORTANCE_TEXT

IMPORTANCE_SCHEMA = {'type': 'integer', 'minimum': 1, 'maximum': 10,
                     'description': MEMORY_IMPORTANCE_TEXT['IMPORTANCE_SCHEMA_1']}


def require_importance(arguments):
    value = arguments.get('importance')
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError('importance is required and must be an integer from 1 to 10; assess this memory explicitly')
    return value

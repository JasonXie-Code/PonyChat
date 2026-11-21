"""Expose the complete expression skill without maintaining partial aliases."""
from .Prompts import reply_expression
def expression_manual():
    return reply_expression

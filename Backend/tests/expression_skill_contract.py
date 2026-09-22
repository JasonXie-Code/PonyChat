"""Drive the serial expression-skill read contract from a synthetic transport.

``Backend.chat_modules.autonomous_expression_paths`` wraps the Agent transport and
rejects any turn that reports ``finish_reason == 'completed'`` while the session's
serial read contract is still incomplete (``ExpressionReadIncomplete``). A
compliant model reads the currently required skill one at a time through
``read_next_reply_skill`` and chooses its expression paths through
``select_reply_paths``; ``load()`` refuses any skill that is not the one required
right now. Synthetic transports that only call ``load_chat_skill`` therefore never
advance the contract and are rejected, however correct their envelope is.

This module is deliberately not named ``test_*`` so pytest never collects it.
Tests in this directory import each other by bare module name, so
``from expression_skill_contract import read_expression_contract`` works.
"""
from __future__ import annotations

# reply_expression, reply_conditions, select_reply_paths, per-path dependencies,
# the path itself, reply_deduplication and reply_review fit well inside this bound.
MAX_CONTRACT_STEPS = 16


async def read_expression_contract(tools, paths=('conversation_reply',)):
    """Drive the serial expression-skill reads a compliant turn performs.

    ``paths`` are the expression paths this turn selects, chosen by the real
    scenario semantics (the keys of ``PATHS`` / ``SKILL_WHEN``):

    * ``conversation_reply`` - ordinary chat, whose dependency ``reply_conditions``
      is already part of the mandatory head of the chain.
    * ``interaction_reply`` / ``description_reply`` - action-in-speech and pure
      description turns; both additionally require the ``reply_perspective``
      dependency, which the loop reads automatically.

    A turn whose prompt carries the explicit ``description_shortcut_contract``
    must include ``description_reply`` in ``paths``: ``select_reply_paths``
    rejects a selection that omits it, so such a turn passes
    ``paths=('description_reply',)``.

    Returns the final contract-progress result (``complete`` is true), or ``None``
    when this transport is not an expression-skill Agent turn.
    """
    read_next = tools.get('read_next_reply_skill')
    if read_next is None:
        # Not every synthetic turn runs the serial expression session (memory
        # review, probes); only the Agent turn exposes the contract tools, and it
        # always exposes both of them together.
        assert 'load_chat_skill' not in tools, (
            'read_next_reply_skill is missing from an Agent turn that exposes load_chat_skill')
        return None
    selection = list(paths)
    assert selection, 'a compliant turn selects at least one expression path'
    for _ in range(MAX_CONTRACT_STEPS):
        result = await read_next.callback({})
        status = result.get('status')
        if status == 'complete' or result.get('complete') is True:
            return result
        if status == 'selection_required':
            selected = await tools['select_reply_paths'].callback({'paths': selection})
            assert selected.get('status') == 'selected', f'expression path selection rejected: {selected}'
            continue
        # A skill bundle carries no status: the read advanced the contract by one
        # skill, so ask again for the item that is required next.
        assert status is None, f'unexpected expression read status: {result}'
        assert 'skill' in result, f'unexpected expression read result: {result}'
    raise AssertionError(f'expression read contract did not complete within {MAX_CONTRACT_STEPS} steps')

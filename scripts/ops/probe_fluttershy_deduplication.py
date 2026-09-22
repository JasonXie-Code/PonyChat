"""Replay the unchanged five-turn repetition fixture after skill consolidation."""
import asyncio
from probe_fluttershy_repetition_history import SCENARIOS
from probe_fluttershy_three_scenes import main


if __name__ == '__main__':
    asyncio.run(main(
        scenarios=SCENARIOS, output_name='fluttershy-deduplication-skill-20260913',
        test_metadata={'synthetic_history_exchanges': 5, 'real_continuation_turns': 2,
                       'baseline': 'docs/testing/fluttershy-repetition-history-20260913/results.json',
                       'new_user_messages_request_deduplication': False,
                       'change': 'deduplication skill consolidation and mandatory serial read; no ledger or lexical gate'}))

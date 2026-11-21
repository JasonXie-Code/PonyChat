"""Select complete visible exchanges without treating assistant bubbles as turns."""
from __future__ import annotations


def recent_round_messages(messages, rounds=30):
    """A user batch plus all following assistant bubbles is one exchange.

    Consecutive user messages form one batch. Leading unsolicited assistant
    messages form one standalone exchange. Input must already be visible and
    chronological; content, metadata and message boundaries are not rewritten.
    """
    if type(rounds) is not int or rounds < 1:
        raise ValueError('rounds must be a positive integer')
    rows = list(messages)
    starts = [0] if rows else []
    for index in range(1, len(rows)):
        if rows[index]['role'] == 'user' and rows[index - 1]['role'] != 'user':
            starts.append(index)
    return rows[starts[-rounds]:] if len(starts) > rounds else rows


def read_recent_round_rows(cursor, rounds):
    """Consume a newest-first SQL cursor only through the requested exchanges."""
    rows, count, previous_role = [], 1, None
    for row in cursor:
        role = row['role']
        if previous_role == 'user' and role == 'assistant':
            count += 1
            if count > rounds:
                break
        rows.append(row)
        previous_role = role
    return rows

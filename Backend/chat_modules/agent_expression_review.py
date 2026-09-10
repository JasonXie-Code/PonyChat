"""Bounded Agent draft review before delivery; source input and side effects stay intact."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
import unicodedata

from .Prompts import EXPRESSION_COMPLETION, EXPRESSION_REVIEW_WORKFLOW, EXPRESSION_FINAL_CHECK
from .autonomous_reply import reply_envelope


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def add_usage(result, extra):
    totals = dict(result.get('usage') or {})
    for key, value in (extra.get('usage') or {}).items():
        if type(value) in (int, float):
            totals[key] = totals.get(key, 0) + value
    result['usage'] = totals
    for key in ('llm_api_calls', 'tool_call_count'):
        result[key] = result.get(key, 0) + max(0, int(extra.get(key, 0)))


def apply_edits(source, candidate):
    """Apply exact, per-part deletion edits; the editor cannot author new prose."""
    if not isinstance(candidate, dict) or set(candidate) != {'edits'}:
        raise ValueError('Review must contain edits only')
    edits = candidate['edits']
    if not isinstance(edits, list) or len(edits) > 192:
        raise ValueError('Review edits must be a bounded array')
    updated, seen, changes = deepcopy(source), set(), []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'bubble', 'part', 'original', 'replacement', 'reason'}:
            raise ValueError('Invalid edit fields')
        b, p = edit['bubble'], edit['part']
        if type(b) is not int or type(p) is not int or min(b, p) < 1 or (b, p) in seen:
            raise ValueError('Invalid or duplicate edit location')
        seen.add((b, p))
        part = updated['bubbles'][b-1]['parts'][p-1]
        old, new = edit['original'], edit['replacement']
        if not isinstance(old, str) or not isinstance(new, str) or part['text'] != old:
            raise ValueError('Edit does not match exact source text')
        if not isinstance(edit['reason'], str) or not edit['reason'].strip():
            raise ValueError('Edit needs a concrete reason')
        # Only punctuation/spacing may be newly authored. Lexical characters
        # must remain an ordered subsequence of the untouched source part.
        letters = lambda s: (c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))
        remaining = iter(letters(old))
        if any(not any(c == prior for prior in remaining) for c in letters(new)):
            raise ValueError('Review introduced new words or reordered source')
        part['text'] = new.strip()
        changes.append(edit['reason'])
    bubbles = updated['bubbles']
    for bubble in bubbles:
        bubble['parts'] = [part for part in bubble['parts'] if part['text']]
    updated['bubbles'] = [bubble for bubble in bubbles if bubble['parts']]
    for index, bubble in enumerate(updated['bubbles'], 1):
        bubble['index'] = index
    updated['bubble_count'] = len(updated['bubbles'])
    if not updated['bubble_count']:
        raise ValueError('Review cannot remove the complete visible reply')
    return updated, changes


async def review_expression_once(result, *, task, manuals, model_config, runner, deadline,
                                 usage_sink=None, final_check=False):
    """One deletion-only edit pass without tools or input edits.

    Failures retain the valid original and never count as reviewed output.
    """
    if not result.get('envelope') or not result.get('bubble_count'):
        return {'status': 'not_applicable'}
    original = result['envelope']
    record = {'status': 'pending', 'draft': original, 'draft_sha256': digest(original),
              'reasoning_effort': 'low'}
    remaining = deadline - time.monotonic()
    if remaining < 3:
        return {**record, 'status': 'skipped_deadline'}
    source = json.loads(original)
    data = {'sources': deepcopy(task), 'loaded_manuals': deepcopy(manuals),
            'expression_completion': EXPRESSION_COMPLETION, 'draft': source}
    started = time.monotonic()
    review = None
    interrupted = False
    try:
        review = await runner(json.dumps(data, ensure_ascii=False), model_config, {},
            system_prompt=EXPRESSION_REVIEW_WORKFLOW + ('\n'+EXPRESSION_FINAL_CHECK if final_check else ''),
            reasoning_effort=record['reasoning_effort'], max_tokens=8192,
            timeout_seconds=min(45, remaining), max_tool_calls=0)
        add_usage(result, review)
        record['raw_review'] = str(review.get('final_response') or '')
        record['llm_api_calls'] = review.get('llm_api_calls', 0)
        record['finish_reason'] = review.get('finish_reason')
        record['usage'] = review.get('usage', {})
        if review.get('finish_reason') != 'completed':
            raise ValueError('Expression review did not complete')
        candidate = json.loads(record['raw_review'])
        updated, changes = apply_edits(source, candidate)
        required = result.get('required_bubble_count')
        if type(required) is int and updated['bubble_count'] != required:
            raise ValueError('Review changed explicit bubble count')
        envelope, count = reply_envelope(json.dumps(updated, ensure_ascii=False))
        validated = json.loads(envelope)
        for key in set(source) - {'bubbles', 'bubble_count'}:
            if validated.get(key) != source[key]:
                raise ValueError('Review changed protected delivery metadata: ' + key)
        result['envelope'], result['bubble_count'] = envelope, count
        record.update(status='reviewed', changed=envelope != original, changes=changes,
                      final_sha256=digest(envelope))
    except BaseException as exc:
        if review is None:
            partial = getattr(exc, 'harness_usage', {}) or {}
            add_usage(result, partial)
            record['llm_api_calls'] = partial.get('llm_api_calls', 0)
            record['usage'] = partial.get('usage', {})
        record.update(status='failed_original_retained', error_type=type(exc).__name__, error=str(exc))
        if not isinstance(exc, Exception):
            interrupted = True
            raise
    finally:
        record['seconds'] = round(time.monotonic() - started, 3)
        if usage_sink:
            usage_sink({key: result.get(key) for key in
                        ('usage', 'llm_api_calls', 'tool_call_count', 'tool_trace', 'automatic_retries')}
                       | {'incomplete': interrupted})
    return record


async def review_expression(result, **options):
    """Two bounded passes: local edits, then a fresh check of the remaining text."""
    if not result.get('envelope') or not result.get('bubble_count'):
        return {'status': 'not_applicable'}
    original = result['envelope']
    passes = []
    for _ in range(3):
        completed = sum(p['status'] == 'reviewed' for p in passes)
        record = await review_expression_once(result, final_check=bool(completed), **options)
        passes.append(record)
        if record['status'] == 'skipped_deadline' or sum(p['status'] == 'reviewed' for p in passes) == 2:
            break
    return {'status': 'reviewed' if sum(p['status'] == 'reviewed' for p in passes) == 2
            else 'partial_review_original_or_prior_retained',
            'draft': original, 'draft_sha256': digest(original), 'passes': passes,
            'changed': result['envelope'] != original, 'final_sha256': digest(result['envelope']),
            'changes': [change for p in passes for change in p.get('changes', [])],
            'seconds': round(sum(p.get('seconds', 0) for p in passes), 3)}

"""Private invocation-local source parse data; never stores validation results."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading

try:
    from . import complete_ensemble_reference_v1 as source
except ImportError:
    import complete_ensemble_reference_v1 as source

_CURRENT = ContextVar('complete_occurrence_frame_source_preparation', default=None)


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


@contextmanager
def _scope():
    token = _CURRENT.set((_owner(), {}))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def _validation_invocation(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        with _scope():
            return function(*args, **kwargs)
    return invoke


def _prepared_structure(canonical):
    state = _CURRENT.get()
    # Child task inheritance must not share the parent's mutable parse data.
    cache = state[1] if state is not None and state[0] == _owner() else None
    if cache is None or type(canonical) is not bytes:
        return dict(projection=source.projection(canonical), descriptor=source.source_descriptor(canonical))
    if canonical not in cache:
        # Keep the original descriptor parser and all its source predicates.
        # Exceptions leave no entry; only successful parse data are retained.
        cache[canonical] = dict(projection=source.projection(canonical), descriptor=source.source_descriptor(canonical))
    return cache[canonical]

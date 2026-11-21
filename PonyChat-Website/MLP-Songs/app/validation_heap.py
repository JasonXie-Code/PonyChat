"""Release dead validation graphs without retaining or changing any authority."""
import gc
import sys

_TRIM = None
if sys.platform.startswith('linux'):
    import ctypes
    _TRIM = getattr(ctypes.CDLL(None), 'malloc_trim', None)
    if _TRIM is not None:
        _TRIM.argtypes = [ctypes.c_size_t]
        _TRIM.restype = ctypes.c_int


def trim_validation_heap():
    """Return unused large allocator arenas before the next proof graph."""
    gc.collect()
    if _TRIM is not None:
        _TRIM(0)

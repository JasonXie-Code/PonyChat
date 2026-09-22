"""Bounded process-local write journal; full disk reconciliation is the fallback."""
import os
import threading


class LogChanges:
    def __init__(self, capacity=4096):
        if capacity < 1:
            raise ValueError('capacity must be positive')
        self.capacity = capacity
        self.lock = threading.Lock()
        self.sequence = 0
        self.dropped_through = 0
        self.pending = {}

    def publish(self, path):
        path = os.path.abspath(os.fspath(path))
        key = os.path.normcase(path)
        with self.lock:
            self.sequence += 1
            self.pending.pop(key, None)
            self.pending[key] = (self.sequence, path)
            if len(self.pending) > self.capacity:
                oldest = next(iter(self.pending))
                sequence, _ = self.pending.pop(oldest)
                self.dropped_through = max(self.dropped_through, sequence)

    def since(self, cursor):
        # Each indexer keeps its own cursor. Snapshots never consume another
        # subscriber's changes; a later rewrite gets a strictly newer sequence.
        with self.lock:
            return (self.sequence,
                    [path for sequence, path in self.pending.values() if sequence > cursor],
                    cursor < self.dropped_through)


changes = LogChanges()

"""Compact dependency locators with fresh clocks, never cached proof results.

A warm scan checks the same complete vector as discovery. Directory entries
only avoid redundant path parsing/lstat calls; file clocks are sampled afresh.
Any mismatch sends the song through full dependency discovery and admission.
"""
import json
import os
import zlib


class DependencyScan:
    """Fresh samples for exactly one before OR after sweep, never both.

    Songs sharing a core file compare the same full current record. Directory
    enumeration only detects links and OMR membership; it supplies no clocks.
    The actual file/ChangeTime tuple still comes from the supplied fresh reader.
    No scanner is stored on a plan, catalog state, or another request.
    """
    def __init__(self, record):
        self.record = record
        self.parents, self.entries, self.sampled = {}, {}, {}

    def directory(self, path):
        if path not in self.entries:
            try:
                with os.scandir(path) as stream:
                    self.entries[path] = {entry.name: entry.is_symlink() for entry in stream}
            except FileNotFoundError:
                self.entries[path] = {}
        return self.entries[path]

    def current(self, path):
        if path not in self.sampled:
            parent, name = os.path.split(path)
            if self.directory(parent).get(name):
                resolved = os.path.realpath(path)
            else:
                if parent not in self.parents:
                    self.parents[parent] = os.path.realpath(parent)
                resolved = os.path.join(self.parents[parent], name)
            self.sampled[path] = self.record(path, resolved)
        return self.sampled[path]


class DependencyPlan:
    def __init__(self, context, snapshot, fingerprint):
        self.context = context
        self.fingerprint = fingerprint
        # Keep locators compact instead of retaining Python path/stat graphs.
        self.payload = zlib.compress(json.dumps(snapshot, ensure_ascii=True,
                                               separators=(',', ':')).encode('ascii'), 1)

    def matches(self, context, record, scan=None):
        if context != self.context or not self.fingerprint[-1]:
            return False
        scan = DependencyScan(record) if scan is None else scan
        if scan.record is not record:
            raise ValueError('Dependency scan belongs to a different current reader')
        roots, paths, directories, _ = json.loads(zlib.decompress(self.payload))

        for expected in (*roots, *paths):
            actual = scan.current(expected[0])
            wanted = (expected[0], expected[1],
                      tuple(expected[2]) if expected[2] is not None else None)
            if actual != wanted:
                return False
        for folder, expected in directories:
            members = []
            for name in scan.directory(folder):
                match = name.lower() if os.name == 'nt' else name
                if match.endswith(('.musicxml', '.mxl')):
                    members.append(os.path.join(folder, name))
            if sorted(members) != expected:
                return False
        return True

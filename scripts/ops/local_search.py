"""Run the migrated, pinned SearXNG installation with Waitress on Windows."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "var" / "services" / "searxng"
SOURCE = SERVICE / "source"


def windows_valkey_logging_compatibility():
    """Replace only Unix account lookup used in an optional Valkey error log.

    The migrated configuration disables Valkey. Its module still imports pwd
    unconditionally, preventing an otherwise portable JSON search API startup.
    Compile the pinned module with equivalent Windows log identification; keep
    the downloaded source byte-for-byte unchanged for migration verification.
    """
    if os.name != "nt":
        return
    filename = SOURCE / "searx" / "valkeydb.py"
    source = filename.read_text(encoding="utf-8")
    expected = "_pw = pwd.getpwuid(os.getuid())"
    if "import pwd\n" not in source or expected not in source:
        raise RuntimeError("SearXNG account-logging adapter needs review for this version")
    source = source.replace("import pwd\n", "import getpass\nimport types\n", 1)
    source = source.replace(
        expected,
        '_pw = types.SimpleNamespace(pw_name=getpass.getuser(), pw_uid="Windows")',
        1,
    )
    spec = importlib.util.spec_from_file_location("searx.valkeydb", filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, str(filename), "exec"), module.__dict__)


def main():
    os.environ["SEARXNG_SETTINGS_PATH"] = str(SERVICE / "settings.yml")
    os.environ["SEARXNG_DATA_PATH"] = str(SERVICE / "state")
    os.environ["XDG_CACHE_HOME"] = str(SERVICE / "state")
    os.environ["PYTHONUTF8"] = "1"
    os.chdir(SOURCE)
    sys.path.insert(0, str(SOURCE))
    windows_valkey_logging_compatibility()
    from searx.webapp import app
    from waitress import serve

    serve(app, host="127.0.0.1", port=18786, threads=4,
          channel_timeout=60, max_request_body_size=1024 * 1024)


if __name__ == "__main__":
    main()

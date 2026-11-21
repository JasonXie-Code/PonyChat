"""Runtime storage paths that must stay outside the source tree locally."""

from __future__ import annotations

import os


def _abs_path(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value))


def _local_data_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
    return os.path.join(base, "PonyChat")


def resolve_database_path(backend_dir: str) -> str:
    explicit = os.environ.get("PONYCHAT_DB_PATH")
    if explicit:
        return _abs_path(explicit)

    legacy_repo_db = os.path.join(backend_dir, "database", "ponychat.db")
    if os.name != "nt" and os.path.exists(legacy_repo_db):
        return os.path.abspath(legacy_repo_db)

    return os.path.join(_local_data_dir(), "ponychat.db")


def resolve_backup_dir(backend_dir: str, db_path: str | None = None) -> str:
    explicit = os.environ.get("PONYCHAT_BACKUP_DIR")
    if explicit:
        return _abs_path(explicit)

    legacy_repo_backups = os.path.join(backend_dir, "backups")
    if os.name != "nt" and os.path.isdir(legacy_repo_backups):
        return os.path.abspath(legacy_repo_backups)

    effective_db_path = db_path or resolve_database_path(backend_dir)
    return os.path.join(os.path.dirname(effective_db_path), "backups")


def resolve_mlp_vector_db_path(backend_dir: str) -> str:
    explicit = os.environ.get("PONYCHAT_MLP_VECTOR_DB_PATH") or os.environ.get(
        "MLP_VECTOR_DB_PATH"
    )
    if explicit:
        return _abs_path(explicit)

    legacy_repo_db = os.path.join(backend_dir, "data", "mlp", "mlp_vectors.db")
    if os.name != "nt" and os.path.exists(legacy_repo_db):
        return os.path.abspath(legacy_repo_db)

    return os.path.join(_local_data_dir(), "mlp_vectors.db")

"""Translate the three log-index path columns after the byte-exact DB migration."""
from __future__ import annotations

import json
import sqlite3

from migration_transport import ROOT, STATE


def main():
    receipt = json.loads((STATE / "final-database-receipt.json").read_text())
    assert receipt["integrity"] == "ok" and receipt["all_table_counts_match"]
    path = ROOT / "Backend" / "database" / "ponychat.db"
    old = "/opt/ponychat/"
    new = str(ROOT) + "\\"
    changes = {}
    with sqlite3.connect(path, timeout=60) as db:
        for table, column in [("llm_log_index", "log_file_path"),
                              ("llm_log_index_progress", "file_path"),
                              ("llm_log_index_errors", "file_path")]:
            before = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            cursor = db.execute(
                f"UPDATE {table} SET {column}=? || replace(substr({column},?), '/', char(92)) "
                f"WHERE {column} LIKE ?", (new, len(old) + 1, old + "%"))
            changes[table] = cursor.rowcount
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == before
        db.commit()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result = {"only_path_columns_changed": True, "row_counts_preserved": True,
              "integrity": "ok", "updated": changes, "old_root": old, "new_root": new}
    (STATE / "localized-database-receipt.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

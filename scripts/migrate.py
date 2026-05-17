"""Apply pending SQL migrations to .agent_log.db."""

import sqlite3
import time
from pathlib import Path

_DB_PATH         = Path(__file__).parents[1] / ".agent.db"
_MIGRATIONS_DIR  = Path(__file__).parents[1] / "migrations"


def migrate(db_path: Path = _DB_PATH) -> None:
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at REAL    NOT NULL
        )
    """)
    con.commit()

    applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}

    migrations = sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda p: int(p.stem.split("_")[0]))
    pending = [m for m in migrations if int(m.stem.split("_")[0]) not in applied]

    if not pending:
        print("nothing to migrate")
        return

    for path in pending:
        version = int(path.stem.split("_")[0])
        print(f"applying {path.name} ...")
        con.executescript(path.read_text(encoding="utf-8"))
        con.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", [version, time.time()])
        con.commit()
        print(f"  ✓ {path.name}")

    con.close()
    print("done")


if __name__ == "__main__":
    migrate()

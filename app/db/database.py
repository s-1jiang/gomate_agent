import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for migration in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                # executescript starts its own transaction; the version is committed with its DDL.
                if connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (migration.stem,)
                ).fetchone():
                    continue
                script = migration.read_text(encoding="utf-8")
                version = migration.stem.replace("'", "''")
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + f"\nINSERT INTO schema_migrations(version) VALUES ('{version}');\nCOMMIT;"
                )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    from app.core.config import Settings

    database = Database(Settings().database_path)
    database.migrate()
    print(f"Migrations applied: {database.path}")

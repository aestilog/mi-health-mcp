import sqlite3

from mi_fitness_mcp.storage import Database


def _sync_state_columns(db_path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}


def _create_legacy_db(db_path, rows):
    """手工建一个带 records_count 列的老库 sync_state 表。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_type TEXT NOT NULL UNIQUE,
                last_sync_at TIMESTAMP,
                last_record_timestamp TIMESTAMP,
                records_count INTEGER DEFAULT 0
            )
        """)
        conn.executemany(
            """
            INSERT INTO sync_state (data_type, last_sync_at, last_record_timestamp)
            VALUES (?, ?, ?)
            """,
            rows,
        )


LEGACY_ROWS = [
    ("daily_activity", "2026-10-01 08:00:00", "2026-10-01T07:59:00"),
    ("heart_rate", "2026-10-02 09:30:00", None),
    ("sleep", "2026-10-03 10:15:00", "2026-10-03T06:40:00"),
]


def test_new_database_has_no_records_count(tmp_path):
    db_path = tmp_path / "new.db"
    Database(db_path)

    assert "records_count" not in _sync_state_columns(db_path)


def test_legacy_database_drops_column_and_keeps_data(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path, LEGACY_ROWS)
    assert "records_count" in _sync_state_columns(db_path)

    Database(db_path)

    columns = _sync_state_columns(db_path)
    assert "records_count" not in columns
    assert columns == {"id", "data_type", "last_sync_at", "last_record_timestamp"}

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT data_type, last_sync_at, last_record_timestamp
            FROM sync_state ORDER BY id
            """
        ).fetchall()
    assert rows == LEGACY_ROWS


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path, LEGACY_ROWS)

    Database(db_path)
    Database(db_path)

    assert "records_count" not in _sync_state_columns(db_path)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sync_state").fetchone()[0]
    assert count == len(LEGACY_ROWS)


def test_reopening_new_database_is_safe(tmp_path):
    db_path = tmp_path / "new.db"
    Database(db_path)
    Database(db_path)

    assert "records_count" not in _sync_state_columns(db_path)

import sqlite3
from pathlib import Path

from vibe_rtts.config import DB_PATH


class HistoryStore:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
                    text TEXT NOT NULL,
                    language TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON transcriptions(timestamp DESC)
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(DB_PATH), check_same_thread=False)

    def save(self, text: str, language: str = None) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO transcriptions (text, language) VALUES (?, ?)",
                (text, language),
            )
            return cursor.lastrowid

    def get_all(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, text, language FROM transcriptions "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, row_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM transcriptions WHERE id = ?", (row_id,))

    def clear_all(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM transcriptions")

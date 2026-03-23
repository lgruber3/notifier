import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class DeduplicationStore:
    def __init__(self, db_path: str | Path = "data/seen.db"):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                item_id TEXT PRIMARY KEY,
                source TEXT,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def is_new(self, item_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row is None

    def mark_seen(self, item_id: str, source: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO seen (item_id, source) VALUES (?, ?)",
            (item_id, source),
        )
        self.conn.commit()

    def has_source(self, source: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE source = ? LIMIT 1", (source,)
        ).fetchone()
        return row is not None

    def cleanup(self, max_age_days: int = 30):
        self.conn.execute(
            "DELETE FROM seen WHERE seen_at < datetime('now', ?)",
            (f"-{max_age_days} days",),
        )
        self.conn.commit()
        logger.info(f"Cleaned up dedup entries older than {max_age_days} days")

    def close(self):
        self.conn.close()

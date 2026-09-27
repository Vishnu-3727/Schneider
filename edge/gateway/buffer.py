"""SQLite store-and-forward buffer for the edge gateway.

outbox       canonical records waiting for the backend, oldest first. The
             UNIQUE dedup_key (kind|machine|timestamp) makes re-delivered or
             retained MQTT messages a no-op locally; the backend dedups the
             same identity again.
dead_letter  inputs that can never be delivered as-is (malformed payload,
             unknown machine, schema rejection), kept with the reason.
             Nothing is silently dropped.
The file survives process restarts, so a gateway reboot during an API
outage loses nothing.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dead_letter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    raw TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delivered (
    dedup_key TEXT PRIMARY KEY,
    delivered_at TEXT NOT NULL
);
"""


class Buffer:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def enqueue(self, kind: str, key: str, record: dict) -> bool:
        """False when this record is already buffered or already delivered."""
        with self._lock:
            if self._db.execute("SELECT 1 FROM delivered WHERE dedup_key = ?", (key,)).fetchone():
                return False
            cur = self._db.execute(
                "INSERT OR IGNORE INTO outbox (kind, dedup_key, payload, created_at) "
                "VALUES (?, ?, ?, ?)", (kind, key, json.dumps(record), self._now()))
            return cur.rowcount == 1

    def dead_letter(self, kind: str, raw, reason: str) -> None:
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        with self._lock:
            self._db.execute("INSERT INTO dead_letter (kind, raw, reason, created_at) "
                             "VALUES (?, ?, ?, ?)", (kind, text, reason, self._now()))

    def oldest(self, kind: str, limit: int) -> list[tuple[int, str, dict]]:
        with self._lock:
            rows = self._db.execute("SELECT id, dedup_key, payload FROM outbox WHERE kind = ? "
                                    "ORDER BY id LIMIT ?", (kind, limit)).fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]

    def delivered(self, items: list[tuple[int, str]]) -> None:
        now = self._now()
        with self._lock:
            self._db.execute("BEGIN")
            for row_id, key in items:
                self._db.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
                self._db.execute("INSERT OR IGNORE INTO delivered VALUES (?, ?)", (key, now))
            self._db.execute("COMMIT")

    def reject(self, row_id: int, kind: str, record: dict, reason: str) -> None:
        with self._lock:
            self._db.execute("BEGIN")
            self._db.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
            self._db.execute("INSERT INTO dead_letter (kind, raw, reason, created_at) "
                             "VALUES (?, ?, ?, ?)", (kind, json.dumps(record), reason, self._now()))
            self._db.execute("COMMIT")

    def bump_attempts(self, ids: list[int]) -> None:
        with self._lock:
            self._db.executemany("UPDATE outbox SET attempts = attempts + 1 WHERE id = ?",
                                 [(i,) for i in ids])

    def counts(self) -> dict:
        with self._lock:
            q = lambda s: self._db.execute(s).fetchone()[0]
            return {"pending": q("SELECT COUNT(*) FROM outbox"),
                    "dead_letter": q("SELECT COUNT(*) FROM dead_letter"),
                    "delivered": q("SELECT COUNT(*) FROM delivered")}

    def dead_letters(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT kind, raw, reason FROM dead_letter ORDER BY id").fetchall()
        return [{"kind": r[0], "raw": r[1], "reason": r[2]} for r in rows]

    def close(self) -> None:
        self._db.close()

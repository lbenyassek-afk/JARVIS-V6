from __future__ import annotations

import sqlite3

from .config import APP_DIR
from .crypto import open_text, seal


def _connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(APP_DIR / "desktop_audit.sqlite3")
    database.execute(
        "CREATE TABLE IF NOT EXISTS actions ("
        "id INTEGER PRIMARY KEY, action TEXT NOT NULL, detail TEXT NOT NULL, "
        "status TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    return database


def record(action: str, detail: str, status: str) -> None:
    try:
        with _connect() as database:
            database.execute(
                "INSERT INTO actions(action,detail,status) VALUES (?,?,?)",
                (str(action)[:80], seal(str(detail)[:300]), str(status)[:40]),
            )
    except (OSError, sqlite3.Error):
        pass


def recent(limit: int = 30) -> list[tuple]:
    try:
        with _connect() as database:
            rows = database.execute(
                "SELECT created,action,detail,status FROM actions ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            return [(row[0], row[1], open_text(row[2]), row[3]) for row in rows]
    except (OSError, sqlite3.Error):
        return []

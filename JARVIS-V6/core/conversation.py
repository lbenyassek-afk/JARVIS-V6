from __future__ import annotations

import re
import sqlite3

from . import config
from .memory import sensitive
from .crypto import open_text, seal, encrypted


def _connect() -> sqlite3.Connection:
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(config.APP_DIR / "conversation.sqlite3")
    database.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    columns = {row[1] for row in database.execute("PRAGMA table_info(messages)")}
    if "scope" not in columns:
        database.execute("ALTER TABLE messages ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
    for row_id, content in database.execute(
            "SELECT id,content FROM messages WHERE content NOT LIKE 'J5E1:%'").fetchall():
        database.execute("UPDATE messages SET content=? WHERE id=?", (seal(content), row_id))
    return database


def _scope() -> str:
    value = str(config.load_config().get("assistant", {}).get("active_mode", "personal"))
    return value if value in ("personal", "school", "business") else "personal"


def _safe(role: str, content: str) -> bool:
    return role in ("user", "assistant") and bool(content.strip()) and not sensitive("chat", content)


def remember_exchange(user_text: str, answer: str) -> None:
    if "do not save this" in user_text.casefold():
        return
    rows = (("user", str(user_text)[:12_000]), ("assistant", str(answer)[:18_000]))
    try:
        with _connect() as database:
            for role, content in rows:
                if _safe(role, content):
                    database.execute(
                        "INSERT INTO messages(role,content,scope) VALUES (?,?,?)",
                        (role, seal(content), _scope()),
                    )
    except (OSError, sqlite3.Error):
        return


def recent_messages(limit: int = 24) -> list[dict]:
    limit = max(2, min(int(limit), 80))
    try:
        with _connect() as database:
            rows = database.execute(
                "SELECT id,role,content FROM messages WHERE scope IN (?, 'global') "
                "ORDER BY id DESC LIMIT ?", (_scope(), limit)
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    rows.reverse()
    return [{"id": row[0], "role": row[1], "content": open_text(row[2])} for row in rows]


def relevant_messages(query: str, recent_limit: int = 20, older_limit: int = 6) -> list[dict]:
    recent = recent_messages(recent_limit)
    recent_ids = {row["id"] for row in recent}
    words = {word for word in re.findall(r"[a-z0-9]{4,}", query.casefold()) if word not in {
        "this", "that", "with", "from", "have", "what", "when", "where", "would", "could"
    }}
    older = []
    if words:
        try:
            with _connect() as database:
                candidates = database.execute(
                    "SELECT id,role,content FROM messages WHERE scope IN (?, 'global') "
                    "ORDER BY id DESC LIMIT 500", (_scope(),)
                ).fetchall()
        except (OSError, sqlite3.Error):
            candidates = []
        scored = []
        for row in candidates:
            if row[0] in recent_ids:
                continue
            content = open_text(row[2])
            haystack = content.casefold()
            score = sum(1 for word in words if word in haystack)
            if score:
                scored.append((score, (row[0], row[1], content)))
        selected = [item[1] for item in sorted(scored, key=lambda item: (-item[0], -item[1][0]))[:older_limit]]
        selected.sort(key=lambda row: row[0])
        older = [{"id": row[0], "role": row[1], "content": row[2]} for row in selected]
    return [{"role": row["role"], "content": row["content"]} for row in older + recent]


def delete_history() -> None:
    try:
        with _connect() as database:
            database.execute("DELETE FROM messages")
    except (OSError, sqlite3.Error):
        return

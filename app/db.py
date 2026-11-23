import json
import os
import sqlite3
from datetime import UTC, datetime

DEFAULT_DB_PATH = "triagebot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _db_path() -> str:
    """Resuelve la ruta de SQLite desde DATABASE_URL en cada llamada (no al importar)."""
    url = os.environ.get("DATABASE_URL", "")
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return url[len(prefix):]
    return url or DEFAULT_DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    return ticket


def create_ticket(title: str, description: str, classification: dict) -> dict:
    now = _now()
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO tickets "
                "(title, description, category, priority, tags, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"]),
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_ticket(row)
    finally:
        conn.close()

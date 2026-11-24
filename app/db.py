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
    updated_at TEXT NOT NULL,
    status_changed_at TEXT NOT NULL
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
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Añade status_changed_at a bases creadas con el esquema antiguo (idempotente)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "status_changed_at" not in columns:
        with conn:
            conn.execute("ALTER TABLE tickets ADD COLUMN status_changed_at TEXT")
            conn.execute("UPDATE tickets SET status_changed_at = updated_at")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    return ticket


def list_tickets(
    category: str | None = None, priority: str | None = None, status: str | None = None
) -> list[dict]:
    """Tickets filtrados por igualdad exacta (None = sin filtro), los más recientes primero."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets "
            "WHERE (? IS NULL OR category = ?) "
            "AND (? IS NULL OR priority = ?) "
            "AND (? IS NULL OR status = ?) "
            "ORDER BY created_at DESC, id DESC",
            (category, category, priority, priority, status, status),
        ).fetchall()
        return [_row_to_ticket(row) for row in rows]
    finally:
        conn.close()


def get_ticket(ticket_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _row_to_ticket(row) if row else None
    finally:
        conn.close()


def update_ticket(ticket_id: int, status: str | None = None, priority: str | None = None) -> dict:
    """Actualiza status y/o priority. status_changed_at solo cambia si el estado cambia."""
    now = _now()
    conn = get_conn()
    try:
        with conn:
            current = conn.execute(
                "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
            if status is not None and status != current["status"]:
                conn.execute(
                    "UPDATE tickets SET status = ?, status_changed_at = ? WHERE id = ?",
                    (status, now, ticket_id),
                )
            if priority is not None:
                conn.execute(
                    "UPDATE tickets SET priority = ? WHERE id = ?", (priority, ticket_id)
                )
            conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id))
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _row_to_ticket(row)
    finally:
        conn.close()


def create_ticket(title: str, description: str, classification: dict) -> dict:
    now = _now()
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO tickets "
                "(title, description, category, priority, tags, status, created_at, updated_at, "
                "status_changed_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"]),
                    now,
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_ticket(row)
    finally:
        conn.close()

import json
import os
import sqlite3
from datetime import UTC, datetime

from app.models import CATEGORY_ORDER, ISO_FORMAT, PRIORITY_ORDER, STATUS_ORDER, compute_due_at

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


def now_iso() -> str:
    """Hora actual en UTC con el mismo formato que se guarda en la base."""
    return datetime.now(UTC).strftime(ISO_FORMAT)


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    # Derivado, no almacenado (SPEC §4): sigue a la prioridad actual.
    ticket["due_at"] = compute_due_at(ticket["created_at"], ticket["priority"])
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


def _counts(rows: list[sqlite3.Row], keys: tuple[str, ...]) -> dict[str, int]:
    """Todas las claves del enum en orden fijo, con 0 si no hay tickets de ese valor."""
    found = {row[0]: row[1] for row in rows}
    return {key: found.get(key, 0) for key in keys}


def ticket_stats() -> dict:
    """Total de tickets y conteos por categoría, prioridad y estado."""
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        by_category = conn.execute(
            "SELECT category, COUNT(*) FROM tickets GROUP BY category"
        ).fetchall()
        by_priority = conn.execute(
            "SELECT priority, COUNT(*) FROM tickets GROUP BY priority"
        ).fetchall()
        by_status = conn.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status").fetchall()
    finally:
        conn.close()
    return {
        "total": total,
        "by_category": _counts(by_category, CATEGORY_ORDER),
        "by_priority": _counts(by_priority, PRIORITY_ORDER),
        "by_status": _counts(by_status, STATUS_ORDER),
    }


def get_ticket(ticket_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _row_to_ticket(row) if row else None
    finally:
        conn.close()


def update_ticket(ticket_id: int, status: str | None = None, priority: str | None = None) -> dict:
    """Actualiza status y/o priority. status_changed_at solo cambia si el estado cambia."""
    now = now_iso()
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
    now = now_iso()
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

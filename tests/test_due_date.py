"""Fecha límite (`due_at`) calculada a partir de la prioridad (SPEC §4, «Fecha límite»)."""

from datetime import UTC, datetime, timedelta

import pytest

from app import db
from app.models import ISO_FORMAT, compute_due_at


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def set_row(ticket_id: int, **fields):
    """Cambia columnas directamente en la base (aún no hay PATCH)."""
    conn = db.get_conn()
    try:
        with conn:
            for column, value in fields.items():
                conn.execute(f"UPDATE tickets SET {column} = ? WHERE id = ?", (value, ticket_id))
    finally:
        conn.close()


def iso(moment: datetime) -> str:
    return moment.strftime(ISO_FORMAT)


def table_html(client) -> str:
    """Solo la lista de tickets: el resto del tablero (p. ej. la tarjeta «Vencidos») no cuenta."""
    return client.get("/").text.split('id="tickets-table-body"', 1)[1]


# --- compute_due_at ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        ("P1", "2026-06-30T09:30:00Z"),
        ("P2", "2026-07-02T09:30:00Z"),
        ("P3", "2026-07-06T09:30:00Z"),
    ],
)
def test_due_at_by_priority(priority, expected):
    assert compute_due_at("2026-06-29T09:30:00Z", priority) == expected


def test_due_at_crosses_month_and_year():
    assert compute_due_at("2026-02-27T12:00:00Z", "P2") == "2026-03-02T12:00:00Z"
    assert compute_due_at("2026-12-31T23:59:59Z", "P1") == "2027-01-01T23:59:59Z"


def test_due_at_uses_natural_hours_over_weekend():
    friday_evening = "2026-11-27T18:00:00Z"  # viernes
    assert compute_due_at(friday_evening, "P1") == "2026-11-28T18:00:00Z"  # sábado


def test_unknown_priority_uses_the_most_lenient_deadline():
    assert compute_due_at("2026-06-29T09:30:00Z", "P9") == "2026-07-06T09:30:00Z"


# --- API --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("priority", "sla"),
    [("P1", timedelta(hours=24)), ("P2", timedelta(hours=72)), ("P3", timedelta(days=7))],
)
def test_post_returns_due_at_from_priority(create_ticket, priority, sla):
    ticket = create_ticket(priority=priority)

    assert ticket["due_at"].endswith("Z")
    assert parse(ticket["due_at"]) - parse(ticket["created_at"]) == sla


def test_due_at_follows_current_priority_from_creation(create_ticket, client):
    ticket = create_ticket(priority="P3")
    set_row(ticket["id"], priority="P1")

    stored = db.list_tickets()[0]

    assert stored["created_at"] == ticket["created_at"]
    assert parse(stored["due_at"]) - parse(stored["created_at"]) == timedelta(hours=24)


def test_due_at_is_not_stored_in_the_database(client):
    conn = db.get_conn()
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    finally:
        conn.close()

    assert "due_at" not in columns


# --- Tablero ----------------------------------------------------------------------


def test_board_has_due_date_column(create_ticket, client):
    ticket = create_ticket(priority="P2")
    html = client.get("/").text

    assert "Fecha límite" in html
    assert f"{ticket['due_at'][:10]} {ticket['due_at'][11:16]}" in html


def test_new_ticket_is_not_overdue(create_ticket, client):
    create_ticket(priority="P1")
    assert "Vencido" not in table_html(client)


def test_past_due_open_ticket_is_overdue(create_ticket, client):
    ticket = create_ticket(priority="P1")
    set_row(ticket["id"], created_at=iso(datetime.now(UTC) - timedelta(days=3)))

    assert "Vencido" in table_html(client)


def test_closed_ticket_is_never_overdue(create_ticket, client):
    ticket = create_ticket(priority="P1")
    set_row(
        ticket["id"],
        created_at=iso(datetime.now(UTC) - timedelta(days=3)),
        status="closed",
    )

    assert "Vencido" not in table_html(client)


def test_htmx_fragment_includes_due_date(create_ticket, client, set_classification):
    set_classification(priority="P2")
    response = client.post(
        "/tickets",
        json={"title": "Desde el formulario", "description": "descripción"},
        headers={"HX-Request": "true"},
    )
    ticket = db.list_tickets()[0]

    assert response.status_code == 201
    assert f"{ticket['due_at'][:10]} {ticket['due_at'][11:16]}" in response.text
    assert 'colspan="8"' not in response.text  # hay filas, no el estado vacío

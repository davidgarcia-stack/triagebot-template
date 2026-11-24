"""Ciclo de vida del ticket: transiciones, reapertura y tiempo en el estado actual."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app import db
from app.main import since
from app.models import is_valid_transition


def patch_status(client, ticket_id, status):
    return client.patch(f"/tickets/{ticket_id}", json={"status": status})


def test_full_forward_flow(create_ticket, client):
    ticket = create_ticket()

    for status in ("in_progress", "resolved", "closed"):
        response = patch_status(client, ticket["id"], status)
        assert response.status_code == 200
        assert response.json()["status"] == status


@pytest.mark.parametrize("from_status", ["resolved", "closed"])
def test_reopen_from_resolved_or_closed(create_ticket, client, from_status):
    ticket = create_ticket()
    patch_status(client, ticket["id"], from_status)

    response = patch_status(client, ticket["id"], "open")

    assert response.status_code == 200
    assert response.json()["status"] == "open"


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("closed", "in_progress"),
        ("resolved", "in_progress"),
        ("closed", "resolved"),
        ("in_progress", "open"),
    ],
)
def test_backwards_transitions_are_rejected(create_ticket, client, from_status, to_status):
    ticket = create_ticket()
    patch_status(client, ticket["id"], from_status)

    response = patch_status(client, ticket["id"], to_status)

    assert response.status_code == 422
    assert "Transición no permitida" in response.json()["detail"]
    assert db.get_ticket(ticket["id"])["status"] == from_status


def test_status_changed_at_starts_at_creation(create_ticket):
    ticket = create_ticket()

    assert ticket["status_changed_at"] == ticket["created_at"]


def _backdate(ticket_id):
    """Mueve status_changed_at al pasado para detectar si se renueva."""
    old = "2020-01-01T00:00:00Z"
    conn = db.get_conn()
    with conn:
        conn.execute("UPDATE tickets SET status_changed_at = ? WHERE id = ?", (old, ticket_id))
    conn.close()
    return old


def test_status_changed_at_is_renewed_on_status_change(create_ticket, client):
    ticket = create_ticket()
    old = _backdate(ticket["id"])

    updated = patch_status(client, ticket["id"], "in_progress").json()

    assert updated["status"] == "in_progress"
    assert not updated["status_changed_at"].startswith(old[:10])


def test_status_changed_at_is_kept_on_priority_change_or_same_status(create_ticket, client):
    ticket = create_ticket()
    _backdate(ticket["id"])

    by_priority = client.patch(f"/tickets/{ticket['id']}", json={"priority": "P3"}).json()
    same_status = patch_status(client, ticket["id"], "open").json()

    assert by_priority["status_changed_at"].startswith("2020-01-01")
    assert same_status["status_changed_at"].startswith("2020-01-01")


def test_filter_by_resolved(create_ticket, client):
    resolved = create_ticket(title="Resuelto")
    create_ticket(title="Abierto")
    patch_status(client, resolved["id"], "resolved")

    listed = client.get("/tickets", params={"status": "resolved"}).json()

    assert [t["id"] for t in listed] == [resolved["id"]]


def test_empty_patch_and_unknown_fields_are_rejected(create_ticket, client):
    ticket = create_ticket()

    assert client.patch(f"/tickets/{ticket['id']}", json={}).status_code == 422
    assert client.patch(f"/tickets/{ticket['id']}", json={"title": "x"}).status_code == 422


def test_htmx_patch_returns_row_with_reopen_button(create_ticket, client):
    ticket = create_ticket()

    response = client.patch(
        f"/tickets/{ticket['id']}", json={"status": "resolved"}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert "<tr" in response.text and "<table" not in response.text
    assert f'id="ticket-{ticket["id"]}"' in response.text
    assert "Reabrir" in response.text
    assert "Resuelto" in response.text


def test_board_shows_time_in_state(create_ticket, client):
    create_ticket()

    html = client.get("/").text

    assert "En este estado" in html
    assert "hace un momento" in html


def test_is_valid_transition_rules():
    assert is_valid_transition("open", "closed")
    assert is_valid_transition("in_progress", "in_progress")
    assert is_valid_transition("open", "open")
    assert is_valid_transition("closed", "open")
    assert not is_valid_transition("in_progress", "open")


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=30), "hace un momento"),
        (timedelta(minutes=5), "hace 5 min"),
        (timedelta(hours=3), "hace 3 h"),
        (timedelta(days=1), "hace 1 día"),
        (timedelta(days=4, hours=2), "hace 4 días"),
    ],
)
def test_since_filter(delta, expected):
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    then = (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert since(then, now=now) == expected


def test_old_database_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
        "description TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL, "
        "tags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tickets (title, description, category, priority, created_at, updated_at) "
        "VALUES ('t', 'd', 'bug', 'P1', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")

    [ticket] = db.list_tickets()

    assert ticket["status_changed_at"] == "2026-01-02T00:00:00Z"

"""Tests derived from SPEC.md section 6 (minimal frontend)."""

import re


def test_index_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_index_has_creation_form(client):
    html = client.get("/").text.lower()

    assert "<form" in html
    assert "title" in html
    assert "description" in html


def test_index_has_filters_for_category_priority_and_status(client):
    html = client.get("/").text

    for name in ("category", "priority", "status"):
        assert re.search(rf'name="{name}"', html), f"missing filter control for {name}"


def test_index_loads_htmx_and_tailwind_from_cdn(client):
    html = client.get("/").text.lower()

    assert "htmx" in html
    assert "tailwind" in html


def test_created_ticket_is_rendered_in_board(client, create_ticket):
    create_ticket(title="Ticket visible en el tablero", category="urgent", priority="P1")

    html = client.get("/").text

    assert "Ticket visible en el tablero" in html


def test_tickets_endpoint_is_json_not_html(client, create_ticket):
    create_ticket()

    response = client.get("/tickets")

    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), list)

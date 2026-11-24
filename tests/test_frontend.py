import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def add(title, category="bug", priority="P1", tags=None):
    return db.create_ticket(
        title, "descripción", {"category": category, "priority": priority, "tags": tags or []}
    )


def test_board_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "TriageBot" in response.text


def test_empty_board_shows_empty_state(client):
    assert "Todavía no hay tickets" in client.get("/").text


def test_board_shows_every_column_of_a_ticket(client):
    ticket = add("La VPN no conecta", "urgent", "P1", ["vpn", "login"])
    html = client.get("/").text

    assert f"#{ticket['id']}" in html
    assert "La VPN no conecta" in html
    assert ">urgent<" in html
    assert ">P1<" in html
    assert ">vpn<" in html and ">login<" in html
    assert "Abierto" in html
    assert ticket["created_at"][:10] in html
    assert "Todavía no hay tickets" not in html


def test_category_and_priority_have_distinct_colors(client):
    add("a", "bug", "P1")
    add("b", "feature_request", "P3")
    html = client.get("/").text

    assert "bg-rose-100" in html  # bug
    assert "bg-sky-100" in html  # feature_request
    assert "bg-red-600" in html  # P1
    assert "bg-emerald-100" in html  # P3


def test_newest_ticket_comes_first(client):
    add("primero")
    add("segundo")
    html = client.get("/").text
    assert html.index("segundo") < html.index("primero")


def test_ticket_without_tags_shows_dash(client):
    add("sin tags", tags=[])
    assert "—" in client.get("/").text


def test_user_content_is_escaped(client):
    add("<script>alert(1)</script>", tags=["<img src=x>"])
    html = client.get("/").text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x>" not in html

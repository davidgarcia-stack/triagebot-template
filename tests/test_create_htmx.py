import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

HTMX = {"HX-Request": "true"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P1", "tags": ["vpn"]},
    )
    return TestClient(app)


def payload(title="Nuevo ticket"):
    return {"title": title, "description": "descripción"}


def test_htmx_post_returns_html_rows_not_json(client):
    response = client.post("/tickets", json=payload(), headers=HTMX)

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["vary"] == "HX-Request"
    assert "Nuevo ticket" in response.text
    assert "<tr" in response.text
    # Es un fragmento para el <tbody>: ni página ni tabla completas, y nada de JSON.
    assert "<table" not in response.text and "<html" not in response.text
    assert '"id"' not in response.text and '"title"' not in response.text


def test_htmx_post_returns_every_ticket_newest_first(client):
    db.create_ticket("Viejo", "d", {"category": "question", "priority": "P3", "tags": []})

    html = client.post("/tickets", json=payload("Recién creado"), headers=HTMX).text

    assert html.count("<tr") == 2
    assert html.index("Recién creado") < html.index("Viejo")


def test_post_without_htmx_header_still_returns_json(client):
    response = client.post("/tickets", json=payload())

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data["title"] == "Nuevo ticket"
    assert data["category"] == "bug" and data["priority"] == "P1"
    assert data["tags"] == ["vpn"] and data["status"] == "open"


def test_htmx_post_keeps_validation(client):
    response = client.post("/tickets", json={"title": "   ", "description": "x"}, headers=HTMX)
    assert response.status_code == 422


def test_htmx_fragment_escapes_user_content(client):
    html = client.post("/tickets", json=payload("<script>alert(1)</script>"), headers=HTMX).text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

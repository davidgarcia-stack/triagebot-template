import pytest
from fastapi.testclient import TestClient

from app.main import app

VALID_DESCRIPTION = "Descripción válida del problema"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with an isolated SQLite database."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


@pytest.fixture()
def set_classification(monkeypatch):
    """Make the classifier return a fixed classification for every ticket."""

    def _set(category="bug", priority="P1", tags=None):
        result = {
            "category": category,
            "priority": priority,
            "tags": tags if tags is not None else [],
        }
        monkeypatch.setattr(
            "app.classifier.classify_ticket", lambda title, description: dict(result)
        )

    _set()
    return _set


@pytest.fixture()
def create_ticket(client, set_classification):
    """Create a ticket through the API and return the response JSON."""

    def _create(title="Ticket de prueba", description=VALID_DESCRIPTION, **classification):
        if classification:
            set_classification(**classification)
        response = client.post("/tickets", json={"title": title, "description": description})
        assert response.status_code == 201, response.text
        return response.json()

    return _create

"""Tests derived from SPEC.md sections 2 and 4 (data model and HTTP API)."""

from datetime import datetime

import pytest

VALID_DESCRIPTION = "Descripción válida del problema"

TICKET_FIELDS = {
    "id",
    "title",
    "description",
    "category",
    "priority",
    "tags",
    "status",
    "created_at",
    "updated_at",
}


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_created_ticket_has_all_model_fields_and_open_status(client, create_ticket):
    ticket = create_ticket(category="bug", priority="P1", tags=["login"])

    assert TICKET_FIELDS <= set(ticket)
    assert ticket["status"] == "open"
    assert parse_datetime(ticket["created_at"]) <= parse_datetime(ticket["updated_at"])


def test_ticket_ids_are_unique_and_increasing(create_ticket):
    first = create_ticket(title="Primero")
    second = create_ticket(title="Segundo")

    assert second["id"] > first["id"]


def test_title_and_description_are_trimmed(create_ticket):
    ticket = create_ticket(title="  Con espacios  ", description="  Descripción  ")

    assert ticket["title"] == "Con espacios"
    assert ticket["description"] == "Descripción"


@pytest.mark.parametrize(
    ("title_length", "description_length"),
    [(1, 1), (200, 5000)],
)
def test_boundary_lengths_are_accepted(
    client, set_classification, title_length, description_length
):
    response = client.post(
        "/tickets",
        json={"title": "t" * title_length, "description": "d" * description_length},
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {"description": VALID_DESCRIPTION},
        {"title": "Título válido"},
        {},
        {"title": "   ", "description": VALID_DESCRIPTION},
        {"title": "Título válido", "description": "   \n\t "},
        {"title": "x" * 201, "description": VALID_DESCRIPTION},
        {"title": "Título válido", "description": "x" * 5001},
    ],
)
def test_post_ticket_rejects_invalid_payloads(client, set_classification, payload):
    response = client.post("/tickets", json=payload)

    assert response.status_code == 422


def test_invalid_post_does_not_create_a_ticket(client, set_classification):
    client.post("/tickets", json={"title": "", "description": VALID_DESCRIPTION})

    assert client.get("/tickets").json() == []


def test_list_is_empty_when_there_are_no_tickets(client):
    response = client.get("/tickets")

    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_same_shape_as_post(create_ticket, client):
    created = create_ticket(category="question", priority="P3", tags=["faq"])

    listed = client.get("/tickets").json()

    assert listed == [created]


def test_filters_by_each_field_separately(create_ticket, client):
    bug = create_ticket(title="Bug", category="bug", priority="P1")
    feature = create_ticket(title="Feature", category="feature_request", priority="P2")
    question = create_ticket(title="Pregunta", category="question", priority="P3")
    client.patch(f"/tickets/{question['id']}", json={"status": "closed"})

    def ids(**params):
        return {t["id"] for t in client.get("/tickets", params=params).json()}

    assert ids(category="bug") == {bug["id"]}
    assert ids(category="feature_request") == {feature["id"]}
    assert ids(priority="P3") == {question["id"]}
    assert ids(status="closed") == {question["id"]}
    assert ids(status="open") == {bug["id"], feature["id"]}


def test_filters_combine_with_and_semantics(create_ticket, client):
    create_ticket(title="A", category="bug", priority="P1")
    target = create_ticket(title="B", category="bug", priority="P2")
    create_ticket(title="C", category="urgent", priority="P2")

    response = client.get("/tickets", params={"category": "bug", "priority": "P2"})

    assert [t["id"] for t in response.json()] == [target["id"]]


def test_filter_without_matches_returns_empty_list(create_ticket, client):
    create_ticket(category="bug")

    response = client.get("/tickets", params={"category": "urgent"})

    assert response.status_code == 200
    assert response.json() == []


def test_patch_only_status(create_ticket, client):
    ticket = create_ticket(priority="P1")

    response = client.patch(f"/tickets/{ticket['id']}", json={"status": "closed"})

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["priority"] == "P1"


def test_patch_only_priority(create_ticket, client):
    ticket = create_ticket(priority="P1")

    response = client.patch(f"/tickets/{ticket['id']}", json={"priority": "P3"})

    assert response.status_code == 200
    assert response.json()["priority"] == "P3"
    assert response.json()["status"] == "open"


def test_patch_updates_updated_at_but_not_created_at(create_ticket, client):
    ticket = create_ticket()

    patched = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"}).json()

    assert patched["created_at"] == ticket["created_at"]
    assert parse_datetime(patched["updated_at"]) >= parse_datetime(ticket["updated_at"])


def test_patch_is_persisted(create_ticket, client):
    ticket = create_ticket()
    client.patch(f"/tickets/{ticket['id']}", json={"status": "closed", "priority": "P3"})

    stored = client.get("/tickets").json()[0]

    assert stored["status"] == "closed"
    assert stored["priority"] == "P3"


def test_patch_unknown_ticket_returns_404(client):
    response = client.patch("/tickets/9999", json={"status": "closed"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "done"},
        {"status": "OPEN"},
        {"priority": "P4"},
        {"priority": "p1"},
    ],
)
def test_patch_rejects_values_outside_enum(create_ticket, client, payload):
    ticket = create_ticket()

    response = client.patch(f"/tickets/{ticket['id']}", json=payload)

    assert response.status_code == 422


def test_patch_cannot_change_immutable_fields(create_ticket, client):
    ticket = create_ticket(title="Original", category="bug")

    client.patch(
        f"/tickets/{ticket['id']}",
        json={"title": "Cambiado", "category": "urgent", "status": "closed"},
    )

    stored = client.get("/tickets").json()[0]
    assert stored["title"] == "Original"
    assert stored["category"] == "bug"


def test_classifier_failure_still_returns_valid_ticket_shape(client, monkeypatch):
    def broken(title, description):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.classifier.classify_ticket", broken)

    response = client.post("/tickets", json={"title": "Algo", "description": VALID_DESCRIPTION})

    assert response.status_code == 201
    assert TICKET_FIELDS <= set(response.json())

"""GET /tickets/stats: conteos totales, por categoría, prioridad y estado."""

EMPTY = {
    "total": 0,
    "by_category": {"bug": 0, "feature_request": 0, "question": 0, "urgent": 0},
    "by_priority": {"P1": 0, "P2": 0, "P3": 0},
    "by_status": {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0},
}


def test_stats_on_empty_database_has_every_key_at_zero(client):
    response = client.get("/tickets/stats")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == EMPTY


def test_stats_counts_by_category_priority_and_status(create_ticket, client):
    create_ticket(category="bug", priority="P1")
    create_ticket(category="bug", priority="P2")
    question = create_ticket(category="question", priority="P3")
    urgent = create_ticket(category="urgent", priority="P1")
    client.patch(f"/tickets/{question['id']}", json={"status": "resolved"})
    client.patch(f"/tickets/{urgent['id']}", json={"status": "in_progress"})

    stats = client.get("/tickets/stats").json()

    assert stats == {
        "total": 4,
        "by_category": {"bug": 2, "feature_request": 0, "question": 1, "urgent": 1},
        "by_priority": {"P1": 2, "P2": 1, "P3": 1},
        "by_status": {"open": 2, "in_progress": 1, "resolved": 1, "closed": 0},
    }


def test_stats_keys_keep_a_fixed_order(create_ticket, client):
    create_ticket(category="urgent", priority="P3")

    stats = client.get("/tickets/stats").json()

    assert list(stats["by_category"]) == ["bug", "feature_request", "question", "urgent"]
    assert list(stats["by_priority"]) == ["P1", "P2", "P3"]
    assert list(stats["by_status"]) == ["open", "in_progress", "resolved", "closed"]


def test_stats_counts_follow_priority_changes(create_ticket, client):
    ticket = create_ticket(priority="P1")
    client.patch(f"/tickets/{ticket['id']}", json={"priority": "P3"})

    assert client.get("/tickets/stats").json()["by_priority"] == {"P1": 0, "P2": 0, "P3": 1}

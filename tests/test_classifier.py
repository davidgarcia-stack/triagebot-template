import pytest

from app import classifier

FALLBACK = {"category": "question", "priority": "P3", "tags": []}


class FakeClient:
    """Imita client.chat.completions.create(...) devolviendo/lanzando lo que se le indique."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        message = type("Msg", (), {"content": outcome})()
        return type("Resp", (), {"choices": [type("Choice", (), {"message": message})()]})()


def use_client(monkeypatch, client):
    monkeypatch.setattr(classifier, "_get_client", lambda: client)
    return client


def classify():
    return classifier.classify_ticket("La VPN no conecta", "Authentication failed")


def test_valid_response_is_returned(monkeypatch):
    use_client(
        monkeypatch,
        FakeClient('{"category": "bug", "priority": "P1", "tags": ["vpn", "login"]}'),
    )
    assert classify() == {"category": "bug", "priority": "P1", "tags": ["vpn", "login"]}


def test_json_inside_markdown_fences_is_accepted(monkeypatch):
    use_client(
        monkeypatch,
        FakeClient('```json\n{"category": "urgent", "priority": "P1", "tags": []}\n```'),
    )
    assert classify() == {"category": "urgent", "priority": "P1", "tags": []}


@pytest.mark.parametrize(
    "raw",
    [
        '{"category": "URGENT", "priority": "P1", "tags": []}',
        '{"category": "outage", "priority": "P1", "tags": []}',
        '{"category": "bug", "priority": "P4", "tags": []}',
        '{"category": "bug", "priority": "p1", "tags": []}',
        '{"category": "bug", "priority": "P1", "tags": "vpn"}',
        '{"category": "bug", "priority": "P1"}',
        "esto no es json",
        "[1, 2, 3]",
        "",
        None,
    ],
)
def test_invalid_output_falls_back_without_retry(monkeypatch, raw):
    client = use_client(monkeypatch, FakeClient(raw))
    assert classify() == FALLBACK
    assert client.calls == 1  # respuesta recibida pero inválida: no se reintenta


def test_no_api_key_falls_back_without_calling_the_network(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(classifier, "load_dotenv", lambda: None)
    assert classify() == FALLBACK


def test_one_retry_then_success(monkeypatch):
    client = use_client(
        monkeypatch,
        FakeClient(
            RuntimeError("timeout"),
            '{"category": "question", "priority": "P2", "tags": ["vpn"]}',
        ),
    )
    assert classify() == {"category": "question", "priority": "P2", "tags": ["vpn"]}
    assert client.calls == 2


def test_two_failures_fall_back_and_never_call_a_third_time(monkeypatch):
    client = use_client(
        monkeypatch, FakeClient(RuntimeError("a"), RuntimeError("b"), RuntimeError("c"))
    )
    assert classify() == FALLBACK
    assert client.calls == 2


def test_tags_are_normalized(monkeypatch):
    use_client(
        monkeypatch,
        FakeClient(
            '{"category": "bug", "priority": "P2", "tags": '
            '["VPN", " vpn ", "Login", "", 7, "a", "b", "c", "d", "e"]}'
        ),
    )
    assert classify()["tags"] == ["vpn", "login", "a", "b", "c"]


def test_fallback_is_not_shared_between_calls(monkeypatch):
    use_client(monkeypatch, FakeClient("x", "y"))
    first = classify()
    first["tags"].append("mutated")
    assert classify() == FALLBACK
    assert classifier.FALLBACK_CLASSIFICATION["tags"] == []

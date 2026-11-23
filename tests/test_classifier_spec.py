"""Tests derived from SPEC.md section 5 (AI classifier).

The OpenAI SDK is always replaced by a fake client: no network, no real API key.
"""

import json
from types import SimpleNamespace

import pytest

from app import classifier

FALLBACK = {"category": "question", "priority": "P3", "tags": []}


class FakeOpenAI:
    """Stand-in for ``openai.OpenAI`` that replays scripted responses or exceptions."""

    init_kwargs: dict = {}
    calls: list = []
    script: list = []

    def __init__(self, *args, **kwargs):
        type(self).init_kwargs = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *args, **kwargs):
        type(self).calls.append(kwargs)
        step = type(self).script.pop(0) if type(self).script else RuntimeError("no more script")
        if isinstance(step, Exception):
            raise step
        message = SimpleNamespace(content=step)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture()
def fake_llm(monkeypatch):
    """Install FakeOpenAI wherever the classifier might look it up."""
    FakeOpenAI.init_kwargs = {}
    FakeOpenAI.calls = []
    FakeOpenAI.script = []
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr("app.classifier.OpenAI", FakeOpenAI, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")

    def _script(*steps):
        FakeOpenAI.script = list(steps)
        return FakeOpenAI

    return _script


def llm_json(category="bug", priority="P1", tags=None):
    return json.dumps(
        {
            "category": category,
            "priority": priority,
            "tags": tags if tags is not None else ["login"],
        }
    )


def test_valid_llm_response_is_returned(fake_llm):
    fake_llm(llm_json("feature_request", "P2", ["export", "pdf"]))

    result = classifier.classify_ticket("Exportar", "Quiero exportar a PDF")

    assert result == {"category": "feature_request", "priority": "P2", "tags": ["export", "pdf"]}


@pytest.mark.parametrize(
    "bad_content",
    [
        llm_json(category="URGENT"),
        llm_json(category="Bug"),
        llm_json(category="complaint"),
        llm_json(priority="P4"),
        llm_json(priority="p1"),
        llm_json(priority="high"),
        json.dumps({"category": "bug", "priority": "P1", "tags": "login"}),
        json.dumps({"category": "bug", "priority": "P1"}),
        json.dumps({"category": "bug"}),
        json.dumps(["bug", "P1"]),
        "not json at all",
        "{broken json",
        "",
        None,
    ],
)
def test_invalid_llm_output_uses_fallback(fake_llm, bad_content):
    fake_llm(bad_content)

    assert classifier.classify_ticket("Título", "Descripción") == FALLBACK


def test_fallback_constant_matches_spec():
    assert classifier.FALLBACK_CLASSIFICATION == FALLBACK


def test_one_retry_recovers_from_a_single_failure(fake_llm):
    fake_llm(ConnectionError("boom"), llm_json("bug", "P1", ["retry"]))

    result = classifier.classify_ticket("Título", "Descripción")

    assert result == {"category": "bug", "priority": "P1", "tags": ["retry"]}
    assert len(FakeOpenAI.calls) == 2


def test_at_most_one_retry_then_fallback(fake_llm):
    fake_llm(
        ConnectionError("first"),
        ConnectionError("second"),
        llm_json("bug", "P1"),  # must never be reached
    )

    result = classifier.classify_ticket("Título", "Descripción")

    assert result == FALLBACK
    assert len(FakeOpenAI.calls) <= 2


@pytest.mark.parametrize("error", [RuntimeError("x"), TimeoutError("x"), ValueError("x")])
def test_sdk_exceptions_never_propagate(fake_llm, error):
    fake_llm(error, error)

    assert classifier.classify_ticket("Título", "Descripción") == FALLBACK


def test_missing_api_key_does_not_raise(fake_llm, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake_llm(RuntimeError("no key"), RuntimeError("no key"))

    assert classifier.classify_ticket("Título", "Descripción") == FALLBACK


def test_llm_is_called_with_openrouter_config(fake_llm):
    fake_llm(llm_json())

    classifier.classify_ticket("Título", "Descripción")

    assert FakeOpenAI.init_kwargs.get("base_url") == "https://openrouter.ai/api/v1"
    assert FakeOpenAI.init_kwargs.get("api_key") == "test-key-not-real"
    assert FakeOpenAI.calls[0].get("model") == "openai/gpt-oss-120b"


def test_ticket_text_is_sent_to_the_llm(fake_llm):
    fake_llm(llm_json())

    classifier.classify_ticket("Título único 123", "Descripción única 456")

    sent = json.dumps(FakeOpenAI.calls[0], default=str)
    assert "Título único 123" in sent
    assert "Descripción única 456" in sent


def test_endpoint_uses_fallback_when_llm_returns_garbage(client, fake_llm):
    fake_llm(llm_json(category="URGENT"))

    response = client.post(
        "/tickets",
        json={"title": "Algo urge", "description": "Descripción válida"},
    )

    assert response.status_code == 201
    data = response.json()
    assert (data["category"], data["priority"], data["tags"]) == ("question", "P3", [])

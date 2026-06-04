"""Tests for the OpenAI LLM client wrapper."""

import pytest

from agents import llm_client


class FakeResponse:
    output_text = "hello from model"


class FakeJsonResponse:
    output_text = '{"status": "ok"}'


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)


def test_ask_llm_returns_text_and_uses_default_model(monkeypatch) -> None:
    fake_client = FakeClient(FakeResponse())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(llm_client, "_client", lambda: fake_client)

    result = llm_client.ask_llm("system", "user")

    assert result == "hello from model"
    assert fake_client.responses.calls[0]["model"] == "gpt-5.2"


def test_ask_llm_json_returns_dict(monkeypatch) -> None:
    fake_client = FakeClient(FakeJsonResponse())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_client, "_client", lambda: fake_client)

    result = llm_client.ask_llm_json("system", "user")

    assert result == {"status": "ok"}


def test_missing_api_key_returns_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is missing"):
        llm_client._api_key()


def test_ask_llm_json_rejects_invalid_json(monkeypatch) -> None:
    fake_client = FakeClient(FakeResponse())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_client, "_client", lambda: fake_client)

    with pytest.raises(ValueError, match="not valid JSON"):
        llm_client.ask_llm_json("system", "user")

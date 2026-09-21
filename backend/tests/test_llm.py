import json

import pytest

from app.config import Settings
from app.services.llm import LLMConfigurationError, LLMResponseError, call_model


def test_mock_llm_returns_valid_json_for_different_modes(settings: Settings) -> None:
    modes = []
    for index in range(3):
        raw = call_model("system", "user", settings, mock_index=index)
        modes.append(json.loads(raw)["choice"]["mode"])
    assert modes == ["open", "locked", "open"]


def test_mock_llm_language_is_respected(settings: Settings) -> None:
    raw = call_model("system", "user", settings, mock_index=0, mock_language="Russian")
    assert "ваш" in json.loads(raw)["narration"] or "Вы" in json.loads(raw)["narration"]


def test_mock_llm_ends_at_max_turns_and_binary_at_midpoint(settings: Settings) -> None:
    mid = call_model("system", "user", settings, mock_index=4, mock_max_turns=10)
    assert json.loads(mid)["choice"]["mode"] == "binary"
    last = call_model("system", "user", settings, mock_index=9, mock_max_turns=10)
    payload = json.loads(last)
    assert payload["is_ending"] is True
    assert payload["choice"] is None


def test_real_mode_without_key_is_clear_error() -> None:
    settings = Settings(mock_llm=False, gemini_api_key="")
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        call_model("system", "user", settings)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _real_settings() -> Settings:
    return Settings(mock_llm=False, gemini_api_key="test-key")


def test_prompt_level_safety_block_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda *args, **kwargs: _FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}}),
    )
    with pytest.raises(LLMResponseError, match="refused the prompt"):
        call_model("system", "user", _real_settings())


def test_candidate_safety_block_names_the_category(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "candidates": [
            {
                "finishReason": "SAFETY",
                "safetyRatings": [
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "probability": "HIGH"},
                    {"category": "HARM_CATEGORY_HARASSMENT", "probability": "NEGLIGIBLE"},
                ],
            }
        ]
    }
    monkeypatch.setattr(
        "app.services.llm.httpx.post", lambda *args, **kwargs: _FakeResponse(payload)
    )
    with pytest.raises(LLMResponseError, match="blocked this turn as unsafe \\(sexually explicit\\)"):
        call_model("system", "user", _real_settings())


def test_empty_candidates_keep_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post", lambda *args, **kwargs: _FakeResponse({"candidates": []})
    )
    with pytest.raises(LLMResponseError, match="unexpected response shape"):
        call_model("system", "user", _real_settings())


def test_max_tokens_finish_reason_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
    monkeypatch.setattr(
        "app.services.llm.httpx.post", lambda *args, **kwargs: _FakeResponse(payload)
    )
    with pytest.raises(LLMResponseError, match="token limit"):
        call_model("system", "user", _real_settings())


def test_safety_settings_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    call_model("system", "user", _real_settings())
    payload = captured["json"]
    thresholds = {entry["category"]: entry["threshold"] for entry in payload["safetySettings"]}
    assert thresholds == {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_ONLY_HIGH",
    }


def _openai_settings() -> Settings:
    return Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="openai",
        openai_base_url="http://localhost:11434/v1/",
        openai_api_key="ollama",
        openai_model="dolphin-llama3:8b",
    )


def test_openai_provider_sends_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    text = call_model("system prompt", "user prompt", _openai_settings())
    assert text == '{"ok": true}'
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    payload = captured["json"]
    assert payload["model"] == "dolphin-llama3:8b"
    assert payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["reasoning"] == {"enabled": False}
    assert captured["headers"]["Authorization"] == "Bearer ollama"


def test_openai_provider_unreachable_server_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def fake_post(*args: object, **kwargs: object) -> _FakeResponse:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    with pytest.raises(LLMResponseError, match="localhost:11434"):
        call_model("system", "user", _openai_settings())


def test_openai_provider_requires_no_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda *args, **kwargs: _FakeResponse({"choices": [{"message": {"content": "text"}}]}),
    )
    assert call_model("s", "u", _openai_settings()) == "text"  # no LLMConfigurationError


def test_unknown_provider_is_config_error() -> None:
    settings = Settings(mock_llm=False, llm_provider="anthropic")
    with pytest.raises(LLMConfigurationError, match="Unknown LLM_PROVIDER"):
        call_model("system", "user", settings)

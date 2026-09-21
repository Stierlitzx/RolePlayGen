import json

import pytest

from app.config import Settings
from app.services.llm import LLMConfigurationError, call_model


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

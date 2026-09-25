import json

import pytest

from app.config import Settings
from app.services.llm import LLMConfigurationError, LLMResponseError, call_model, translate_image_tags


def test_mock_llm_returns_valid_json_for_different_modes(settings: Settings) -> None:
    modes = []
    for index in range(3):
        raw = call_model("system", "user", settings, mock_index=index)
        modes.append(json.loads(raw)["choice"]["mode"])
    assert modes == ["open", "locked", "open"]


def test_translate_image_tags_uses_one_narrow_call(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from app.services import story_engine as engine

    from app.models import Story

    answers: list[str] = []

    def fake_translate(system: object, user: object, *args: object, **kwargs: object) -> str:
        answers.append(str(user))
        return "Garret in the tavern, night"

    monkeypatch.setattr("app.services.llm.call_model", fake_translate)
    # ...but the call must NOT happen in mock mode at all.
    assert translate_image_tags("таверна", settings) is None
    assert answers == []

    real = Settings(mock_llm=False, gemini_api_key="x")
    assert translate_image_tags("1girl, тёмная таверна, ночь", real) == "Garret in the tavern, night"
    assert len(answers) == 1 and "TAGS:" in answers[0]

    fake_settings = Settings(mock_llm=True)  # keeps the original text
    story_row = Story(title="t", settings={}, max_turns=None)
    assert (
        engine._english_tags("1girl, тёмный лес", story_row, fake_settings)
        == "1girl, тёмный лес"
    )


def test_mock_llm_language_is_respected(settings: Settings) -> None:
    raw = call_model("system", "user", settings, mock_index=0, mock_language="Russian")
    assert "ваш" in json.loads(raw)["narration"] or "Вы" in json.loads(raw)["narration"]


def test_mock_intro_uses_localized_setting_name(settings: Settings) -> None:
    # The raw English preset key must never leak into Russian prose.
    raw = call_model(
        "s", "u", settings, mock_index=0, mock_language="Russian", mock_setting="Wizard school"
    )
    narration = json.loads(raw)["narration"]
    assert "Wizard school" not in narration
    assert "школа магии" in narration
    # the prologue is a multi-paragraph open-ended opening, not two clipped lines
    assert narration.count("\n\n") >= 3


def test_mock_intro_passes_custom_setting_through(settings: Settings) -> None:
    raw = call_model(
        "s", "u", settings, mock_index=0, mock_language="Russian", mock_setting="Летающий архипелаг"
    )
    assert "Летающий архипелаг" in json.loads(raw)["narration"]


def test_mock_state_and_narration_have_no_raw_preset_key(settings: Settings) -> None:
    raw = call_model(
        "s", "u", settings, mock_index=1, mock_language="Russian",
        mock_setting="Cyberpunk metropolis",
    )
    payload = json.loads(raw)
    assert "Cyberpunk metropolis" not in payload["narration"]
    assert "Cyberpunk metropolis" not in payload["state"]["summary"]
    assert "киберпанк-мегаполис" in payload["state"]["scene"]


def test_mock_hero_tags_follow_player_appearance_and_gender(settings: Settings) -> None:
    raw = call_model(
        "s", "u", settings, mock_index=0, mock_language="English",
        mock_hero_appearance="Platinum-blonde ponytail. Golden-brown eyes. Red silk blouse.",
        mock_hero_gender="Female",
    )
    tags = json.loads(raw)["hero"]["appearance_tags"]
    assert tags.startswith("1girl, solo, adult")
    assert "Platinum-blonde ponytail" in tags and "Red silk blouse" in tags

    raw = call_model("s", "u", settings, mock_index=0, mock_hero_gender="Male")
    assert json.loads(raw)["hero"]["appearance_tags"].startswith("1boy")


def test_mock_scene_prompt_has_no_hardcoded_look(settings: Settings) -> None:
    # The hero's stored appearance tags are spliced into every scene by the
    # backend — the mock scene prompt must not contradict them with a fixed look.
    raw = call_model("s", "u", settings, mock_index=1, mock_setting="Space station")
    payload = json.loads(raw)
    assert "cloak" not in payload["image_prompt"]
    assert payload["characters_in_scene"] == ["__hero__"]


def test_mock_seed_rotates_intro_and_companion(settings: Settings) -> None:
    first = json.loads(call_model("s", "u", settings, mock_index=0, mock_language="Russian", mock_seed=0))
    second = json.loads(call_model("s", "u", settings, mock_index=0, mock_language="Russian", mock_seed=1))
    assert first["narration"] != second["narration"]
    assert first["characters"][0]["name"] != second["characters"][0]["name"]


def test_mock_solo_opening_has_no_companion(settings: Settings) -> None:
    # Every fourth seed opens with the hero alone: no guide, no stranger.
    payload = json.loads(call_model("s", "u", settings, mock_index=0, mock_seed=3))
    assert "characters" not in payload
    assert payload["hero"]["appearance_tags"]


def test_mock_scenes_rotate_between_turns(settings: Settings) -> None:
    turn2 = json.loads(call_model("s", "u", settings, mock_index=1))
    turn3 = json.loads(call_model("s", "u", settings, mock_index=2))
    assert turn2["narration"] != turn3["narration"]
    assert turn2["state"]["facts"] != turn3["state"]["facts"]


def test_mock_hero_tags_always_include_clothing(settings: Settings) -> None:
    # A non-English description is unreadable to the image model; without a
    # clothing anchor it renders the hero nude. "fully clothed" prevents that.
    raw = call_model("s", "u", settings, mock_index=0, mock_hero_appearance="короткие рыжие волосы, зелёные глаза")
    tags = json.loads(raw)["hero"]["appearance_tags"]
    assert "fully clothed" in tags


def test_faithful_appearance_tags_stays_out_of_mock_mode(settings: Settings) -> None:
    from app.services.llm import faithful_appearance_tags

    assert faithful_appearance_tags("long red hair", "Female", settings) is None
    assert faithful_appearance_tags("", "Female", settings) is None


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


def test_provider_param_overrides_server_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # The server default is Gemini (no key configured), but this story picked
    # the local model — the per-story choice must win and need no Gemini key.
    settings = Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="gemini",
        openai_base_url="http://localhost:11434/v1/",
        openai_api_key="ollama",
        openai_model="dolphin-llama3:8b",
    )
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", settings, provider="local") == "ok"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"]["model"] == "dolphin-llama3:8b"


def test_provider_param_gemini_ignores_local_server(monkeypatch: pytest.MonkeyPatch) -> None:
    # Server default is the local provider, but the story picked Gemini.
    settings = Settings(
        mock_llm=False,
        gemini_api_key="test-key",
        llm_provider="openai",
        openai_base_url="http://localhost:11434/v1/",
    )
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    call_model("s", "u", settings, provider="gemini")
    assert "generativelanguage.googleapis.com" in captured["url"]


def test_unknown_provider_param_is_config_error() -> None:
    settings = Settings(mock_llm=False, gemini_api_key="k")
    with pytest.raises(LLMConfigurationError, match="Unknown LLM_PROVIDER"):
        call_model("system", "user", settings, provider="anthropic")


def _cloud_settings() -> Settings:
    return Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="groq",
        groq_api_key="gsk-test",
        groq_model="qwen/qwen3.8-27b",
        openrouter_api_key="sk-or-test",
        openrouter_model="some/model:free",
        mistral_api_key="mistral-test",
        mistral_model="mistral-medium-latest",
    )


def test_groq_provider_uses_groq_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", _cloud_settings()) == "ok"
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["json"]["model"] == "qwen/qwen3.8-27b"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    # Groq's strict API rejects the reasoning toggle with a 400 — omitted.
    assert "reasoning" not in captured["json"]
    # Free-tier OTPM is ~1000 output tokens/min: the request is capped under it
    # or Groq rejects it outright with 429 "Request too large".
    assert captured["json"]["max_tokens"] == 950
    assert captured["headers"]["Authorization"] == "Bearer gsk-test"


def test_mistral_provider_param_uses_mistral_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Server default is Groq, but this story picked Mistral — the per-story
    # choice must win.
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", _cloud_settings(), provider="mistral") == "ok"
    assert captured["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert captured["json"]["model"] == "mistral-medium-latest"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    # Strict like Groq: no reasoning toggle; Mistral gets the full budget.
    assert "reasoning" not in captured["json"]
    assert captured["json"]["max_tokens"] == 4000
    assert captured["headers"]["Authorization"] == "Bearer mistral-test"


def test_openrouter_falls_back_to_next_free_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # A congested (429) or removed-from-free (404) model retries on the next
    # free model instead of failing the turn.
    attempts: list[str] = []

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        attempts.append(kwargs["json"]["model"])
        if len(attempts) == 1:
            return _FakeResponse({"error": {"message": "rate-limited"}}, status_code=429)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", _cloud_settings(), provider="openrouter") == "ok"
    assert attempts[0] == "some/model:free"
    assert len(attempts) == 2 and attempts[1] != "some/model:free"


def test_mistral_falls_back_to_next_model_class(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Experiment tier rate-limits per model class: medium/small are often
    # 429 while ministral answers — fall back instead of failing the turn.
    attempts: list[str] = []

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        attempts.append(kwargs["json"]["model"])
        if attempts[-1] == "mistral-medium-latest":
            return _FakeResponse({"message": "Rate limit exceeded"}, status_code=429)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", _cloud_settings(), provider="mistral") == "ok"
    assert attempts[0] == "mistral-medium-latest"
    assert len(attempts) == 2 and attempts[1] != "mistral-medium-latest"


def test_openrouter_provider_param_uses_openrouter_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Server default is Groq, but this story picked OpenRouter — the per-story
    # choice must win.
    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    assert call_model("s", "u", _cloud_settings(), provider="openrouter") == "ok"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["json"]["model"] == "some/model:free"
    # OpenRouter accepts the reasoning toggle; its free reasoning models need it.
    assert captured["json"]["reasoning"] == {"enabled": False}
    assert captured["headers"]["Authorization"] == "Bearer sk-or-test"


def test_groq_provider_requires_key() -> None:
    settings = Settings(mock_llm=False, llm_provider="groq", groq_api_key="")
    with pytest.raises(LLMConfigurationError, match="GROQ_API_KEY"):
        call_model("system", "user", settings)


def test_openrouter_provider_requires_key() -> None:
    settings = Settings(mock_llm=False, llm_provider="openrouter", openrouter_api_key="")
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        call_model("system", "user", settings)


def test_mistral_provider_requires_key() -> None:
    settings = Settings(mock_llm=False, llm_provider="mistral", mistral_api_key="")
    with pytest.raises(LLMConfigurationError, match="MISTRAL_API_KEY"):
        call_model("system", "user", settings)

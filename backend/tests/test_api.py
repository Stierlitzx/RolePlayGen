from fastapi.testclient import TestClient


def payload() -> dict:
    return {
        "setting": "Space station",
        "custom_setting": None,
        "genres": ["Science fiction"],
        "tone": "Serious",
        "hero_role": "Engineer",
        "hero_name": "Ada",
        "length": "custom",
        "custom_turns": 50,
        "model": "gemini-3.6-flash",
        "content_restrictions": None,
        "language": "English",
    }


def test_health_and_setup_options(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    options = client.get("/api/setup-options")
    assert options.status_code == 200
    assert "Space station" in options.json()["settings"]
    assert options.json()["mock_llm"] is True
    assert len(options.json()["models"]) >= 1
    assert any(length["value"] == "custom" for length in options.json()["lengths"])
    # the provider picker: both backends are served side by side
    body = options.json()
    assert body["default_provider"] == "gemini"
    assert len(body["gemini_models"]) >= 1
    assert body["gemini_configured"] is False  # no key in tests
    assert body["local_configured"] is True  # default OPENAI_BASE_URL is set
    assert body["local_model"] == "llama3.1:8b"
    assert body["groq_configured"] is False  # no key in tests
    assert body["groq_model"] is None
    assert body["openrouter_configured"] is False
    assert body["openrouter_model"] is None
    assert body["mistral_configured"] is False
    assert body["mistral_model"] is None


def test_story_provider_choice_round_trips(client: TestClient) -> None:
    for provider in ("local", "groq", "openrouter", "mistral"):
        data = payload()
        data["llm_provider"] = provider
        created = client.post("/api/stories", json=data)
        assert created.status_code == 201
        assert created.json()["settings"]["llm_provider"] == provider

    bad = payload()
    bad["llm_provider"] = "anthropic"
    assert client.post("/api/stories", json=bad).status_code == 422


def test_story_lifecycle_through_api(client: TestClient) -> None:
    created = client.post("/api/stories", json=payload())
    assert created.status_code == 201
    story = created.json()
    assert story["turns"][0]["choice"]["mode"] == "open"

    listed = client.get("/api/stories")
    assert listed.status_code == 200
    assert listed.json()[0]["turn_count"] == 1

    second = client.post(f"/api/stories/{story['id']}/turns", json={"option_id": "a"})
    assert second.status_code == 201
    assert second.json()["choice"]["mode"] == "locked"

    # A custom action is accepted on a locked turn too — the mode limits the
    # options the narrator offers, never what the player may type.
    own = client.post(f"/api/stories/{story['id']}/turns", json={"custom_text": "Fly away"})
    assert own.status_code == 201
    assert own.json()["player_input_type"] == "custom"

    turn_by_index: dict[int, dict] = {}
    current = second.json()
    while not current["is_ending"]:
        nxt = client.post(f"/api/stories/{story['id']}/turns", json={"option_id": "a"})
        assert nxt.status_code == 201
        current = nxt.json()
        turn_by_index[current["index"]] = current
        if len(turn_by_index) > 60:
            raise AssertionError("story did not finish within the expected turn count")

    assert current["index"] == 49
    assert current["choice"] is None
    modes = {t["choice"]["mode"] for t in turn_by_index.values() if t["choice"]}
    assert modes == {"open", "locked", "binary"}
    binary_turns = [t["index"] + 1 for t in turn_by_index.values() if t["choice"] and t["choice"]["mode"] == "binary"]
    assert binary_turns == [25]

    conflict = client.post(f"/api/stories/{story['id']}/turns", json={"option_id": "a"})
    assert conflict.status_code == 409

    deleted = client.delete(f"/api/stories/{story['id']}")
    assert deleted.status_code == 204
    missing = client.get(f"/api/stories/{story['id']}")
    assert missing.status_code == 404


def test_invalid_story_input_is_400(client: TestClient) -> None:
    bad_payload = payload()
    bad_payload["genres"] = []
    response = client.post("/api/stories", json=bad_payload)
    assert response.status_code == 422


def test_missing_story_is_404(client: TestClient) -> None:
    response = client.get("/api/stories/999")
    assert response.status_code == 404


def test_update_and_regenerate_start_via_api(client: TestClient) -> None:
    created = client.post("/api/stories", json=payload())
    story = created.json()

    new_payload = payload()
    new_payload["hero_name"] = "Raya"
    new_payload["language"] = "Russian"
    updated = client.patch(f"/api/stories/{story['id']}", json=new_payload)
    assert updated.status_code == 200
    assert updated.json()["title"].startswith("Raya")
    assert updated.json()["settings"]["language"] == "Russian"

    regenerated = client.post(f"/api/stories/{story['id']}/regenerate-start")
    assert regenerated.status_code == 200
    assert len(regenerated.json()["turns"]) == 1

    turn = client.post(f"/api/stories/{story['id']}/turns", json={"option_id": "a"})
    assert turn.status_code == 201
    new_payload["tone"] = "Epic"  # any non-style change is frozen mid-story
    blocked = client.patch(f"/api/stories/{story['id']}", json=new_payload)
    assert blocked.status_code == 400
    blocked_regen = client.post(f"/api/stories/{story['id']}/regenerate-start")
    assert blocked_regen.status_code == 400

    # the narrator voice is the one thing that may change mid-story
    current = client.get(f"/api/stories/{story['id']}").json()
    style_only = dict(current["settings"])
    style_only["narrator_style"] = "Noir"
    restyled = client.patch(f"/api/stories/{story['id']}", json=style_only)
    assert restyled.status_code == 200
    assert restyled.json()["settings"]["narrator_style"] == "Noir"
    assert restyled.json()["settings"]["hero_name"] == "Raya"  # everything else untouched

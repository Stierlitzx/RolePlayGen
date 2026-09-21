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
        "model": None,
        "content_restrictions": None,
        "language": "English",
    }


def test_turn_image_endpoint_and_retry_rules(client: TestClient) -> None:
    created = client.post("/api/stories", json=payload())
    assert created.status_code == 201
    turn = created.json()["turns"][0]
    assert "image_status" in turn

    info = client.get(f"/api/turns/{turn['id']}/image")
    assert info.status_code == 200
    body = info.json()
    assert body["status"] == "none"  # image generation disabled in tests by default
    assert body["url"] is None

    # retry is only allowed from failed
    rejected = client.post(f"/api/turns/{turn['id']}/image/retry")
    assert rejected.status_code == 400

    missing = client.get("/api/turns/9999/image")
    assert missing.status_code == 404


def test_retry_from_failed_requeues(client: TestClient, db_session) -> None:
    created = client.post("/api/stories", json=payload())
    turn_id = created.json()["turns"][0]["id"]

    # simulate a failed job directly in the database
    from app.models import Turn

    turn = db_session.get(Turn, turn_id)
    turn.image_status = "failed"
    turn.image_error = "Image generator is not running"
    db_session.commit()

    info = client.get(f"/api/turns/{turn_id}/image")
    assert info.json()["status"] == "failed"
    assert "not running" in info.json()["error"]

    retried = client.post(f"/api/turns/{turn_id}/image/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"


def test_story_response_includes_image_fields(client: TestClient) -> None:
    created = client.post("/api/stories", json=payload())
    story_id = created.json()["id"]
    fetched = client.get(f"/api/stories/{story_id}")
    turn = fetched.json()["turns"][0]
    for key in ("image_status", "image_format", "image_url"):
        assert key in turn

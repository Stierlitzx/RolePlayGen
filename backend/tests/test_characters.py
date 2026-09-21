"""Character tracking: upsert logic, endpoints, portrait queue, cleanup."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Character, Story, Turn
from app.schemas import StoryCreate, TurnCreate
from app.services import image_service, story_engine


def payload(**overrides) -> dict:
    data = {
        "setting": "Space station",
        "genres": ["Science fiction"],
        "tone": "Serious",
        "hero_role": "Engineer",
        "hero_name": "Ada",
        "length": "custom",
        "custom_turns": 50,
        "language": "English",
    }
    data.update(overrides)
    return data


def _characters(db: Session, story_id: int) -> list[Character]:
    return list(db.query(Character).filter(Character.story_id == story_id).order_by(Character.id))


def _turn_contract_with(characters_json: str) -> str:
    return (
        '{"narration": "Next.", "choice": {"mode": "locked", "options": '
        '[{"id": "a", "text": "Go"}, {"id": "b", "text": "Stay"}], '
        '"allow_custom": false, "prompt": "Choose"}, '
        '"state": {"scene": "Dock", "summary": "S", "facts": []}, "is_ending": false, '
        f'"characters": {characters_json}}}'
    )


def test_mock_story_registers_hero_and_companion(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    characters = _characters(db_session, story.id)
    assert len(characters) == 2
    hero = next(c for c in characters if c.is_hero)
    companion = next(c for c in characters if not c.is_hero)
    assert hero.name == "Ada"  # falls back to the setup hero_name
    assert hero.appearance_tags and "1girl" in hero.appearance_tags
    assert hero.relationship is None
    assert companion.name == "Warden Hale"
    assert companion.role == "local guide"
    assert companion.relationship == "wary ally"
    assert companion.first_seen_turn_id == story.turns[0].id
    # image generation disabled in tests: no portrait jobs
    assert all(c.portrait_status == "none" for c in characters)


def test_new_character_enqueues_portrait_when_images_enabled(db_session: Session) -> None:
    while not image_service._job_queue.empty():  # drain leftovers (e.g. stop sentinels)
        image_service._job_queue.get_nowait()
    settings = Settings(mock_llm=True, image_generation_enabled=True)
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    characters = _characters(db_session, story.id)
    assert len(characters) == 2
    assert all(c.portrait_status == "queued" for c in characters)
    jobs = []
    while not image_service._job_queue.empty():
        jobs.append(image_service._job_queue.get_nowait())
    portraits = [job for job in jobs if job[0] == "portrait"]
    scenes = [job for job in jobs if job[0] == "scene"]
    assert len(portraits) == 2  # hero + companion
    assert len(scenes) == 1  # the turn-1 scene illustration shares the queue


def test_characters_endpoint_returns_first_seen_turn_id(client: TestClient) -> None:
    created = client.post("/api/stories", json=payload())
    assert created.status_code == 201
    story_id = created.json()["id"]
    turn_id = created.json()["turns"][0]["id"]

    response = client.get(f"/api/stories/{story_id}/characters")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2  # hero + companion from the mock narrator
    assert all("first_seen_turn_id" in item for item in data)
    assert all(item["first_seen_turn_id"] == turn_id for item in data)



def test_unknown_name_without_is_new_is_created_anyway(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with('[{"name": "Mysterious Stranger", "is_new": false}]'),
    )
    with caplog.at_level("WARNING"):
        story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    names = [c.name for c in _characters(db_session, story.id)]
    assert "Mysterious Stranger" in names
    assert "without is_new" in caplog.text


def test_scene_appearance_tags_splicing(db_session: Session) -> None:
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    db_session.add_all([
        Character(story_id=story.id, name="Ada", is_hero=True, appearance_tags="1girl, red hair"),
        Character(story_id=story.id, name="Kaelen", appearance_tags="1boy, tricorn hat"),
        Character(story_id=story.id, name="Una", appearance_tags="1girl, silver hair"),
    ])
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["__hero__", "Kaelen"],
    )
    db_session.add(turn)
    db_session.commit()

    hero_tags, tags = image_service._scene_appearance_tags(db_session, turn)
    assert hero_tags == "1girl, red hair"
    assert tags == ["1boy, tricorn hat"]  # hero sentinel skipped, scene order kept

    prompt = image_service.assemble_positive_prompt("standing, dock", hero_tags, tags)
    assert prompt.index("1girl, red hair") < prompt.index("1boy, tricorn hat") < prompt.index("standing, dock")

    # fallback: no characters_in_scene -> hero only
    turn.characters_in_scene = None
    hero_tags, tags = image_service._scene_appearance_tags(db_session, turn)
    assert hero_tags == "1girl, red hair"
    assert tags == []


def test_portrait_prompt_sanitized_and_framed() -> None:
    prompt = image_service.assemble_portrait_prompt(
        "1girl, nsfw, green eyes, masterpiece, scar",
        pose="arms crossed",
        expression="sardonic grin",
    )
    assert "nsfw" not in prompt
    assert "green eyes" in prompt and "adult" in prompt
    assert "arms crossed" in prompt and "sardonic grin" in prompt
    assert prompt.endswith("full body, standing, looking at viewer, simple background")


def test_relationship_update_does_not_overwrite_appearance(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    companion = next(c for c in _characters(db_session, story.id) if not c.is_hero)

    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "warden hale", "is_new": false, "relationship": "trusted ally", '
            '"appearance_tags": "SHOULD NOT STICK", "description": "SHOULD NOT STICK"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    db_session.refresh(companion)
    assert companion.relationship == "trusted ally"  # case-insensitive name match worked
    assert companion.appearance_tags != "SHOULD NOT STICK"
    assert companion.description != "SHOULD NOT STICK"


def test_character_endpoints_and_retry_rules(client: TestClient, db_session: Session) -> None:
    created = client.post("/api/stories", json=payload())
    assert created.status_code == 201
    story_id = created.json()["id"]

    listed = client.get(f"/api/stories/{story_id}/characters")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 2
    assert body[0]["is_hero"] is True  # hero pinned first
    assert body[0]["name"] == "Ada"
    assert body[1]["role"] == "local guide"
    assert body[1]["portrait_url"] is None

    character_id = body[1]["id"]
    detail = client.get(f"/api/characters/{character_id}")
    assert detail.status_code == 200
    assert detail.json()["description"]

    # retry allowed only from failed
    rejected = client.post(f"/api/characters/{character_id}/portrait/retry")
    assert rejected.status_code == 400

    character = db_session.get(Character, character_id)
    character.portrait_status = "failed"
    character.portrait_error = "Interrupted"
    db_session.commit()
    retried = client.post(f"/api/characters/{character_id}/portrait/retry")
    assert retried.status_code == 200
    assert retried.json()["portrait_status"] == "queued"

    assert client.get("/api/characters/9999").status_code == 404
    assert client.get("/api/stories/9999/characters").status_code == 404


def test_startup_cleanup_covers_portraits(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    for status in ("queued", "generating", "done"):
        db_session.add(Character(story_id=story.id, name=f"C{status}", portrait_status=status))
    db_session.commit()

    count = image_service.reset_interrupted_turns()
    assert count == 2
    statuses = [c.portrait_status for c in _characters(db_session, story.id)]
    assert statuses == ["failed", "failed", "done"]

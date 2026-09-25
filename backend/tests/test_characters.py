"""Character tracking: upsert logic, endpoints, portrait queue, cleanup."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from pathlib import Path

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


def test_player_photo_upload(client: TestClient, db_session: Session) -> None:
    # The Characters tab lets the player hand the generator their own picture of
    # a character: it becomes the reference every picture is built from, and
    # (with use_as_portrait) the card shows it right away — no GPU job.
    created = client.post("/api/stories", json=payload())
    story_id = created.json()["id"]
    companion = next(
        c for c in _characters(db_session, story_id) if not c.is_hero
    )
    # Pretend a portrait was already generated, so the upload has something to
    # keep: the old look must stay in the gallery and remain revertible.
    companion.portrait_status = "done"
    companion.portrait_path = f"{story_id}/char_{companion.id}.png"
    history = [dict(entry) for entry in (companion.portrait_history or [])]
    history[0]["portrait_path"] = companion.portrait_path
    companion.portrait_history = history
    db_session.commit()

    response = client.post(
        f"/api/characters/{companion.id}/portrait",
        json={"image": "data:image/png;base64,aGVsbG8=", "use_as_portrait": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["portrait_status"] == "done"
    assert body["portrait_url"] == f"/media/{story_id}/photo_{companion.id}.png"
    assert body["photo_url"] == body["portrait_url"]
    # The generated look is APPENDED, not replaced: it stays in the gallery and
    # stays available for a revert.
    assert len(body["portrait_history"]) == 2
    assert body["portrait_history"][0]["portrait_url"] == f"/media/{story_id}/char_{companion.id}.png"
    assert body["portrait_history"][1]["portrait_url"] == body["portrait_url"]

    db_session.refresh(companion)
    assert companion.photo_path == f"{story_id}/photo_{companion.id}.png"
    # No job was queued: the player's file IS the portrait now.
    assert companion.portrait_status == "done"

    # A broken upload is a plain 400 with a readable reason, never a 500.
    broken = client.post(
        f"/api/characters/{companion.id}/portrait", json={"image": "nonsense"}
    )
    assert broken.status_code == 400
    assert "data URL" in broken.json()["detail"]


def test_photo_without_use_as_portrait_only_serves_as_reference(
    client: TestClient, db_session: Session
) -> None:
    created = client.post("/api/stories", json=payload())
    story_id = created.json()["id"]
    companion = next(c for c in _characters(db_session, story_id) if not c.is_hero)
    body = client.post(
        f"/api/characters/{companion.id}/portrait",
        json={"image": "data:image/png;base64,aGVsbG8=", "use_as_portrait": False},
    ).json()
    assert body["photo_url"]
    assert body["portrait_status"] == "none"  # the generated card is untouched


def test_hero_photo_is_stored_with_the_story(db_session: Session, settings: Settings) -> None:
    # The setup form's hero photo lands under IMAGE_DIR and is remembered in the
    # story settings as a path — the data URL itself is never stored.
    story = story_engine.create_story(
        db_session,
        StoryCreate(**payload(hero_image="data:image/png;base64,aGVsbG8=")),
        settings,
    )
    assert story.settings["hero_image"] == f"{story.id}/hero_photo.png"
    assert (Path(settings.image_dir) / story.settings["hero_image"]).read_bytes() == b"hello"

    # Replacing it mid-story is allowed (it is a picture, not a story parameter).
    updated = story_engine.update_story(
        db_session,
        story.id,
        StoryCreate(**payload(hero_image="data:image/png;base64,d29ybGQ=")),
        settings,
    )
    assert updated.settings["hero_image"] == f"{story.id}/hero_photo.png"
    assert (Path(settings.image_dir) / updated.settings["hero_image"]).read_bytes() == b"world"


def test_a_broken_hero_photo_is_rejected_in_plain_language(
    db_session: Session, settings: Settings
) -> None:
    with pytest.raises(story_engine.InvalidPlayerInputError, match="data URL"):
        story_engine.create_story(
            db_session, StoryCreate(**payload(hero_image="oops")), settings
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


def test_hero_first_portrait_carries_the_narrator_pose(db_session: Session, settings: Settings) -> None:
    # The hero's report is the only channel for the hero's pose and expression:
    # without it the engine used to store an empty history, and every hero of
    # every story fell back to the same hardcoded standing look.
    from app.services.llm import _MOCK_HERO_POSES

    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    hero = next(c for c in _characters(db_session, story.id) if c.is_hero)
    pose, expression = _MOCK_HERO_POSES[(story.id - 1) % len(_MOCK_HERO_POSES)]
    latest = hero.portrait_history[-1]
    assert latest["pose"] == pose
    assert latest["expression"] == expression
    # ... and that posed history is what the portrait job paints from.
    prompt = image_service.assemble_portrait_prompt(
        latest["appearance_tags"], pose=latest["pose"], expression=latest["expression"]
    )
    assert pose.split(",")[0] in prompt
    assert "standing" not in prompt.split(", ")


def test_hero_named_in_characters_report_is_not_duplicated(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Small narrators list the hero in "characters" despite the rules, and
    # SQLite's ASCII-only lower() used to miss Cyrillic case differences —
    # both must not spawn a second "hero" row.
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "ada", "is_new": true, "role": "stowaway", '
            '"relationship": "unknown", "description": "Duplicate attempt.", '
            '"appearance_tags": "1girl, adult"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    characters = _characters(db_session, story.id)
    assert len([c for c in characters if c.name.casefold() == "ada"]) == 1
    assert len(characters) == 2  # still just hero + companion


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


def test_hero_placeholder_report_creates_no_duplicate_hero(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A small narrator copied the "__hero__" sentinel (which `characters_in_scene`
    # uses for the player) into "characters" as a NAME. That used to create a
    # second character row for the player, with a wasted portrait job, and the
    # turn feed showed the player twice (the "___hero___" card).
    settings = Settings(mock_llm=True, image_generation_enabled=True)
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    queued: list[int] = []
    monkeypatch.setattr(image_service, "enqueue_portrait", lambda cid: queued.append(cid))
    queued.clear()  # the opening turn's own portraits are not the subject here
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "__hero__", "is_new": true, "role": "main heroine", '
            '"description": "the village elf", "appearance_tags": "1girl, elf ears, adult"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    characters = _characters(db_session, story.id)
    assert [c.name for c in characters].count("Ada") == 1  # the hero, exactly once
    assert "__hero__" not in [c.name for c in characters]
    assert len([c for c in characters if c.is_hero]) == 1
    assert queued == []  # no portrait job for a phantom character


def test_hero_row_name_falls_back_from_placeholders() -> None:
    assert story_engine._hero_row_name("Эльвира", "Ada") == "Эльвира"
    assert story_engine._hero_row_name("__hero__", "Ada") == "Ada"
    assert story_engine._hero_row_name("hero", None) == "Hero"
    assert story_engine._hero_row_name(None, "Ada") == "Ada"


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
    # Scene tags lead; spliced appearance anchors follow, hero before the NPC.
    assert prompt.index("standing, dock") < prompt.index("1girl, red hair") < prompt.index("1boy, tricorn hat")

    # fallback: no characters_in_scene -> hero only
    turn.characters_in_scene = None
    hero_tags, tags = image_service._scene_appearance_tags(db_session, turn)
    assert hero_tags == "1girl, red hair"
    assert tags == []


def test_portrait_prompt_keeps_the_narrator_tags_and_framing() -> None:
    prompt = image_service.assemble_portrait_prompt(
        "1girl, nsfw, green eyes, masterpiece, scar",
        pose="arms crossed",
        expression="sardonic grin",
    )
    # Content filtering is off: the narrator's own rating word survives...
    assert "nsfw" in prompt
    # ...while the quality vocabulary the backend itself writes never reaches the
    # prompt any more (the old SDXL prefix is gone).
    assert "masterpiece" not in prompt and "best quality" not in prompt
    assert "green eyes" in prompt and "adult" in prompt
    # The narrator's pose survives and is NOT overridden by a generic one.
    assert "arms crossed" in prompt and "sardonic grin" in prompt
    assert "standing" not in prompt  # a stated pose never gets the standing default
    # ...but the reference card keeps the face towards the camera: a look that
    # states no gaze at all gets the frontal one (see _portrait_framing).
    assert prompt.rstrip().endswith("cowboy shot, looking at viewer, simple background")


def test_portrait_drops_the_over_the_shoulder_pose() -> None:
    # The reference card must show the face: a back-turned pose is dropped and
    # the frontal gaze restored — instead of a copy of the player's back.
    prompt = image_service.assemble_portrait_prompt(
        "1girl, long hair, red cloak",
        pose="glancing over her shoulder",
    )
    assert "over her shoulder" not in prompt
    assert "looking at viewer" in prompt
    assert "glancing away" not in prompt


def test_portrait_keeps_an_averted_stated_gaze() -> None:
    prompt = image_service.assemble_portrait_prompt(
        "1girl, green eyes",
        pose="full body, sitting on a crate, looking away",
        expression="amused",
    )
    assert "looking away" in prompt
    assert prompt.count("looking at viewer") == 0
    # ...while the same back-turned tags survive in a SCENE untouched.
    scene = image_service.assemble_positive_prompt(
        "1girl, glancing over her shoulder, forest", hero_tags="1girl"
    )
    assert "glancing over her shoulder" in scene



def test_portrait_prompt_without_pose_uses_the_generic_fallback() -> None:
    # A portrait the narrator left blank still gets framed as a reference card.
    prompt = image_service.assemble_portrait_prompt("1girl, green eyes")
    tags = [tag.strip() for tag in prompt.split(",")]
    assert "cowboy shot" in tags
    assert "standing" in tags and "looking at viewer" in tags
    assert "simple background" in tags


def test_portrait_prompt_keeps_a_stated_shot_and_gaze() -> None:
    # A full-body card with an averted gaze keeps them; the default must not
    # be layered on top.
    prompt = image_service.assemble_portrait_prompt(
        "1girl, green eyes",
        pose="full body, sitting on a crate, glancing away",
        expression="amused",
    )
    tags = [tag.strip() for tag in prompt.split(",")]
    assert tags.count("cowboy shot") == 0
    assert "full body" in tags and "glancing away" in tags
    assert "looking at viewer" not in tags


def test_portrait_prompt_does_not_edit_the_narrator_look() -> None:
    # Content filtering is off: nudity tags the narrator wrote stay in the
    # portrait prompt as they are. The RATING is still the backend's decision —
    # the caller did not ask for an explicit portrait, so the general token is
    # what leads the prompt.
    prompt = image_service.assemble_portrait_prompt(
        "1girl, nude, nipples, long black hair, red dress, explicit",
        pose="standing, naked",
        expression="seductive smile",
    )
    assert prompt.startswith("general, ")
    for kept in ("nude", "nipples", "naked"):
        assert kept in prompt
    assert "long black hair" in prompt and "red dress" in prompt
    assert "standing" in prompt and "seductive smile" in prompt
    assert "adult" in prompt

    # ...and the portrait's negative prompt always carries the nsfw guard then.
    assert image_service.negative_extra_for("anime, cartoon", explicit=False).endswith("nsfw")


def test_portrait_prompt_explicit_only_when_narrator_asks() -> None:
    # explicit=True (18+ explicit story + narrator tagged the look as nude):
    # the nudity tags pass through and the rating token flips.
    prompt = image_service.assemble_portrait_prompt("1girl, nude, long black hair", explicit=True)
    assert prompt.startswith("explicit, ")
    assert "nude" in prompt

    # The nudity DETECTOR outlived the filtering removal (it is not a filter,
    # it is the gate for the explicit rating): nudity tags anywhere in the look
    # signal an explicit portrait.
    assert image_service.portrait_wants_nudity("1girl, nude, long hair")
    assert image_service.portrait_wants_nudity("1girl, dress", pose="naked")
    assert not image_service.portrait_wants_nudity("1girl, dress", expression="smile")


def test_character_detail_serves_portrait_history(client: TestClient, db_session: Session) -> None:
    created = client.post("/api/stories", json=payload())
    assert created.status_code == 201
    story_id = created.json()["id"]
    companion = client.get(f"/api/stories/{story_id}/characters").json()[1]

    character = db_session.get(Character, companion["id"])
    character.portrait_history = [
        {"appearance_tags": "1boy, coat", "pose": "", "expression": "",
         "portrait_path": f"{story_id}/char_{character.id}.png", "turn_id": 1},
        {"appearance_tags": "1boy, armor", "pose": "", "expression": "",
         "portrait_path": None, "turn_id": 5},  # still generating: no URL yet
    ]
    db_session.commit()

    detail = client.get(f"/api/characters/{character.id}").json()
    history = detail["portrait_history"]
    assert len(history) == 2
    assert history[0]["portrait_url"] == f"/media/{story_id}/char_{character.id}.png"
    assert history[0]["current"] is False
    assert history[0]["turn_id"] == 1
    assert history[1]["portrait_url"] is None
    assert history[1]["current"] is True  # the last entry is the current look


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


def test_retry_heals_when_file_exists(
    db_session: Session, settings: Settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed row whose file is actually on disk heals to done — no GPU job.
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "get_settings", lambda: Settings(image_dir=str(tmp_path)))
    while not image_service._job_queue.empty():
        image_service._job_queue.get_nowait()

    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    companion = next(c for c in _characters(db_session, story.id) if not c.is_hero)

    portrait_rel = f"{story.id}/char_{companion.id}.png"
    target = tmp_path / portrait_rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    companion.portrait_status = "failed"
    companion.portrait_error = "timeout"
    companion.portrait_path = portrait_rel

    turn = story.turns[0]
    scene_rel = f"{story.id}/{turn.id}.png"
    (tmp_path / scene_rel).write_bytes(b"png")
    turn.image_status = "failed"
    turn.image_error = "timeout"
    turn.image_path = scene_rel
    db_session.commit()

    healed_portrait = image_service.retry_character_portrait(companion.id)
    assert healed_portrait.portrait_status == "done"
    assert healed_portrait.portrait_error is None

    healed_turn = image_service.retry_turn_image(turn.id)
    assert healed_turn.image_status == "done"
    assert healed_turn.image_error is None

    assert image_service._job_queue.empty()  # nothing was regenerated


def test_save_portrait_versions_do_not_overwrite(tmp_path) -> None:
    # Each portrait version gets its own file: a portrait_update must not
    # overwrite the previous look (the history gallery and revert need it).
    image_settings = Settings(image_dir=str(tmp_path))
    first = image_service.save_portrait(b"one", image_settings, 3, 7)
    second = image_service.save_portrait(b"two", image_settings, 3, 7, version=2)
    assert first == "3/char_7.png"
    assert second == "3/char_7_v2.png"
    assert (tmp_path / first).read_bytes() == b"one"
    assert (tmp_path / second).read_bytes() == b"two"
def test_redescribed_known_character_is_merged_not_duplicated(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The narrator re-titles a known character ("Тайный странник" -> "Странник
    # в чёрном") and even marks it is_new: the shared descriptor token must
    # merge the report into the existing row, and the stored look must win.
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    db_session.add(Character(
        story_id=story.id, name="Тайный странник", is_hero=False,
        role="загадочный мужчина в чёрном", appearance_tags="1boy, black coat, adult",
    ))
    db_session.commit()
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "Странник в чёрном", "is_new": true, "role": "незнакомец", '
            '"relationship": "unknown", "description": "Тот же странник.", '
            '"appearance_tags": "1boy, white hair, adult"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    strangers = [c for c in _characters(db_session, story.id) if "странник" in c.name.casefold()]
    assert len(strangers) == 1
    assert strangers[0].name == "Тайный странник"
    # The existing look is reused, not replaced by the duplicate report.
    assert strangers[0].appearance_tags == "1boy, black coat, adult"


def test_shared_surname_does_not_merge_distinct_characters(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    db_session.add(Character(
        story_id=story.id, name="Иван Петров", is_hero=False, appearance_tags="1boy, adult",
    ))
    db_session.commit()
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "Ольга Петрова", "is_new": true, "role": "сестра Ивана", '
            '"relationship": "ally", "description": "Сестра Ивана.", '
            '"appearance_tags": "1girl, adult"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    names = [c.name for c in _characters(db_session, story.id)]
    assert "Иван Петров" in names
    assert "Ольга Петрова" in names


def test_scene_names_are_canonicalized_to_known_characters(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A loose scene name must be stored as the canonical DB name so the image
    # step (appearance tags, reference portrait) matches exactly.
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    db_session.add(Character(
        story_id=story.id, name="Тайный странник", is_hero=False, appearance_tags="1boy, adult",
    ))
    db_session.commit()
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *a, **k: (
            '{"narration": "Next.", "choice": {"mode": "locked", "options": '
            '[{"id": "a", "text": "Go"}, {"id": "b", "text": "Stay"}], '
            '"allow_custom": false, "prompt": "Choose"}, '
            '"state": {"scene": "Dock", "summary": "S", "facts": []}, "is_ending": false, '
            '"characters_in_scene": ["__hero__", "Странник в чёрном"]}'
        ),
    )
    turn = story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    assert turn.characters_in_scene == ["__hero__", "Тайный странник"]


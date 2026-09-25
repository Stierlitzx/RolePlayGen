"""Age rating, adult genres, narrator/image styles, portrait evolution, cleanup."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.schemas import StoryCreate, TurnCreate
from app.services import image_service, story_engine
from app.setup_options import age_rating_clause, images_are_explicit


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


def test_explicit_options_require_18_plus() -> None:
    with pytest.raises(ValueError, match="18+"):
        StoryCreate(**payload(age_rating="16+", explicit_sexual=True))
    with pytest.raises(ValueError, match="18+"):
        StoryCreate(**payload(age_rating="12+", graphic_violence=True))
    with pytest.raises(ValueError, match="18+"):
        StoryCreate(**payload(age_rating="16+", genres=["Hentai"]))
    # all allowed at 18+
    StoryCreate(**payload(age_rating="18+", explicit_sexual=True, graphic_violence=True,
                          genres=["Hentai", "Horror"]))


def test_age_rating_clause() -> None:
    assert age_rating_clause({}) == ""  # legacy stories: no rating line at all
    assert "12+" in age_rating_clause(payload(age_rating="12+"))
    adult = age_rating_clause(payload(age_rating="18+", explicit_sexual=True))
    assert "explicit sexual content" in adult
    assert "graphic" not in adult.split("explicit sexual content")[0].lower()
    adult_off = age_rating_clause(payload(age_rating="18+"))
    assert "No explicit sexual detail" in adult_off
    assert images_are_explicit(payload(age_rating="18+", explicit_sexual=True)) is True
    assert images_are_explicit(payload(age_rating="18+")) is False
    assert images_are_explicit(payload(age_rating="12+")) is False


def test_system_prompt_includes_style_and_rating(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(
        db_session, StoryCreate(**payload(narrator_style="Noir", age_rating="16+")), settings
    )
    prompt = story_engine._system_prompt(story)
    assert "NARRATOR STYLE" in prompt and "noir" in prompt.lower()
    assert "AGE RATING" in prompt and "16+" in prompt

    legacy = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    assert story_engine._system_prompt(legacy) == story_engine.load_prompt("narrator_system.txt")


def test_scene_prompt_with_style_and_explicit_rating() -> None:
    prompt = image_service.assemble_positive_prompt(
        "1girl, standing, medium wide shot",
        hero_tags="1girl, red eyes",
        style_tags="anime style, anime coloring",
    )
    assert prompt.startswith(
        "anime style, anime coloring, general, "
        "1girl, standing, medium wide shot, adult, 1girl, red eyes"
    )
    # The style also closes the prompt, so a long descriptive vocabulary cannot
    # outvote it (an anime story came back photorealistic without this).
    assert prompt.endswith("anime style, anime coloring")

    explicit_prompt = image_service.assemble_positive_prompt("1girl, nsfw, posing", explicit=True)
    assert explicit_prompt.startswith("explicit, ")
    assert "nsfw" in explicit_prompt  # rating tokens pass only when the story allows it


def test_build_workflow_ignores_negative_extra_qwen_cfg1() -> None:
    # Qwen-Image-2.1 runs at cfg=1: the sampler output equals the positive
    # conditioning, so style negatives / the nsfw guard have no node to go to.
    styled = image_service.build_workflow(
        "wide", "test prompt", "prefix", seed=1, negative_extra="realistic, photorealistic"
    )
    assert styled["6"]["inputs"]["prompt"] == "test prompt"
    plain = image_service.build_workflow("wide", "test prompt", "prefix", seed=1)
    assert plain["6"]["inputs"]["prompt"] == "test prompt"


def _turn_contract_with(characters_json: str, hero_json: str | None = None) -> str:
    hero = f', "hero": {hero_json}' if hero_json else ""
    return (
        '{"narration": "Next.", "choice": {"mode": "locked", "options": '
        '[{"id": "a", "text": "Go"}, {"id": "b", "text": "Stay"}], '
        '"allow_custom": false, "prompt": "Choose"}, '
        '"state": {"scene": "Dock", "summary": "S", "facts": []}, "is_ending": false, '
        f'"characters": {characters_json}{hero}}}'
    )


def _drain_queue() -> None:
    while not image_service._job_queue.empty():
        image_service._job_queue.get_nowait()


def test_portrait_update_and_revert(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _drain_queue()
    settings = Settings(mock_llm=True, image_generation_enabled=True)
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    companion = next(c for c in story.characters if not c.is_hero)
    _drain_queue()

    # Simulate the first portrait having been generated.
    companion.portrait_status = "done"
    companion.portrait_path = f"{story.id}/char_{companion.id}.png"
    history = [dict(entry) for entry in companion.portrait_history]
    history[0]["portrait_path"] = companion.portrait_path
    companion.portrait_history = history
    db_session.commit()

    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "Warden Hale", "is_new": false, "portrait_update": true, '
            '"appearance_tags": "1boy, adult, space suit, helmet", '
            '"pose": "floating in zero-g", "expression": "calm focus"}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(companion)
    assert companion.appearance_tags == "1boy, adult, space suit, helmet"
    assert len(companion.portrait_history) == 2
    assert companion.portrait_history[-1]["pose"] == "floating in zero-g"
    assert companion.portrait_status == "queued"
    jobs = []
    while not image_service._job_queue.empty():
        jobs.append(image_service._job_queue.get_nowait())
    # exactly one portrait job for the new look (the turn's scene illustration
    # shares the queue — the fallback image prompt keeps turns illustrated)
    portraits = [job for job in jobs if job[0] == "portrait"]
    assert portraits == [("portrait", companion.id)]

    # Reverting is instant and free: old file restored, no GPU job.
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "Warden Hale", "is_new": false, "portrait_revert": true}]'
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(companion)
    assert len(companion.portrait_history) == 1
    assert companion.portrait_path == f"{story.id}/char_{companion.id}.png"
    assert companion.portrait_status == "done"
    assert "space suit" not in (companion.appearance_tags or "")
    # no PORTRAIT job enqueued for a revert (the turn's scene illustration
    # still queues — the fallback image prompt keeps every turn illustrated)
    remaining = []
    while not image_service._job_queue.empty():
        remaining.append(image_service._job_queue.get_nowait())
    assert all(job[0] != "portrait" for job in remaining)


def test_portrait_revert_without_history_is_ignored(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            '[{"name": "Warden Hale", "is_new": false, "portrait_revert": true}]'
        ),
    )
    with caplog.at_level("WARNING"):
        story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    companion = next(c for c in story.characters if not c.is_hero)
    assert len(companion.portrait_history) == 1
    assert "portrait_revert" in caplog.text


def test_hero_look_evolution(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    # The player character is not frozen in the outfit they happened to wear at
    # the opening: a persistent change of look repaints the hero's portrait and
    # the previous look comes back for free.
    _drain_queue()
    settings = Settings(mock_llm=True, image_generation_enabled=True)
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    hero = next(c for c in story.characters if c.is_hero)
    original_tags = hero.appearance_tags
    hero.portrait_status = "done"
    hero.portrait_path = f"{story.id}/char_{hero.id}.png"
    history = [dict(entry) for entry in hero.portrait_history]
    history[0]["portrait_path"] = hero.portrait_path
    hero.portrait_history = history
    db_session.commit()
    _drain_queue()

    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            "[]",
            '{"appearance_tags": "1girl, green eyes, red hair, rough brown cloak, '
            'pants, adult", "pose": "pulling the cloak closed", '
            '"expression": "wary", "portrait_update": true}',
        ),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(hero)
    assert "brown cloak" in (hero.appearance_tags or "")
    assert "brown cloak" not in (original_tags or "")
    assert len(hero.portrait_history) == 2
    assert hero.portrait_history[-1]["pose"] == "pulling the cloak closed"
    assert hero.portrait_status == "queued"
    jobs = []
    while not image_service._job_queue.empty():
        jobs.append(image_service._job_queue.get_nowait())
    assert ("portrait", hero.id) in jobs
    # The new look is what every later scene image is built from.
    hero_tags, _ = image_service._scene_appearance_tags(db_session, story.turns[-1])
    assert "brown cloak" in hero_tags

    # Back to the opening look: the old file returns instantly, no GPU job.
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with("[]", '{"portrait_revert": true}'),
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(hero)
    assert len(hero.portrait_history) == 1
    assert hero.appearance_tags == original_tags
    assert hero.portrait_path == f"{story.id}/char_{hero.id}.png"
    assert hero.portrait_status == "done"
    remaining = []
    while not image_service._job_queue.empty():
        remaining.append(image_service._job_queue.get_nowait())
    assert all(job[0] != "portrait" for job in remaining)


def test_hero_revert_without_a_previous_look_is_ignored(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    hero = next(c for c in story.characters if c.is_hero)
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with("[]", '{"portrait_revert": true}'),
    )
    with caplog.at_level("WARNING"):
        story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(hero)
    assert len(hero.portrait_history) == 1  # the opening look is all there is
    assert "portrait_revert" in caplog.text


def test_hero_look_update_and_revert_together_keep_the_update(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    # Both flags in one turn is a contract slip, not a lost turn: the update wins
    # and the odd combination is logged.
    story = story_engine.create_story(db_session, StoryCreate(**payload()), settings)
    hero = next(c for c in story.characters if c.is_hero)
    monkeypatch.setattr(
        story_engine, "call_model",
        lambda *a, **k: _turn_contract_with(
            "[]",
            '{"appearance_tags": "1girl, green eyes, red hair, cloak, adult", '
            '"portrait_update": true, "portrait_revert": true}',
        ),
    )
    with caplog.at_level("WARNING"):
        story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(hero)
    assert len(hero.portrait_history) == 2
    assert "cloak" in (hero.appearance_tags or "")
    assert "portrait_update and portrait_revert" in caplog.text


def test_delete_story_removes_image_folder(tmp_path) -> None:
    from pathlib import Path

    from app.routers.stories import _delete_story_images

    settings = Settings(mock_llm=True, image_dir=str(tmp_path))
    story_dir = tmp_path / "7"
    story_dir.mkdir()
    (story_dir / "6.png").write_bytes(b"png")
    (story_dir / "char_1.png").write_bytes(b"png")

    _delete_story_images(settings, 7)
    assert not story_dir.exists()

    # missing folder and nothing to delete: tolerated silently
    _delete_story_images(settings, 999)
    assert Path(settings.image_dir).exists()


def test_setup_options_serve_new_lists(client: TestClient) -> None:
    options = client.get("/api/setup-options").json()
    assert options["age_ratings"] == ["3+", "7+", "12+", "16+", "18+"]
    assert options["default_age_rating"] == "12+"
    assert "Hentai" in options["adult_genres"]
    assert "Anime (default)" in options["image_styles"]
    assert options["default_narrator_style"] == "Classic narrator"
    assert "Disco Elysium" in options["narrator_styles"]
    assert options["max_genres"] == 5


def test_negative_extra_keeps_nsfw_guard_below_explicit_18() -> None:
    # style negatives pass through; non-explicit stories always get nsfw appended
    assert image_service.negative_extra_for("realistic, photorealistic", False) == (
        "realistic, photorealistic, nsfw"
    )
    assert image_service.negative_extra_for("", False) == "nsfw"
    # only explicit 18+ stories drop the guard
    assert image_service.negative_extra_for("anime, cartoon", True) == "anime, cartoon"
    assert image_service.negative_extra_for("", True) == ""


def test_built_workflow_ignores_negative_guard_qwen_cfg1() -> None:
    workflow = image_service.build_workflow(
        "wide", "p", "x", seed=1,
        negative_extra=image_service.negative_extra_for("", explicit=False),
    )
    assert workflow["8"]["inputs"]["cfg"] == 1
    assert workflow["6"]["inputs"]["prompt"] == "p"


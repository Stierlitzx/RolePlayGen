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
        "masterpiece, best quality, amazing quality, general, anime style, anime coloring, 1girl, red eyes"
    )

    explicit_prompt = image_service.assemble_positive_prompt("1girl, nsfw, posing", explicit=True)
    assert ", explicit," in explicit_prompt
    assert "nsfw" in explicit_prompt  # rating tokens pass only when the story allows it


def test_build_workflow_appends_style_negative() -> None:
    styled = image_service.build_workflow(
        "wide", "test prompt", "prefix", seed=1, negative_extra="realistic, photorealistic"
    )
    assert styled["7"]["inputs"]["text"].endswith("realistic, photorealistic")
    plain = image_service.build_workflow("wide", "test prompt", "prefix", seed=1)
    assert "realistic" not in plain["7"]["inputs"]["text"]


def _turn_contract_with(characters_json: str) -> str:
    return (
        '{"narration": "Next.", "choice": {"mode": "locked", "options": '
        '[{"id": "a", "text": "Go"}, {"id": "b", "text": "Stay"}], '
        '"allow_custom": false, "prompt": "Choose"}, '
        '"state": {"scene": "Dock", "summary": "S", "facts": []}, "is_ending": false, '
        f'"characters": {characters_json}}}'
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
    assert jobs == [("portrait", companion.id)]  # exactly one job for the new look

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
    assert image_service._job_queue.empty()  # no job enqueued for a revert


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


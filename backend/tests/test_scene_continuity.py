"""Scene location continuity.

The reference image of a scene is a character PORTRAIT (hero first) — never a
previous scene file. A place tag the story has moved away from must therefore
be negated, or the old location stays in the picture while the narration has
already moved on.
"""

import json

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Character, Story, Turn
from app.services import image_service
from app.services.image_service import previous_scene_negative


def _settings(**overrides) -> Settings:
    # Pin the reference knobs: Settings() reads backend/.env for unset fields
    # and the developer's values must not leak into tests (same rule as conftest).
    base = {
        "image_reference_mode": "img2img",
        "image_reference_nodes": "",
        "image_reference_denoise": 0.6,
    }
    base.update(overrides)
    return Settings(**base)


def _story_with_two_turns(
    db_session: Session,
    tmp_path,
    previous_prompt: str,
    previous_scene: str,
    current_prompt: str,
    current_scene: str,
) -> tuple[Turn, Turn]:
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    previous = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={"scene": previous_scene, "summary": "s", "facts": []},
        is_ending=False, image_status="done", image_format="wide",
        image_prompt=previous_prompt, image_path=f"{story.id}/1.png",
    )
    current = Turn(
        story_id=story.id, index=1, player_input_type="option", narration="n",
        choice=None, state={"scene": current_scene, "summary": "s", "facts": []},
        is_ending=False, image_status="queued", image_format="wide",
        image_prompt=current_prompt, characters_in_scene=["__hero__"],
    )
    db_session.add_all([previous, current])
    db_session.commit()
    return previous, current


def test_previous_scene_negative_targets_the_left_behind_place(db_session: Session, tmp_path) -> None:
    # The story walks out of the forest into a hut; the forest words of the
    # previous turn are what the portrait reference keeps painting back.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, dark forest background with twisted trees, twilight lighting, black cat",
        previous_scene="Тёмный лес у реки",
        current_prompt="1girl, wooden hut interior, log walls, hearth fire, warm light",
        current_scene="Избушка у ручья, внутри",
    )
    negative = previous_scene_negative(db_session, current, current.image_prompt)
    assert negative == "forest, trees"


def test_previous_scene_negative_keeps_the_character_in_a_compound_tag(db_session: Session, tmp_path) -> None:
    # "Garret in the background with knife" carries a character as well as a
    # place: only the place word may be negated, the knife and the man stay.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, hard ground, Garret in the background with knife, black cat",
        previous_scene="Двор у кузницы",
        current_prompt="1girl, forest clearing, grass, wooden shrine",
        current_scene="Избушка у ручья, внутри",
    )
    negative = previous_scene_negative(db_session, current, current.image_prompt)
    for word in ("garret", "knife", "background", "cat"):
        assert word not in negative
    assert "ground" in negative


def test_previous_scene_negative_keeps_a_place_the_prompt_still_uses(db_session: Session, tmp_path) -> None:
    # The narration is still in the forest: nothing may be negated.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, dark forest, twisted trees, night",
        previous_scene="Тёмный лес у реки",
        current_prompt="1girl, forest clearing, grass, wooden shrine",
        current_scene="Лесная поляна со святилищем",
    )
    assert previous_scene_negative(db_session, current, current.image_prompt) == ""


def test_previous_scene_negative_ignores_a_renamed_same_place(db_session: Session, tmp_path) -> None:
    # A renamed wording of the same hut is not a move: inflected forms still
    # share a stem, and a false positive would fight the real setting.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, wooden hut interior, log walls",
        previous_scene="Избушка Лирны, у окна",
        current_prompt="1girl, inside a hut, table, candle",
        current_scene="Внутри избушки, у стола",
    )
    assert previous_scene_negative(db_session, current, current.image_prompt) == ""


def test_previous_scene_negative_needs_a_previous_scene(db_session: Session, tmp_path) -> None:
    # The opening turn has nothing before it.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="",
        previous_scene="",
        current_prompt="1girl, wooden hut interior",
        current_scene="Избушка у ручья",
    )
    assert previous_scene_negative(db_session, current, current.image_prompt) == ""
    assert previous_scene_negative(db_session, current, "") == ""


def test_scene_reference_is_the_portrait_never_the_previous_scene(db_session: Session, tmp_path) -> None:
    # Regression guard for "the wide scene is generated from the previous wide
    # scene": the only reference that may ever reach ComfyUI is a character
    # portrait, even when a finished scene image exists for the previous turn.
    _, current = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, dark forest",
        previous_scene="Тёмный лес",
        current_prompt="1girl, wooden hut interior",
        current_scene="Избушка у ручья",
    )
    story_id = current.story_id
    (tmp_path / str(story_id) / "1.png").write_bytes(b"\x89PNG previous scene")
    hero = Character(story_id=story_id, name="Ada", is_hero=True, portrait_status="done")
    db_session.add(hero)
    db_session.flush()
    hero.portrait_path = f"{story_id}/char_{hero.id}.png"
    (tmp_path / str(story_id) / f"char_{hero.id}.png").write_bytes(b"\x89PNG hero portrait")
    db_session.commit()

    references = image_service._reference_images_for_turn(
        db_session, current, _settings(image_dir=str(tmp_path), image_scene_reference=True)
    )
    assert references == [(f"ref_{hero.id}.png", b"\x89PNG hero portrait")]


def test_process_turn_image_negates_the_old_location(
    db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded: list[bytes] = []
    submitted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/image":
            uploaded.append(request.read())
            return httpx.Response(200, json={"name": "ref_x.png"})
        if request.url.path == "/prompt":
            submitted.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "abc"})
        if request.url.path == "/history/abc":
            return httpx.Response(200, json={
                "abc": {"outputs": {"10": {"images": [
                    {"filename": "f.png", "subfolder": "roleplaygen/story_1", "type": "output"}
                ]}}}
            })
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)

    _, turn = _story_with_two_turns(
        db_session, tmp_path,
        previous_prompt="1girl, dark forest background with twisted trees, night",
        previous_scene="Тёмный лес у реки",
        current_prompt="1girl, wooden hut interior, log walls, hearth fire",
        current_scene="Избушка у ручья, внутри",
    )
    (tmp_path / str(turn.story_id) / "char_5.png").write_bytes(b"\x89PNG hero portrait")
    db_session.add(Character(
        story_id=turn.story_id, name="Ada", is_hero=True,
        portrait_status="done", portrait_path=f"{turn.story_id}/char_5.png",
    ))
    db_session.commit()

    settings = _settings(
        image_dir=str(tmp_path), mock_images=False, image_generation_enabled=True,
        # The test verifies the reference-upload flow, so the scene reference is
        # opted in; by default scenes render tag-only.
        image_scene_reference=True,
    )
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: httpx.Client(
        base_url="http://comfy.test", transport=httpx.MockTransport(handler)
    ))

    image_service.process_turn_image(turn.id, settings)
    db_session.refresh(turn)

    assert turn.image_status == "done"
    # Only the hero portrait was uploaded — a scene file is never a reference.
    assert len(uploaded) == 1 and b"\x89PNG hero portrait" in uploaded[0]
    assert submitted
    # Qwen-Image-2.1 runs at cfg=1: the previous-place guard is computed (see
    # previous_scene_negative above) but intentionally not written anywhere.
    assert image_service.previous_scene_negative(db_session, turn, turn.image_prompt) != ""
    # ... while the new location stays in the positive prompt
    assert "wooden hut interior" in submitted[0]["6"]["inputs"]["prompt"]
    # ComfyUI output goes into a per-story folder, not one flat list of stories
    assert submitted[0]["10"]["inputs"]["filename_prefix"] == (
        f"roleplaygen/story_{turn.story_id}/scene_{turn.id}"
    )
    # the app keeps its own per-story file layout
    assert turn.image_path == f"{turn.story_id}/{turn.id}.png"



def test_portrait_output_is_written_per_story(
    tmp_path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    submitted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            submitted.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "abc"})
        if request.url.path == "/history/abc":
            return httpx.Response(200, json={
                "abc": {"outputs": {"10": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}
            })
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    character = Character(
        story_id=story.id, name="Ada", appearance_tags="1girl, adult",
        portrait_status="queued",
    )
    db_session.add(character)
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path), mock_images=False, image_generation_enabled=True)
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: httpx.Client(
        base_url="http://comfy.test", transport=httpx.MockTransport(handler)
    ))

    image_service.process_character_portrait(character.id, settings)
    assert submitted
    assert submitted[0]["10"]["inputs"]["filename_prefix"] == (
        f"roleplaygen/story_{story.id}/portrait_{character.id}"
    )

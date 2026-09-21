"""Optional reference-image feeding into ComfyUI workflows (spec section 5)."""

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Character, Story, Turn
from app.services import image_service
from app.services.image_service import (
    ImageGenerationError,
    apply_reference_images,
    build_workflow,
    upload_reference_image,
)


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://comfy.test", transport=httpx.MockTransport(handler))


def test_upload_reference_image_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/upload/image"
        return httpx.Response(200, json={"name": "ref_7.png", "subfolder": "", "type": "input"})

    assert upload_reference_image(make_client(handler), b"\x89PNG fake", "ref_7.png") == "ref_7.png"


def test_upload_reference_image_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ImageGenerationError, match="not running"):
        upload_reference_image(make_client(handler), b"x", "r.png")


def _settings(**overrides) -> Settings:
    base = {"image_reference_mode": "img2img", "image_reference_nodes": "20,21"}
    base.update(overrides)
    return Settings(**base)


def test_apply_reference_images_fills_load_image_nodes() -> None:
    workflow = build_workflow("wide", "p", "x")
    workflow["20"] = {"class_type": "LoadImage", "inputs": {"image": "placeholder.png", "upload": True}}
    workflow["21"] = {"class_type": "LoadImage", "inputs": {"image": "placeholder.png", "upload": True}}

    applied = apply_reference_images(workflow, ["ref_1.png", "ref_2.png"], _settings())
    assert applied == 2
    assert workflow["20"]["inputs"]["image"] == "ref_1.png"
    assert workflow["21"]["inputs"]["image"] == "ref_2.png"
    # img2img mode lowers the first sampler's denoise
    assert workflow["3"]["inputs"]["denoise"] == 0.55


def test_apply_reference_images_missing_node_is_skipped() -> None:
    workflow = build_workflow("wide", "p", "x")  # no LoadImage nodes at all
    applied = apply_reference_images(workflow, ["ref_1.png"], _settings())
    assert applied == 0
    assert workflow["3"]["inputs"]["denoise"] == 1  # untouched without a reference


def test_apply_reference_images_off_mode_keeps_denoise() -> None:
    workflow = build_workflow("wide", "p", "x")
    workflow["20"] = {"class_type": "LoadImage", "inputs": {"image": "p.png"}}
    settings = _settings(image_reference_mode="ipadapter", image_reference_nodes="20")
    applied = apply_reference_images(workflow, ["ref_1.png"], settings)
    assert applied == 1
    assert workflow["3"]["inputs"]["denoise"] == 1  # only img2img mode touches it


def test_reference_images_for_turn_collects_scene_portraits(db_session: Session, tmp_path) -> None:
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    (tmp_path / str(story.id) / "char_1.png").write_bytes(b"\x89PNG hero")
    (tmp_path / str(story.id) / "char_2.png").write_bytes(b"\x89PNG friend")
    (tmp_path / str(story.id) / "char_3.png").write_bytes(b"\x89PNG other")
    db_session.add_all([
        Character(story_id=story.id, name="Ada", is_hero=True,
                  portrait_status="done", portrait_path=f"{story.id}/char_1.png"),
        Character(story_id=story.id, name="Kaelen",
                  portrait_status="done", portrait_path=f"{story.id}/char_2.png"),
        Character(story_id=story.id, name="Una", portrait_status="generating",
                  portrait_path=f"{story.id}/char_3.png"),  # not done -> excluded
    ])
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["__hero__", "Kaelen"],
    )
    db_session.add(turn)
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path))
    references = image_service._reference_images_for_turn(db_session, turn, settings)
    assert [name for name, _ in references] == ["ref_1.png", "ref_2.png"]  # hero first

    # off mode -> no references at all
    off = _settings(image_reference_mode="off", image_dir=str(tmp_path))
    assert image_service._reference_images_for_turn(db_session, turn, off) == []

    # no configured nodes -> no references
    none_configured = _settings(image_reference_nodes="", image_dir=str(tmp_path))
    assert image_service._reference_images_for_turn(db_session, turn, none_configured) == []

    # one slot -> one reference
    one_slot = _settings(image_reference_nodes="20", image_dir=str(tmp_path))
    assert len(image_service._reference_images_for_turn(db_session, turn, one_slot)) == 1


def test_process_turn_image_uploads_references(
    db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/image":
            uploaded.append("yes")
            return httpx.Response(200, json={"name": "ref_1.png"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "abc"})
        if request.url.path == "/history/abc":
            return httpx.Response(200, json={
                "abc": {"outputs": {"9": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}
            })
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    (tmp_path / str(story.id) / "char_5.png").write_bytes(b"\x89PNG hero")
    db_session.add(Character(
        story_id=story.id, name="Ada", is_hero=True,
        portrait_status="done", portrait_path=f"{story.id}/char_5.png",
    ))
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="queued",
        image_format="wide", image_prompt="1girl, dock", characters_in_scene=["__hero__"],
    )
    db_session.add(turn)
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path), mock_images=False, image_generation_enabled=True)
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(handler))

    image_service.process_turn_image(turn.id, settings)
    db_session.refresh(turn)
    assert turn.image_status == "done"
    assert uploaded == ["yes"]

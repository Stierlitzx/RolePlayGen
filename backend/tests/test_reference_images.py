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
    # Pin the denoise too: Settings() reads backend/.env for unset fields, and
    # the developer's value must not leak into tests (same rule as conftest).
    base = {
        "image_reference_mode": "img2img",
        "image_reference_nodes": "20,21",
        "image_reference_denoise": 0.6,
        # Scene references are opt-in (they pin the scene to the portrait's
        # crop): these tests pin the switch explicitly on both sides.
        "image_scene_reference": True,
    }
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
    assert workflow["8"]["inputs"]["denoise"] == 0.6


def test_apply_reference_images_missing_node_is_skipped() -> None:
    workflow = build_workflow("wide", "p", "x")  # no hand-added LoadImage nodes
    applied = apply_reference_images(workflow, ["ref_1.png"], _settings())
    # img2img mode does not need configured nodes: it injects its own chain
    assert applied == 1
    assert workflow["90"] == {"class_type": "LoadImage", "inputs": {"image": "ref_1.png"}}
    assert workflow["91"]["class_type"] == "ImageScale"
    assert workflow["91"]["inputs"]["image"] == ["90", 0]
    # the reference is scaled to the canvas the workflow renders at, which the
    # ResolutionSelector computes (the numbers no longer sit in EmptyLatentImage)
    assert workflow["91"]["inputs"]["width"] == image_service.workflow_resolution(workflow, "wide")[0]
    assert workflow["91"]["inputs"]["height"] == image_service.workflow_resolution(workflow, "wide")[1]
    assert workflow["92"] == {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["91", 0], "vae": ["3", 0]},
    }
    # the first sampler now runs img2img off the reference at lowered denoise
    assert workflow["8"]["inputs"]["latent_image"] == ["92", 0]
    assert workflow["8"]["inputs"]["denoise"] == 0.6


def test_apply_reference_images_none_uploaded_keeps_txt2img() -> None:
    workflow = build_workflow("wide", "p", "x")
    applied = apply_reference_images(workflow, [], _settings())
    assert applied == 0
    assert "90" not in workflow  # no chain injected
    assert workflow["8"]["inputs"]["latent_image"] == ["7", 0]
    assert workflow["8"]["inputs"]["denoise"] == 1


def test_apply_reference_images_off_mode_keeps_denoise() -> None:
    workflow = build_workflow("wide", "p", "x")
    workflow["20"] = {"class_type": "LoadImage", "inputs": {"image": "p.png"}}
    settings = _settings(image_reference_mode="ipadapter", image_reference_nodes="20")
    applied = apply_reference_images(workflow, ["ref_1.png"], settings)
    assert applied == 1
    assert workflow["8"]["inputs"]["denoise"] == 1  # only img2img mode touches it


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

    # no configured nodes: opted-in img2img still offers its auto-injected slot,
    # other modes collect nothing
    none_configured = _settings(image_reference_nodes="", image_dir=str(tmp_path))
    assert len(image_service._reference_images_for_turn(db_session, turn, none_configured)) == 1
    none_custom = _settings(
        image_reference_mode="ipadapter", image_reference_nodes="", image_dir=str(tmp_path)
    )
    assert image_service._reference_images_for_turn(db_session, turn, none_custom) == []


def test_scene_image_by_default_uses_no_reference(db_session: Session, tmp_path) -> None:
    # The default scene is composed from the prompt plus the characters' stored
    # appearance tags: no portrait starts the sampler, so the picture cannot
    # inherit the portrait's 4:5 crop or its pose.
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    (tmp_path / str(story.id) / "char_9.png").write_bytes(b"\\x89PNG hero")
    db_session.add(Character(
        story_id=story.id, name="Ada", is_hero=True,
        portrait_status="done", portrait_path=f"{story.id}/char_9.png",
    ))
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["__hero__"],
    )
    db_session.add(turn)
    db_session.commit()

    default = _settings(
        image_scene_reference=False, image_reference_nodes="", image_dir=str(tmp_path)
    )
    assert image_service._reference_images_for_turn(db_session, turn, default) == []


def test_apply_reference_images_latent_opt_out_keeps_txt2img() -> None:
    # The configured LoadImage nodes still receive the picture (a hand-built
    # workflow may want it), but the sampler stays pure txt2img.
    workflow = build_workflow("wide", "p", "x")
    workflow["20"] = {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}}
    settings = _settings(image_reference_nodes="20")
    applied = apply_reference_images(workflow, ["ref_1.png"], settings, as_latent=False)
    assert applied == 1
    assert workflow["20"]["inputs"]["image"] == "ref_1.png"
    assert workflow["8"]["inputs"]["denoise"] == 1  # only an opted-in scene touches it
    assert workflow["8"]["inputs"]["latent_image"] == ["7", 0]
    assert "90" not in workflow  # no chain injected


def test_reference_images_for_turn_respects_slot_count(db_session: Session, tmp_path) -> None:
    # One configured slot keeps one reference even with two portraits done.
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    for filename, data in (( "char_1.png", b"\x89PNG hero"), ("char_2.png", b"\x89PNG npc")):
        (tmp_path / str(story.id) / filename).write_bytes(data)
    db_session.add_all([
        Character(story_id=story.id, name="Ada", is_hero=True,
                  portrait_status="done", portrait_path=f"{story.id}/char_1.png"),
        Character(story_id=story.id, name="Kaelen",
                  portrait_status="done", portrait_path=f"{story.id}/char_2.png"),
    ])
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["__hero__", "Kaelen"],
    )
    db_session.add(turn)
    db_session.commit()

    one_slot = _settings(image_reference_nodes="20", image_dir=str(tmp_path))
    assert len(image_service._reference_images_for_turn(db_session, turn, one_slot)) == 1


def test_hero_listed_by_name_still_leads_references(db_session: Session, tmp_path) -> None:
    # Small narrators often list the hero by NAME instead of the "__hero__"
    # sentinel, and an NPC listed first would take the single img2img slot —
    # the scene would be painted off the wrong face.
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    for filename, data in (("char_1.png", b"\x89PNG hero"), ("char_2.png", b"\x89PNG npc")):
        (tmp_path / str(story.id) / filename).write_bytes(data)
    db_session.add_all([
        Character(story_id=story.id, name="Мира", is_hero=True,
                  portrait_status="done", portrait_path=f"{story.id}/char_1.png"),
        Character(story_id=story.id, name="Kaelen",
                  portrait_status="done", portrait_path=f"{story.id}/char_2.png"),
    ])
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["Kaelen", "Мира"],  # NPC first, hero by name
    )
    db_session.add(turn)
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path))
    references = image_service._reference_images_for_turn(db_session, turn, settings)
    # Hero leads although listed last — the first reference drives img2img.
    assert [name for name, _ in references] == ["ref_1.png", "ref_2.png"]


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
                "abc": {"outputs": {"10": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}
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
def test_reference_images_for_turn_resolves_loose_scene_name(db_session: Session, tmp_path) -> None:
    # The narrator re-titled the character in characters_in_scene ("Странник в
    # чёрном" for the stored "Тайный странник"); the fuzzy matcher must still
    # find the portrait, or the scene is painted from tags alone.
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    (tmp_path / str(story.id) / "char_9.png").write_bytes(b"\x89PNG stranger")
    db_session.add(Character(
        story_id=story.id, name="Тайный странник", appearance_tags="1boy, black coat, adult",
        portrait_status="done", portrait_path=f"{story.id}/char_9.png",
    ))
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False,
        characters_in_scene=["Странник в чёрном"],
    )
    db_session.add(turn)
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path))
    references = image_service._reference_images_for_turn(db_session, turn, settings)
    stranger = db_session.query(Character).filter_by(name="Тайный странник").one()
    assert [name for name, _ in references] == [f"ref_{stranger.id}.png"]
    # ... and the appearance-tag splicing resolves the same loose name.
    _, npc_tags = image_service._scene_appearance_tags(db_session, turn)
    assert npc_tags == ["Black coat"]  # danbooru boilerplate is dropped by clean_phrase

def _portrait_flow_handler(uploaded: list[str], submitted: list[dict]):
    import json as _json

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/image":
            uploaded.append("yes")
            return httpx.Response(200, json={"name": "ref_x.png"})
        if request.url.path == "/prompt":
            submitted.append(_json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "abc"})
        if request.url.path == "/history/abc":
            return httpx.Response(200, json={
                "abc": {"outputs": {"10": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}
            })
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)

    return handler


def test_portrait_regeneration_uses_previous_portrait_as_reference(
    db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A portrait_update repaints the character; the previous portrait must be
    # the picture the new one is EDITED from, or the face drifts into a
    # different person every time the look evolves.
    uploaded: list[str] = []
    submitted: list[dict] = []

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / str(story.id)).mkdir()
    (tmp_path / str(story.id) / "char_7.png").write_bytes(b"\x89PNG old look")
    db_session.add(Character(
        story_id=story.id, name="Ada", appearance_tags="1girl, red cloak, adult",
        portrait_status="queued", portrait_path=f"{story.id}/char_7.png",
        portrait_history=[
            {"appearance_tags": "1girl, adult", "pose": "", "expression": "",
             "portrait_path": f"{story.id}/char_7.png", "turn_id": 1},
            {"appearance_tags": "1girl, red cloak, adult", "pose": "", "expression": "",
             "portrait_path": None, "turn_id": 2},
        ],
    ))
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path), mock_images=False, image_generation_enabled=True)
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(_portrait_flow_handler(uploaded, submitted)))

    character = db_session.query(Character).filter_by(name="Ada").one()
    image_service.process_character_portrait(character.id, settings)

    db_session.refresh(character)
    assert uploaded == ["yes"]
    # The edit graph, not the injected img2img chain: the previous portrait is
    # image_1 and the sampler starts from its encoded latent.
    assert submitted[0]["6"]["inputs"]["images.image_1"] == ["100", 0]
    assert submitted[0]["100"]["inputs"]["image"] == "ref_x.png"  # what ComfyUI stored it as
    assert submitted[0]["9"]["inputs"]["switch"] is True  # a portrait card is 2:3, not the photo's shape
    assert submitted[0]["8"]["inputs"]["latent_image"] == ["9", 0]
    assert "<image1>" in submitted[0]["6"]["inputs"]["prompt"]
    assert character.portrait_status == "done"
    # version 2 saved alongside version 1, which stays on disk for the gallery
    assert character.portrait_path == f"{story.id}/char_{character.id}_v2.png"


def test_first_portrait_stays_txt2img_without_reference(
    db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No previous portrait file yet -> no upload, pure txt2img at full denoise.
    uploaded: list[str] = []
    submitted: list[dict] = []

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    db_session.add(Character(
        story_id=story.id, name="Newcomer", appearance_tags="1boy, adult",
        portrait_status="queued",
    ))
    db_session.commit()

    settings = _settings(image_dir=str(tmp_path), mock_images=False, image_generation_enabled=True)
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(_portrait_flow_handler(uploaded, submitted)))

    character = db_session.query(Character).filter_by(name="Newcomer").one()
    image_service.process_character_portrait(character.id, settings)

    db_session.refresh(character)
    assert uploaded == []
    assert submitted and submitted[0]["8"]["inputs"]["denoise"] == 1
    assert character.portrait_status == "done"


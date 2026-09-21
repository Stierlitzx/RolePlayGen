import httpx
import pytest

from app.config import Settings
from app.services import image_service
from app.services.image_service import (
    ImageGenerationError,
    build_workflow,
    download_image,
    process_turn_image,
    submit_job,
    wait_for_result,
)


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://comfy.test", transport=httpx.MockTransport(handler))


def ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/prompt":
        return httpx.Response(200, json={"prompt_id": "abc-123"})
    if request.url.path == "/history/abc-123":
        return httpx.Response(200, json={
            "abc-123": {"outputs": {"9": {"images": [{"filename": "story_1_2_00001_.png", "subfolder": "", "type": "output"}]}}}
        })
    if request.url.path == "/view":
        return httpx.Response(200, content=b"\x89PNG fake")
    return httpx.Response(404)


def test_submit_success() -> None:
    client = make_client(ok_handler)
    assert submit_job(client, build_workflow("wide", "p", "x")) == "abc-123"


def test_submit_non_200_is_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model file missing"}})

    with pytest.raises(ImageGenerationError, match="rejected the job"):
        submit_job(make_client(handler), build_workflow("wide", "p", "x"))


def test_submit_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ImageGenerationError, match="not running"):
        submit_job(make_client(handler), build_workflow("wide", "p", "x"))


def test_wait_for_result_success() -> None:
    info = wait_for_result(make_client(ok_handler), "abc-123", timeout_seconds=5)
    assert info["filename"] == "story_1_2_00001_.png"


def test_wait_for_result_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(ImageGenerationError, match="timed out"):
        wait_for_result(make_client(handler), "never", timeout_seconds=0)


def test_download_image() -> None:
    data = download_image(make_client(ok_handler), {"filename": "f.png", "subfolder": "", "type": "output"})
    assert data.startswith(b"\x89PNG")


def test_process_turn_image_mock_mode(db_session, tmp_path, monkeypatch) -> None:
    from app.models import Story, Turn
    from sqlalchemy.orm import sessionmaker

    settings = Settings(mock_llm=True, mock_images=True, image_generation_enabled=True, image_dir=str(tmp_path))
    monkeypatch.setattr(image_service.time, "sleep", lambda _: None)
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="queued",
        image_format="wide", image_prompt="1girl, forest",
    )
    db_session.add(turn)
    db_session.commit()

    process_turn_image(turn.id, settings)
    db_session.refresh(turn)
    assert turn.image_status == "done"
    assert turn.image_path == f"{story.id}/{turn.id}.png"
    assert (tmp_path / str(story.id) / f"{turn.id}.png").exists()
    assert turn.image_url == f"/media/{story.id}/{turn.id}.png"


def test_process_turn_image_comfy_down_marks_failed(db_session, tmp_path, monkeypatch) -> None:
    from app.models import Story, Turn
    from sqlalchemy.orm import sessionmaker

    settings = Settings(mock_images=False, image_generation_enabled=True, image_dir=str(tmp_path), comfyui_url="http://127.0.0.1:9")
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="queued",
        image_format="wide", image_prompt="1girl, forest",
    )
    db_session.add(turn)
    db_session.commit()

    process_turn_image(turn.id, settings)
    db_session.refresh(turn)
    assert turn.image_status == "failed"
    assert "not running" in turn.image_error


def test_reset_interrupted_turns(db_session, monkeypatch) -> None:
    from app.models import Story, Turn
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    story = Story(title="t", settings={}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    for i, status in enumerate(["queued", "generating", "done"]):
        db_session.add(Turn(
            story_id=story.id, index=i, player_input_type="start", narration="n",
            choice=None, state={}, is_ending=False, image_status=status,
        ))
    db_session.commit()

    count = image_service.reset_interrupted_turns()
    assert count == 2
    statuses = [t.image_status for t in db_session.query(Turn).order_by(Turn.index).all()]
    assert statuses == ["failed", "failed", "done"]

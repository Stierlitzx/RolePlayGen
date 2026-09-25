import httpx
import pytest

from app.config import Settings
from app.models import Character, Story, Turn
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
            "abc-123": {"outputs": {"10": {"images": [{"filename": "story_1_2_00001_.png", "subfolder": "", "type": "output"}]}}}
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

def test_wait_for_result_timeout_cancels_running_job() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [[0, "abc-123"]], "queue_pending": []})
        return httpx.Response(200, json={})

    client = make_client(handler)
    with pytest.raises(ImageGenerationError, match="timed out"):
        wait_for_result(client, "abc-123", 0)
    assert ("POST", "/queue") in calls  # remove from pending queue
    assert ("POST", "/interrupt") in calls  # it was the running job


def test_wait_for_result_timeout_does_not_interrupt_other_jobs() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [[0, "someone-else"]], "queue_pending": []})
        return httpx.Response(200, json={})

    client = make_client(handler)
    with pytest.raises(ImageGenerationError, match="timed out"):
        wait_for_result(client, "abc-123", 0)
    assert ("POST", "/queue") in calls
    assert ("POST", "/interrupt") not in calls


def test_cancel_job_tolerates_comfy_down() -> None:
    client = httpx.Client(base_url="http://127.0.0.1:9", timeout=1.0)
    image_service.cancel_job(client, "abc-123")  # must not raise


def test_conductor_unload_calls_ollama_keepalive_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(image_service.httpx, "post", lambda *a, **k: calls.append((a, k)))
    image_service._ollama_unload(
        Settings(openai_base_url="http://localhost:11434/v1", openai_model="m:8b")
    )
    assert calls[0][0][0] == "http://localhost:11434/api/generate"  # /v1 stripped
    assert calls[0][1]["json"] == {"model": "m:8b", "keep_alive": 0}


def test_conductor_free_calls_comfyui_free(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(image_service.httpx, "post", lambda *a, **k: calls.append((a, k)))
    image_service._comfyui_free(Settings(comfyui_url="http://127.0.0.1:8188"))
    assert calls[0][0][0] == "http://127.0.0.1:8188/free"
    assert calls[0][1]["json"] == {"unload_models": True, "free_memory": True}


def test_conductor_tolerates_servers_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(image_service.httpx, "post", boom)
    settings = Settings()
    image_service._ollama_unload(settings)  # must not raise
    image_service._comfyui_free(settings)  # must not raise


def test_conductor_skipped_for_mock_images(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Placeholder images use no GPU, so the conductor must stay out of the way.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    from app.models import Story, Turn

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    story = Story(title="t", settings={}, max_turns=None)
    session.add(story)
    session.flush()
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        state={"scene": "s", "summary": "s", "facts": []}, image_prompt="p",
        image_status="queued",
    )
    session.add(turn)
    session.commit()
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=engine))

    calls = []
    monkeypatch.setattr(image_service.httpx, "post", lambda *a, **k: calls.append((a, k)))
    image_service.process_turn_image(
        turn.id,
        Settings(mock_images=True, gpu_vram_conductor=True, image_dir=str(tmp_path)),
    )
    assert calls == []
    session.close()


def _image_settings(**overrides) -> Settings:
    base = {"mock_images": False, "image_generation_enabled": True, "image_timeout_seconds": 5}
    base.update(overrides)
    return Settings(**base)


def test_submit_persists_the_prompt_id_for_restart_adoption(
    db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the ComfyUI job id is known, a restart later can adopt the finished
    # picture instead of throwing it away and painting a second one.
    from sqlalchemy.orm import sessionmaker

    db = db_session
    story = Story(title="t", settings={}, max_turns=None)
    db.add(story)
    db.flush()
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="queued",
        image_format="wide", image_prompt="1girl, forest",
    )
    db.add(turn)
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "job-1"})
        if request.url.path == "/history/job-1":
            return httpx.Response(200, json={"job-1": {"outputs": {"10": {"images": [
                {"filename": "scene.png", "subfolder": "", "type": "output"}]}}}})
        return httpx.Response(200, content=b"\x89PNG fake")

    settings = _image_settings(image_dir=str(tmp_path))
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(handler))
    monkeypatch.setattr(image_service.time, "sleep", lambda _: None)

    process_turn_image(turn.id, settings)
    db.refresh(turn)
    assert turn.image_status == "done"
    assert turn.image_prompt_id is None  # cleared once the job is finished


def test_recovery_state_tells_done_alive_and_lost() -> None:
    def client_for(history=None, queue=None):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/history/"):
                return httpx.Response(200, json=history or {})
            return httpx.Response(
                200, json=queue or {"queue_running": [], "queue_pending": []}
            )

        return make_client(handler)

    done_history = {"job-1": {"outputs": {"10": {"images": [{"filename": "f.png"}]}}}}
    assert image_service.job_recovery_state(client_for(history=done_history), "job-1") == "done"
    queue = {"queue_running": [[3, "job-1"]], "queue_pending": []}
    assert image_service.job_recovery_state(client_for(queue=queue), "job-1") == "alive"
    queue = {"queue_running": [], "queue_pending": [[1, "other"]]}
    assert image_service.job_recovery_state(client_for(queue=queue), "job-1") == "lost"


def test_reset_resumes_a_live_job_instead_of_failing_it(
    db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The app died while ComfyUI was still drawing: the stuck turn must keep
    # saying "Drawing" (queued) and get a resume job — not a Retry button for
    # a picture that is already on its way.
    from sqlalchemy.orm import sessionmaker

    db = db_session
    story = Story(title="t", settings={}, max_turns=None)
    db.add(story)
    db.flush()
    good = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="generating",
        image_format="wide", image_prompt_id="job-alive",
    )
    gone = Turn(
        story_id=story.id, index=1, player_input_type="option", narration="n",
        choice=None, state={}, is_ending=False, image_status="generating",
        image_format="wide", image_prompt_id="job-gone",
    )
    db.add_all([good, gone])
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json={})
        return httpx.Response(
            200, json={"queue_running": [[3, "job-alive"]], "queue_pending": []}
        )

    settings = _image_settings(image_dir=str(tmp_path))
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(handler))

    recovered = image_service.reset_interrupted_turns(settings)
    assert recovered == 2
    db.refresh(good)
    db.refresh(gone)
    assert good.image_status == "queued"  # ComfyUI has it: keep waiting
    assert good.image_prompt_id == "job-alive"
    jobs = []
    while not image_service._job_queue.empty():
        jobs.append(image_service._job_queue.get_nowait())
    assert ("resume_scene", good.id) in jobs
    assert gone.image_status == "failed"  # ComfyUI forgot it: honest Retry
    assert gone.image_prompt_id is None


def test_resume_adopts_the_finished_picture(
    db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The interrupted job is already DONE on the ComfyUI side: the resumed
    # worker adopts that file instead of painting a second picture.
    from sqlalchemy.orm import sessionmaker

    db = db_session
    story = Story(title="t", settings={}, max_turns=None)
    db.add(story)
    db.flush()
    turn = Turn(
        story_id=story.id, index=0, player_input_type="start", narration="n",
        choice=None, state={}, is_ending=False, image_status="queued",
        image_format="wide", image_prompt="1girl, forest", image_prompt_id="job-done",
    )
    db.add(turn)
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json={
                "job-done": {"outputs": {"10": {"images": [
                    {"filename": "scene.png", "subfolder": "", "type": "output"}
                ]}}}
            })
        return httpx.Response(200, content=b"\x89PNG fake")

    settings = _image_settings(image_dir=str(tmp_path))
    monkeypatch.setattr(image_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(image_service, "_client", lambda s: make_client(handler))

    image_service.resume_turn_image(turn.id, settings)
    db.refresh(turn)
    assert turn.image_status == "done"
    assert turn.image_path == f"{story.id}/{turn.id}.png"
    assert turn.image_prompt_id is None
    assert (tmp_path / str(story.id) / f"{turn.id}.png").exists()



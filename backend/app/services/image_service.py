"""Background scene illustrations via a local ComfyUI server.

One in-process queue with a single worker: jobs run strictly one at a time.
Failures never propagate into the text flow — they are stored on the turn.
"""

import copy
import json
import logging
import queue
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models import Character, Turn

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "comfy_workflows"
FORMATS = ("portrait", "wide")
REQUIRED_NODES = {"6": "CLIPTextEncode", "7": "CLIPTextEncode", "3": "KSampler", "13": "KSampler", "9": "SaveImage"}

QUALITY_PREFIX = ["masterpiece", "best quality", "amazing quality", "general"]
PORTRAIT_SUFFIX = ["portrait", "close-up", "looking at viewer", "simple background"]
BANNED_TOKENS = {
    "masterpiece", "best quality", "amazing quality", "general",
    "nsfw", "explicit", "questionable", "sensitive",
}
PERSON_TAGS = {"1girl", "1boy", "2girls", "2boys", "1other", "multiple girls", "multiple boys"}


class ImageGenerationError(RuntimeError):
    pass


def sanitize_tags(image_prompt: str) -> list[str]:
    """Split the narrator tags, trim them and drop quality/rating tokens."""
    tags = []
    for raw in image_prompt.split(","):
        tag = raw.strip()
        if tag and tag.lower() not in BANNED_TOKENS:
            tags.append(tag)
    return tags


def assemble_positive_prompt(
    image_prompt: str,
    hero_tags: str = "",
    character_tags: list[str] | None = None,
) -> str:
    """Scene prompt: quality prefix, then known appearance tags (hero first,
    then the other characters in scene order), then the narrator's tags.

    Appearance is spliced in by the backend so a character keeps the same look
    across turns even though the text model has no memory between generations.
    """
    parts: list[str] = list(QUALITY_PREFIX)
    if hero_tags.strip():
        parts.append(hero_tags.strip())
    for tags in character_tags or []:
        if tags.strip():
            parts.append(tags.strip())
    tags = sanitize_tags(image_prompt)
    lowered = {t.lower() for t in tags}
    if lowered & PERSON_TAGS and "adult" not in lowered:
        tags.append("adult")
    parts.extend(tags)
    prompt = ", ".join(parts)
    logger.debug("image prompt: %s", prompt)
    return prompt


def assemble_portrait_prompt(appearance_tags: str) -> str:
    """Portrait prompt: quality prefix + the character's own tags + framing."""
    parts: list[str] = list(QUALITY_PREFIX)
    tags = sanitize_tags(appearance_tags)
    lowered = {t.lower() for t in tags}
    if lowered & PERSON_TAGS and "adult" not in lowered:
        tags.append("adult")
    parts.extend(tags)
    parts.extend(PORTRAIT_SUFFIX)
    prompt = ", ".join(parts)
    logger.debug("portrait prompt: %s", prompt)
    return prompt


def load_workflow(image_format: str) -> dict[str, Any]:
    if image_format not in FORMATS:
        image_format = "wide"
    path = WORKFLOWS_DIR / f"{image_format}.json"
    if not path.exists():
        raise ImageGenerationError(f"Workflow file not found: {path}")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node_id, class_type in REQUIRED_NODES.items():
        node = workflow.get(node_id)
        if node is None or node.get("class_type") != class_type:
            raise ImageGenerationError(
                f"Workflow {path.name} is missing required node {node_id} ({class_type})"
            )
    return workflow


def build_workflow(
    image_format: str,
    positive_prompt: str,
    filename_prefix: str,
    seed: int | None = None,
) -> dict[str, Any]:
    workflow = copy.deepcopy(load_workflow(image_format))
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    workflow["6"]["inputs"]["text"] = positive_prompt
    workflow["3"]["inputs"]["seed"] = seed
    workflow["13"]["inputs"]["seed"] = seed
    workflow["9"]["inputs"]["filename_prefix"] = filename_prefix
    return workflow


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(base_url=settings.comfyui_url, timeout=30.0)


def submit_job(client: httpx.Client, workflow: dict[str, Any]) -> str:
    try:
        response = client.post("/prompt", json={"prompt": workflow, "client_id": str(uuid.uuid4())})
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"ComfyUI rejected the job ({response.status_code}): {response.text[:300]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise ImageGenerationError("ComfyUI did not return a prompt_id")
    return str(prompt_id)


def wait_for_result(client: httpx.Client, prompt_id: str, timeout_seconds: int) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(f"/history/{prompt_id}")
        except httpx.HTTPError as exc:
            raise ImageGenerationError("Image generator is not running") from exc
        if response.status_code == 200:
            history = response.json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                images = outputs.get("9", {}).get("images", [])
                if images:
                    return images[0]
                raise ImageGenerationError("ComfyUI finished but produced no image")
        time.sleep(1.5)
    raise ImageGenerationError(f"Image generation timed out after {timeout_seconds}s")


def download_image(client: httpx.Client, image_info: dict[str, str]) -> bytes:
    try:
        response = client.get("/view", params={
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        })
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"Could not download image ({response.status_code})")
    return response.content


# ---------------------------------------------------------------------------
# Optional reference images (character portraits fed back into the workflow)
# ---------------------------------------------------------------------------

def reference_node_ids(settings: Settings) -> list[str]:
    return [node.strip() for node in settings.image_reference_nodes.split(",") if node.strip()]


def upload_reference_image(client: httpx.Client, data: bytes, filename: str) -> str:
    """Upload a reference image to ComfyUI, returns the stored file name."""
    try:
        response = client.post(
            "/upload/image",
            files={"image": (filename, data, "image/png")},
            data={"overwrite": "true"},
        )
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"ComfyUI refused the reference image ({response.status_code})")
    name = response.json().get("name")
    if not name:
        raise ImageGenerationError("ComfyUI did not return a name for the uploaded reference")
    return str(name)


def apply_reference_images(
    workflow: dict[str, Any],
    uploaded_names: list[str],
    settings: Settings,
) -> int:
    """Point the configured LoadImage nodes at the uploaded references.

    One node per reference slot; extra references are dropped, missing or
    non-LoadImage nodes are skipped with a warning (generation continues
    without a reference rather than failing the job). In "img2img" mode the
    first sampler's denoise is lowered so the reference drives the look.
    """
    applied = 0
    for node_id, name in zip(reference_node_ids(settings), uploaded_names):
        node = workflow.get(node_id)
        if node is None or node.get("class_type") != "LoadImage":
            logger.warning("reference node %s is missing or not a LoadImage node; skipping", node_id)
            continue
        node.setdefault("inputs", {})["image"] = name
        applied += 1
    if applied and settings.image_reference_mode == "img2img":
        workflow["3"]["inputs"]["denoise"] = settings.image_reference_denoise
    if len(uploaded_names) > applied:
        logger.info("dropped %d reference image(s): not enough LoadImage nodes", len(uploaded_names) - applied)
    return applied


def _reference_images_for_turn(db: Any, turn: Turn, settings: Settings) -> list[tuple[str, bytes]]:
    """Portraits of the characters in this scene, hero first, as (name, bytes)."""
    if settings.image_reference_mode == "off":
        return []
    node_count = len(reference_node_ids(settings))
    if node_count == 0:
        return []
    characters = db.query(Character).filter(
        Character.story_id == turn.story_id,
        Character.portrait_status == "done",
        Character.portrait_path.isnot(None),
    ).all()
    if not characters:
        return []
    by_name = {character.name.lower(): character for character in characters}
    ordered: list[Character] = []
    hero = next((c for c in characters if c.is_hero), None)
    names = turn.characters_in_scene or []
    if hero and (not names or "__hero__" in names):
        ordered.append(hero)
    for name in names:
        character = by_name.get(str(name).lower())
        if character and character not in ordered:
            ordered.append(character)
    if not names and hero is None:
        ordered = characters  # no scene info: fall back to any known portraits
    references: list[tuple[str, bytes]] = []
    for character in ordered[:node_count]:
        path = Path(settings.image_dir) / str(character.portrait_path)
        try:
            references.append((f"ref_{character.id}.png", path.read_bytes()))
        except OSError:
            logger.warning("portrait file missing for character %s: %s", character.id, path)
    return references


def _mock_png(path: Path) -> None:
    """Tiny valid 1x1 PNG placeholder written without extra dependencies."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x40\x30\x50")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def save_image(data: bytes, settings: Settings, story_id: int, turn_id: int) -> str:
    directory = Path(settings.image_dir) / str(story_id)
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"{story_id}/{turn_id}.png"
    (Path(settings.image_dir) / relative).write_bytes(data)
    return relative


def save_portrait(data: bytes, settings: Settings, story_id: int, character_id: int) -> str:
    directory = Path(settings.image_dir) / str(story_id)
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"{story_id}/char_{character_id}.png"
    (Path(settings.image_dir) / relative).write_bytes(data)
    return relative


# ---------------------------------------------------------------------------
# Queue with a single worker thread (one ComfyUI job at a time).
# Jobs are (job_type, ref_id): ("scene", turn_id) or ("portrait", character_id).
# ---------------------------------------------------------------------------

_JOB_STOP = ("stop", -1)
_job_queue: queue.Queue[tuple[str, int]] = queue.Queue()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_running = False


def enqueue_turn_image(turn_id: int) -> None:
    _job_queue.put(("scene", turn_id))


def enqueue_portrait(character_id: int) -> None:
    _job_queue.put(("portrait", character_id))


def start_worker() -> None:
    global _worker_thread, _worker_running
    with _worker_lock:
        if _worker_running:
            return
        _worker_running = True
        _worker_thread = threading.Thread(target=_worker_loop, name="image-worker", daemon=True)
        _worker_thread.start()


def stop_worker() -> None:
    global _worker_running
    with _worker_lock:
        _worker_running = False
    _job_queue.put(_JOB_STOP)  # wake the worker so it can exit


def _worker_loop() -> None:
    while _worker_running:
        job = _job_queue.get()
        if job == _JOB_STOP:
            break
        job_type, ref_id = job
        try:
            if job_type == "portrait":
                process_character_portrait(ref_id)
            else:
                process_turn_image(ref_id)
        except Exception:
            logger.exception("image job failed: %s %s", job_type, ref_id)
        finally:
            _job_queue.task_done()


def _get_with_retry(db: Any, model: type, row_id: int) -> Any:
    """Jobs are enqueued just before the turn transaction commits, so the row
    may not be visible to the worker's session yet — wait briefly for it."""
    for attempt in range(10):
        row = db.get(model, row_id)
        if row is not None:
            return row
        if attempt < 9:
            time.sleep(0.3)
    return None


def process_turn_image(turn_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        turn = _get_with_retry(db, Turn, turn_id)
        if turn is None or not turn.image_prompt:
            return
        turn.image_status = "generating"
        turn.image_error = None
        db.commit()
        try:
            if settings.mock_images:
                time.sleep(3)
                directory = Path(settings.image_dir) / str(turn.story_id)
                directory.mkdir(parents=True, exist_ok=True)
                relative = f"{turn.story_id}/{turn.id}.png"
                _mock_png(Path(settings.image_dir) / relative)
            else:
                hero_tags, character_tags = _scene_appearance_tags(db, turn)
                workflow = build_workflow(
                    turn.image_format or "wide",
                    assemble_positive_prompt(turn.image_prompt, hero_tags, character_tags),
                    filename_prefix=f"story_{turn.story_id}_{turn.id}",
                )
                references = _reference_images_for_turn(db, turn, settings)
                with _client(settings) as client:
                    if references:
                        uploaded = [
                            upload_reference_image(client, data, filename)
                            for filename, data in references
                        ]
                        apply_reference_images(workflow, uploaded, settings)
                    prompt_id = submit_job(client, workflow)
                    image_info = wait_for_result(client, prompt_id, settings.image_timeout_seconds)
                    data = download_image(client, image_info)
                relative = save_image(data, settings, turn.story_id, turn.id)
            turn.image_status = "done"
            turn.image_path = relative
        except ImageGenerationError as exc:
            turn.image_status = "failed"
            turn.image_error = str(exc)
        db.commit()
    finally:
        db.close()


def _scene_appearance_tags(db: Any, turn: Turn) -> tuple[str, list[str]]:
    """Hero tags plus the tags of every named character in the scene.

    With no `characters_in_scene` this falls back to hero-only, exactly the
    behavior before character tracking existed.
    """
    characters = db.query(Character).filter(Character.story_id == turn.story_id).all()
    hero = next((c for c in characters if c.is_hero), None)
    hero_tags = (hero.appearance_tags or "") if hero else ""
    names = turn.characters_in_scene or []
    if not names:
        return hero_tags, []
    by_name = {c.name.lower(): c for c in characters if not c.is_hero}
    tags: list[str] = []
    for name in names:
        if str(name) == "__hero__":
            continue  # hero tags are already first
        character = by_name.get(str(name).lower())
        if character and character.appearance_tags:
            tags.append(character.appearance_tags)
    return hero_tags, tags


def process_character_portrait(character_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        character = _get_with_retry(db, Character, character_id)
        if character is None or not character.appearance_tags:
            return
        character.portrait_status = "generating"
        character.portrait_error = None
        db.commit()
        try:
            if settings.mock_images:
                time.sleep(3)
                relative = f"{character.story_id}/char_{character.id}.png"
                directory = Path(settings.image_dir) / str(character.story_id)
                directory.mkdir(parents=True, exist_ok=True)
                _mock_png(Path(settings.image_dir) / relative)
            else:
                workflow = build_workflow(
                    "portrait",
                    assemble_portrait_prompt(character.appearance_tags),
                    filename_prefix=f"story_{character.story_id}_char_{character.id}",
                )
                with _client(settings) as client:
                    prompt_id = submit_job(client, workflow)
                    image_info = wait_for_result(client, prompt_id, settings.image_timeout_seconds)
                    data = download_image(client, image_info)
                relative = save_portrait(data, settings, character.story_id, character.id)
            character.portrait_status = "done"
            character.portrait_path = relative
        except ImageGenerationError as exc:
            character.portrait_status = "failed"
            character.portrait_error = str(exc)
        db.commit()
    finally:
        db.close()


def reset_interrupted_turns() -> int:
    """On startup: turns and characters stuck in queued/generating become failed."""
    db = SessionLocal()
    try:
        stuck_turns = db.query(Turn).filter(Turn.image_status.in_(["queued", "generating"])).all()
        for turn in stuck_turns:
            turn.image_status = "failed"
            turn.image_error = "Interrupted"
        stuck_portraits = db.query(Character).filter(
            Character.portrait_status.in_(["queued", "generating"])
        ).all()
        for character in stuck_portraits:
            character.portrait_status = "failed"
            character.portrait_error = "Interrupted"
        db.commit()
        return len(stuck_turns) + len(stuck_portraits)
    finally:
        db.close()


def retry_turn_image(turn_id: int) -> Turn:
    db = SessionLocal()
    try:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise ImageGenerationError("Turn not found")
        if turn.image_status != "failed":
            raise ImageGenerationError("Only a failed image can be retried")
        turn.image_status = "queued"
        turn.image_error = None
        db.commit()
        enqueue_turn_image(turn.id)
        db.refresh(turn)
        return turn
    finally:
        db.close()


def retry_character_portrait(character_id: int) -> Character:
    db = SessionLocal()
    try:
        character = db.get(Character, character_id)
        if character is None:
            raise ImageGenerationError("Character not found")
        if character.portrait_status != "failed":
            raise ImageGenerationError("Only a failed portrait can be retried")
        character.portrait_status = "queued"
        character.portrait_error = None
        db.commit()
        enqueue_portrait(character.id)
        db.refresh(character)
        return character
    finally:
        db.close()



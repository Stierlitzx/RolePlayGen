from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Turn
from ..schemas import ScenePromptUpdate
from ..services import image_service

router = APIRouter(prefix="/api/turns", tags=["images"])


def _image_payload(turn: Turn) -> dict:
    return {
        "status": turn.image_status,
        "format": turn.image_format,
        "url": turn.image_url,
        "error": turn.image_error,
        "progress": turn.image_progress,
    }


@router.get("/{turn_id}/image")
def get_turn_image(turn_id: int, db: Session = Depends(get_db)) -> dict:
    turn = db.get(Turn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    return _image_payload(turn)


@router.post("/{turn_id}/image/redo")
def redo_image(turn_id: int, db: Session = Depends(get_db)) -> dict:
    """Repaint a turn's illustration from the SAME stored scene prompt.

    The button a player needs after a prompt/style change: the old picture was
    made by an older prompt, and only a new job (with a new seed, the current
    art style and a fresh log) shows what the model would draw now. The previous
    file is replaced, exactly like a regeneration of the turn itself.

    The old build log is cleared on purpose: a re-queued job reuses the seed its
    log records (so an interrupted picture comes back as itself), and a repaint
    must NOT reuse it — that is the whole point of pressing the button.
    """
    turn = db.get(Turn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    if not (turn.image_prompt or "").strip():
        raise HTTPException(status_code=400, detail="This turn has no picture to repaint.")
    turn.image_status = "queued"
    turn.image_error = None
    turn.image_build_log = None  # a new picture wants a new seed, so a new log
    turn.image_prompt_id = None  # a redo is a NEW job, never an adoption
    db.commit()
    image_service.enqueue_turn_image(turn.id)
    db.refresh(turn)
    return _image_payload(turn)


@router.patch("/{turn_id}/image/prompt")
def update_scene_prompt(
    turn_id: int, payload: ScenePromptUpdate, db: Session = Depends(get_db)
) -> dict:
    """Store the player's own scene wording (or clear it) and repaint.

    The override is a PICTURE setting: the narration, the choice and the story
    state are untouched, so a picture the narrator framed badly can be re-aimed
    without rewriting the turn. An empty prompt clears the override, and the
    next picture goes back to the narrator's own words.
    """
    turn = db.get(Turn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    if not (turn.image_prompt or "").strip():
        raise HTTPException(status_code=400, detail="This turn has no picture to aim.")
    override = payload.prompt.strip()
    if not (override or turn.image_prompt_override):
        raise HTTPException(
            status_code=400, detail="Write a prompt, or restore the narrator's own."
        )
    turn.image_prompt_override = override or None
    turn.image_status = "queued"
    turn.image_error = None
    turn.image_build_log = None  # a new picture wants a new seed, so a new log
    turn.image_prompt_id = None
    db.commit()
    image_service.enqueue_turn_image(turn.id)
    db.refresh(turn)
    return _image_payload(turn)



@router.post("/{turn_id}/image/retry")
def retry_image(turn_id: int, db: Session = Depends(get_db)) -> dict:
    turn = db.get(Turn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    if turn.image_status != "failed":
        raise HTTPException(status_code=400, detail="Only a failed image can be retried.")
    turn.image_status = "queued"
    turn.image_error = None
    db.commit()
    image_service.enqueue_turn_image(turn.id)
    db.refresh(turn)
    return _image_payload(turn)

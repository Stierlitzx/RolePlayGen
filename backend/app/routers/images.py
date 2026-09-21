from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Turn
from ..services import image_service

router = APIRouter(prefix="/api/turns", tags=["images"])


def _image_payload(turn: Turn) -> dict:
    return {
        "status": turn.image_status,
        "format": turn.image_format,
        "url": turn.image_url,
        "error": turn.image_error,
    }


@router.get("/{turn_id}/image")
def get_turn_image(turn_id: int, db: Session = Depends(get_db)) -> dict:
    turn = db.get(Turn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
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

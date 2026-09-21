from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Character, Story
from ..schemas import CharacterRead
from ..services import image_service

router = APIRouter(prefix="/api", tags=["characters"])


@router.get("/stories/{story_id}/characters", response_model=list[CharacterRead])
def list_characters(story_id: int, db: Session = Depends(get_db)) -> list[Character]:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found.")
    # Hero first (pinned), then the rest in order of appearance.
    return sorted(story.characters, key=lambda c: (not c.is_hero, c.id))


@router.get("/characters/{character_id}", response_model=CharacterRead)
def get_character(character_id: int, db: Session = Depends(get_db)) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    return character


@router.post("/characters/{character_id}/portrait/retry", response_model=CharacterRead)
def retry_portrait(character_id: int, db: Session = Depends(get_db)) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    if character.portrait_status != "failed":
        raise HTTPException(status_code=400, detail="Only a failed portrait can be retried.")
    character.portrait_status = "queued"
    character.portrait_error = None
    db.commit()
    image_service.enqueue_portrait(character.id)
    db.refresh(character)
    return character

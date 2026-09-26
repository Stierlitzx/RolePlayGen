from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Character, Story
from ..schemas import CharacterLookUpdate, CharacterRead, PortraitUpload
from ..services import image_service, story_engine

router = APIRouter(prefix="/api", tags=["characters"])


@router.get("/stories/{story_id}/characters", response_model=list[CharacterRead])
def list_characters(story_id: int, db: Session = Depends(get_db)) -> list[Character]:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found.")
    # Hero first (pinned), then the rest in order of appearance.
    return sorted(story.characters, key=lambda c: (not c.is_hero, c.id))


@router.get("/characters/{character_id}", response_model=CharacterRead)
def get_character(
    character_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    image_service.ensure_portrait_build_logs([character], settings)
    return character


@router.post("/characters/{character_id}/portrait", response_model=CharacterRead)
def upload_character_photo(
    character_id: int,
    payload: PortraitUpload,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Character:
    """The player's own picture for a character (the Characters tab).

    The file is kept as `photo_path` — the picture generator edits it (image_1)
    and uses it as a reference in every scene — and, with `use_as_portrait`,
    it also becomes the character's current portrait immediately: no GPU job,
    the player sees their own picture right away.
    """
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    try:
        data = image_service.decode_upload(payload.image)
    except image_service.ImageGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    relative = image_service.save_upload(
        data, settings, character.story_id, f"photo_{character.id}.png"
    )
    character.photo_path = relative
    # A replaced photo is new bytes behind the same path, so the URLs (the photo
    # and, when reused, the portrait card) have to change or the browser keeps
    # showing the face the player just replaced.
    character.portrait_version = int(character.portrait_version or 0) + 1
    if payload.use_as_portrait:
        character.portrait_path = relative
        character.portrait_status = "done"
        character.portrait_error = None
        character.portrait_prompt_id = None
        look, pose, expression = image_service._current_look(character)
        # APPEND, never replace: the previous generated look stays in the
        # gallery and stays available for `portrait_revert`, and the feed's
        # "New look" row still knows this portrait belongs to this turn.
        character.portrait_history = [
            *(character.portrait_history or []),
            {
                "appearance_tags": look,
                "pose": pose,
                "expression": expression,
                "portrait_path": relative,
                "turn_id": character.first_seen_turn_id,
            },
        ]
    db.commit()
    db.refresh(character)
    return character


@router.post("/characters/{character_id}/portrait/redo", response_model=CharacterRead)
def redo_portrait(character_id: int, db: Session = Depends(get_db)) -> Character:
    """Repaint a portrait that already exists (same rules as the turn redo).

    Needed after any prompt or style change: the card still shows the picture the
    OLD prompt produced. The new job writes a new history version, so the
    previous look stays in "Past looks" instead of being overwritten.
    """
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    if not (character.appearance_tags or "").strip():
        raise HTTPException(status_code=400, detail="This character has no look to paint yet.")
    character.portrait_status = "queued"
    character.portrait_error = None
    character.portrait_build_log = None  # a repaint wants a new seed, so a new log
    character.portrait_prompt_id = None
    db.commit()
    image_service.enqueue_portrait(character.id)
    db.refresh(character)
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


@router.patch("/characters/{character_id}/look", response_model=CharacterRead)
def update_character_look(
    character_id: int,
    payload: CharacterLookUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Character:
    """The player rewriting a character's look, then repainting the card.

    The narrator owns the look by default, but a portrait the player dislikes is
    theirs to fix — so free text in, a new look stored, one portrait job queued.
    The change follows the same rules as a narrator-driven `portrait_update`:
    with `keep_history` the previous look stays in "Past looks" and can be
    restored, and every later scene splices the new look instead of the old one.
    With `keep_history=false` the current look is rewritten in place, so a player
    iterating on a prompt does not fill the gallery with near-identical versions.
    """
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    new_tags = payload.appearance_tags.strip()
    if not new_tags:
        raise HTTPException(status_code=400, detail="Describe the new look.")

    if payload.keep_history:
        history = story_engine.init_portrait_history(character)
        history.append(story_engine.portrait_history_entry(new_tags, None, None, None, None))
        character.portrait_history = history
    else:
        character.portrait_history = story_engine.replace_current_look(character, new_tags)
    character.appearance_tags = new_tags
    character.portrait_build_log = None  # a new picture wants a new seed
    if payload.repaint and settings.image_generation_enabled:
        character.portrait_status = "queued"
        character.portrait_error = None
        character.portrait_prompt_id = None
        db.commit()
        image_service.enqueue_portrait(character.id)
    db.commit()
    db.refresh(character)
    return character


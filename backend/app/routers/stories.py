from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Story
from ..schemas import SetupOptions, StoryCreate, StoryRead, StorySummary, StoryUpdate, TurnCreate, TurnRead
from ..services import story_engine
from ..setup_options import (
    CULTURE_OPTIONS,
    GENRE_OPTIONS,
    LANGUAGE_OPTIONS,
    LENGTH_OPTIONS,
    MAX_GENRES,
    MODEL_OPTIONS,
    SETTING_OPTIONS,
    TONE_OPTIONS,
)

router = APIRouter(prefix="/api", tags=["stories"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/setup-options", response_model=SetupOptions)
def setup_options(settings: Settings = Depends(get_settings)) -> SetupOptions:
    return SetupOptions(
        settings=SETTING_OPTIONS,
        genres=GENRE_OPTIONS,
        tones=TONE_OPTIONS,
        lengths=LENGTH_OPTIONS,
        languages=LANGUAGE_OPTIONS,
        cultures=CULTURE_OPTIONS,
        max_genres=MAX_GENRES,
        models=MODEL_OPTIONS,
        default_model=settings.model_name,
        ai_configured=bool(settings.gemini_api_key),
        mock_llm=settings.mock_llm,
    )


@router.get("/stories", response_model=list[StorySummary])
def list_stories(db: Session = Depends(get_db)) -> list[StorySummary]:
    stories = story_engine.list_stories(db)
    return [
        StorySummary(
            id=story.id,
            title=story.title,
            settings=story.settings,
            status=story.status,
            max_turns=story.max_turns,
            created_at=story.created_at,
            updated_at=story.updated_at,
            turn_count=len(story.turns),
        )
        for story in stories
    ]


@router.post("/stories", response_model=StoryRead, status_code=201)
def create_story(
    payload: StoryCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Story:
    return story_engine.create_story(db, payload, settings)


@router.get("/stories/{story_id}", response_model=StoryRead)
def get_story(story_id: int, db: Session = Depends(get_db)) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise story_engine.StoryNotFoundError("Story not found.")
    return story


@router.patch("/stories/{story_id}", response_model=StoryRead)
def update_story(
    story_id: int,
    payload: StoryUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Story:
    return story_engine.update_story(db, story_id, payload, settings)


@router.post("/stories/{story_id}/regenerate-start", response_model=StoryRead)
def regenerate_story_start(
    story_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Story:
    return story_engine.regenerate_start(db, story_id, settings)


@router.post("/stories/{story_id}/turns", response_model=TurnRead, status_code=201)
def create_turn(
    story_id: int,
    payload: TurnCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> object:
    return story_engine.add_turn(db, story_id, payload, settings)


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(story_id: int, db: Session = Depends(get_db)) -> Response:
    story = db.get(Story, story_id)
    if story is None:
        raise story_engine.StoryNotFoundError("Story not found.")
    db.delete(story)
    db.commit()
    return Response(status_code=204)

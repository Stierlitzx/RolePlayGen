import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Story
from ..schemas import (
    PinnedFactsRead,
    SetupOptions,
    StoryCreate,
    StoryRead,
    StorySummary,
    StoryUpdate,
    TurnCreate,
    TurnRead,
)
from ..services import image_service, story_engine
from ..setup_options import (
    ADULT_GENRE_OPTIONS,
    AGE_RATING_OPTIONS,
    CULTURE_OPTIONS,
    DEFAULT_AGE_RATING,
    DEFAULT_HERO_GENDER,
    DEFAULT_IMAGE_STYLE,
    DEFAULT_NARRATOR_STYLE,
    GENRE_OPTIONS,
    HERO_GENDER_OPTIONS,
    IMAGE_STYLE_OPTIONS,
    LANGUAGE_OPTIONS,
    LENGTH_OPTIONS,
    MAX_GENRES,
    MODEL_OPTIONS,
    NARRATOR_STYLE_OPTIONS,
    SETTING_OPTIONS,
    TONE_OPTIONS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stories"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/setup-options", response_model=SetupOptions)
def setup_options(settings: Settings = Depends(get_settings)) -> SetupOptions:
    # All configured providers are served side by side: the player picks the
    # text model source per story in the setup form. The legacy fields
    # `models`, `default_model` and `ai_configured` keep following the
    # server-wide LLM_PROVIDER for clients that predate the provider picker.
    provider = (settings.llm_provider or "gemini").lower()
    is_gemini = provider == "gemini"
    local_configured = bool(settings.openai_base_url)
    groq_configured = bool(settings.groq_api_key)
    openrouter_configured = bool(settings.openrouter_api_key)
    mistral_configured = bool(settings.mistral_api_key)
    legacy_model = {
        "gemini": settings.model_name,
        "groq": settings.groq_model,
        "openrouter": settings.openrouter_model,
        "mistral": settings.mistral_model,
    }.get(provider, settings.openai_model)
    legacy_ready = {
        "gemini": bool(settings.gemini_api_key),
        "groq": groq_configured,
        "openrouter": openrouter_configured,
        "mistral": mistral_configured,
    }.get(provider, local_configured)
    default_provider = (
        provider if provider in ("gemini", "groq", "openrouter", "mistral") else "local"
    )
    return SetupOptions(
        settings=SETTING_OPTIONS,
        genres=GENRE_OPTIONS,
        tones=TONE_OPTIONS,
        lengths=LENGTH_OPTIONS,
        languages=LANGUAGE_OPTIONS,
        cultures=CULTURE_OPTIONS,
        max_genres=MAX_GENRES,
        age_ratings=AGE_RATING_OPTIONS,
        adult_genres=ADULT_GENRE_OPTIONS,
        image_styles=IMAGE_STYLE_OPTIONS,
        narrator_styles=NARRATOR_STYLE_OPTIONS,
        default_age_rating=DEFAULT_AGE_RATING,
        default_image_style=DEFAULT_IMAGE_STYLE,
        default_narrator_style=DEFAULT_NARRATOR_STYLE,
        models=MODEL_OPTIONS if is_gemini else [legacy_model],
        default_model=settings.model_name if is_gemini else legacy_model,
        ai_configured=legacy_ready,
        mock_llm=settings.mock_llm,
        default_provider=default_provider,
        gemini_models=MODEL_OPTIONS,
        default_gemini_model=settings.model_name,
        gemini_configured=bool(settings.gemini_api_key),
        local_model=settings.openai_model if local_configured else None,
        local_configured=local_configured,
        groq_model=settings.groq_model if groq_configured else None,
        groq_configured=groq_configured,
        openrouter_model=settings.openrouter_model if openrouter_configured else None,
        openrouter_configured=openrouter_configured,
        mistral_model=settings.mistral_model if mistral_configured else None,
        mistral_configured=mistral_configured,
        hero_genders=HERO_GENDER_OPTIONS,
        default_hero_gender=DEFAULT_HERO_GENDER,
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
def get_story(
    story_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise story_engine.StoryNotFoundError("Story not found.")
    # Every picture gets a log, including the ones drawn before logging existed.
    image_service.ensure_build_logs(db, list(story.turns), settings)
    image_service.ensure_portrait_build_logs(list(story.characters), settings)
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


@router.post("/stories/{story_id}/regenerate-last", response_model=StoryRead)
def regenerate_last_story_turn(
    story_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Story:
    return story_engine.regenerate_last_turn(db, story_id, settings)


@router.post("/stories/{story_id}/turns", response_model=TurnRead, status_code=201)
def create_turn(
    story_id: int,
    payload: TurnCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> object:
    turn = story_engine.add_turn(db, story_id, payload, settings)
    # The new turn is appended to the story in the browser, so its image log has
    # to travel with this response: without it the "Image log" panel only learns
    # about a turn after a full reload of the story.
    image_service.ensure_build_logs(db, [turn], settings)
    return turn


@router.delete("/stories/{story_id}/pinned-facts/{index}", response_model=PinnedFactsRead)
def delete_pinned_fact(
    story_id: int,
    index: int,
    db: Session = Depends(get_db),
) -> PinnedFactsRead:
    # The player's manual fix for a mistaken "fact" note; the fact stops being
    # passed to the narrator from the next turn on.
    return PinnedFactsRead(pinned_facts=story_engine.delete_pinned_fact(db, story_id, index))


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(
    story_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    story = db.get(Story, story_id)
    if story is None:
        raise story_engine.StoryNotFoundError("Story not found.")
    db.delete(story)
    db.commit()
    _delete_story_images(settings, story_id)
    return Response(status_code=204)


def _delete_story_images(settings: Settings, story_id: int) -> None:
    """Remove IMAGE_DIR/{story_id}/ with all scenes and portraits.

    Failures are logged, never fatal: a locked or missing folder must not
    turn a successful database delete into an error response.
    """
    try:
        base = Path(settings.image_dir).resolve()
        target = (base / str(story_id)).resolve()
        if target.parent != base:  # defensive: never delete outside IMAGE_DIR
            logger.error("refusing to delete suspicious image path: %s", target)
            return
        shutil.rmtree(target, ignore_errors=True)
    except OSError:
        logger.exception("could not delete images for story %s", story_id)

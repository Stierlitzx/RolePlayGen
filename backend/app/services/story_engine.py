import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Character, Story, Turn
from ..schemas import TurnContract, TurnCreate
from ..setup_options import (
    age_rating_clause,
    effective_culture,
    effective_naming_culture,
    narrator_style_fragment,
    resolve_randoms,
    setting_description,
)
from .llm import LLMConfigurationError, LLMResponseError, call_model

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class StoryEngineError(RuntimeError):
    status_code = 500


class InvalidPlayerInputError(StoryEngineError):
    status_code = 400


class StoryNotFoundError(StoryEngineError):
    status_code = 404


class StoryFinishedError(StoryEngineError):
    status_code = 409


class InvalidModelResponseError(StoryEngineError):
    status_code = 502


class MissingAIKeyError(StoryEngineError):
    status_code = 503


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def story_title(settings_data: dict[str, Any]) -> str:
    setting_value = settings_data.get("setting")
    if setting_value == "Custom" and settings_data.get("custom_setting"):
        setting_value = settings_data["custom_setting"]
    hero = (settings_data.get("hero_name") or "").strip() or "The hero"
    return f"{hero} in {setting_value}"[:200]


def _setting_name(params: dict[str, Any]) -> str:
    if params.get("setting") == "Custom" and params.get("custom_setting"):
        return str(params["custom_setting"])
    return str(params.get("setting", "a mysterious world"))


def max_turns_for_length(length: str, custom_turns: int | None = None) -> int | None:
    if length == "custom":
        return custom_turns
    return {"short": 50, "medium": 100, "long": None}[length]


def create_story(db: Session, payload: Any, settings: Settings) -> Story:
    if not settings.mock_llm and (settings.llm_provider or "gemini") == "gemini" and not settings.gemini_api_key:
        raise MissingAIKeyError(
            "Gemini API key is not configured. Add GEMINI_API_KEY to .env, switch "
            "LLM_PROVIDER=openai for a local model, or enable MOCK_LLM=true."
        )
    settings_data = resolve_randoms(payload.model_dump())
    story = Story(
        title=story_title(settings_data),
        settings=settings_data,
        max_turns=max_turns_for_length(payload.length, payload.custom_turns),
    )
    db.add(story)
    db.flush()
    _generate_turn(db, story, "start", "Begin the story.", settings)
    db.commit()
    db.refresh(story)
    return story


def update_story(db: Session, story_id: int, payload: Any, settings: Settings) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    if len(story.turns) > 1:
        # Mid-story only the narrator voice may change; every other field is frozen.
        incoming = payload.model_dump()
        current = dict(story.settings)
        mismatched = []
        for key, value in incoming.items():
            if key == "narrator_style":
                continue
            if key in current:
                if current[key] != value:
                    mismatched.append(key)
            elif value not in (None, False):
                # field did not exist when the story was created; only defaults are OK
                mismatched.append(key)
        if mismatched:
            raise InvalidPlayerInputError(
                "Only the narrator style can be changed after the story has started "
                f"(tried to change: {', '.join(mismatched)})."
            )
        story.settings = {**current, "narrator_style": payload.narrator_style}
        db.commit()
        db.refresh(story)
        return story
    settings_data = resolve_randoms(payload.model_dump())
    story.title = story_title(settings_data)
    story.settings = settings_data
    story.max_turns = max_turns_for_length(payload.length, payload.custom_turns)
    db.commit()
    db.refresh(story)
    return story


def regenerate_start(db: Session, story_id: int, settings: Settings) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    if len(story.turns) > 1:
        raise InvalidPlayerInputError("The beginning can only be regenerated before the second turn.")
    first_turn = story.turns[0]
    db.delete(first_turn)
    db.flush()
    story.status = "active"
    _generate_turn(db, story, "start", "Begin the story.", settings)
    db.commit()
    db.refresh(story)
    return story


def add_turn(db: Session, story_id: int, payload: TurnCreate, settings: Settings) -> Turn:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    if story.status == "finished":
        raise StoryFinishedError("This story is already finished.")

    last_turn = story.turns[-1] if story.turns else None
    if last_turn is None or last_turn.choice is None:
        raise StoryFinishedError("This story has no active choice.")

    if payload.option_id:
        valid_ids = {option["id"] for option in last_turn.choice["options"]}
        if payload.option_id not in valid_ids:
            raise InvalidPlayerInputError("The selected option does not exist for the current turn.")
        input_type = "option"
        input_text = next(
            option["text"] for option in last_turn.choice["options"] if option["id"] == payload.option_id
        )
    else:
        if not last_turn.choice["allow_custom"]:
            raise InvalidPlayerInputError("Custom actions are not allowed for this choice.")
        custom_text = (payload.custom_text or "").strip()
        if not custom_text:
            raise InvalidPlayerInputError("Custom action cannot be empty.")
        if len(custom_text) > 500:
            raise InvalidPlayerInputError("Custom action must be at most 500 characters.")
        input_type = "custom"
        input_text = custom_text

    turn = _generate_turn(db, story, input_type, input_text, settings)
    db.commit()
    db.refresh(turn)
    return turn


def _system_prompt(story: Story) -> str:
    """Base narrator prompt + the story's narrator voice + age rating clause.

    Both additions are empty strings for stories created before those fields
    existed, so old stories keep their exact previous prompt.
    """
    parts = [load_prompt("narrator_system.txt")]
    style = narrator_style_fragment(story.settings.get("narrator_style"))
    if style:
        parts.append(style)
    rating = age_rating_clause(story.settings)
    if rating:
        parts.append(rating)
    return "\n\n".join(parts)


def _generate_turn(db: Session, story: Story, input_type: str, input_text: str, settings: Settings) -> Turn:
    turn_number = len(story.turns) + 1
    user_prompt = _build_prompt(story, input_type, input_text, turn_number)
    system_prompt = _system_prompt(story)
    errors: list[str] = []

    for attempt in range(2):
        prompt = user_prompt
        if errors:
            prompt += (
                "\nPREVIOUS RESPONSE ERROR\n"
                + "\n".join(errors)
                + "\nFix the JSON and return only the corrected object."
            )
        try:
            raw = call_model(
                system_prompt,
                prompt,
                settings,
                mock_index=turn_number - 1,
                mock_language=story.settings.get("language", "English"),
                mock_setting=_setting_name(story.settings),
                mock_max_turns=story.max_turns,
                model_name=story.settings.get("model") or None,
            )
            contract = _parse_contract(raw)
        except LLMConfigurationError as exc:
            raise MissingAIKeyError(str(exc)) from exc
        except LLMResponseError as exc:
            raise InvalidModelResponseError(str(exc)) from exc
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.warning(
                "story %s turn %s attempt %s failed contract validation: %s | raw (first 500 chars): %.500s",
                story.id,
                turn_number,
                attempt + 1,
                exc,
                raw,
            )
            errors.append(str(exc))
            if attempt == 0:
                continue
            raise InvalidModelResponseError(
                f"The AI returned an invalid turn after one retry. Cause: {errors[-1][:300]}"
            ) from exc

        turn = Turn(
            story_id=story.id,
            index=turn_number - 1,
            player_input_type=input_type,
            player_input_text=None if input_type == "start" else input_text,
            narration=contract.narration,
            choice=contract.choice.model_dump() if contract.choice else None,
            state=contract.state.model_dump(),
            is_ending=contract.is_ending,
        )
        if contract.characters_in_scene:
            turn.characters_in_scene = [str(name)[:100] for name in contract.characters_in_scene]
        if settings.image_generation_enabled and contract.image_prompt and contract.image_prompt.strip():
            turn.image_prompt = contract.image_prompt.strip()
            turn.image_format = contract.image_format if contract.image_format in ("portrait", "wide") else "wide"
            turn.image_status = "queued"
        db.add(turn)
        if contract.is_ending:
            story.status = "finished"
        db.flush()
        _process_character_reports(db, story, turn, contract, settings)
        if turn.image_status == "queued":
            from . import image_service

            image_service.enqueue_turn_image(turn.id)
        return turn

    raise InvalidModelResponseError("The AI returned an invalid turn.")


def _find_character(db: Session, story_id: int, name: str) -> Character | None:
    return db.scalars(
        select(Character).where(
            Character.story_id == story_id,
            func.lower(Character.name) == name.strip().lower(),
        )
    ).first()


def _queue_portrait(character: Character, settings: Settings) -> None:
    if not settings.image_generation_enabled or not character.appearance_tags:
        return
    character.portrait_status = "queued"
    from . import image_service

    image_service.enqueue_portrait(character.id)


def _history_entry(
    tags: str, pose: str | None, expression: str | None, path: str | None, turn_id: int | None
) -> dict[str, Any]:
    return {
        "appearance_tags": tags,
        "pose": pose or "",
        "expression": expression or "",
        "portrait_path": path,
        "turn_id": turn_id,
    }


def _init_history(character: Character) -> list[dict[str, Any]]:
    """Characters created before versioning get a one-entry history from their
    current data; already-versioned characters keep theirs."""
    if character.portrait_history:
        return [dict(entry) for entry in character.portrait_history]
    return [
        _history_entry(
            character.appearance_tags or "", None, None,
            character.portrait_path, character.first_seen_turn_id,
        )
    ]


def _apply_portrait_update(
    character: Character, entry: Any, turn: Turn, settings: Settings
) -> None:
    """New persistent look: append a history entry and queue one portrait job."""
    new_tags = (entry.appearance_tags or "").strip()
    if not new_tags:
        logger.warning("portrait_update for %r without appearance_tags; ignored", character.name)
        return
    history = _init_history(character)
    history.append(_history_entry(new_tags, entry.pose, entry.expression, None, turn.id))
    character.portrait_history = history
    character.appearance_tags = new_tags
    _queue_portrait(character, settings)


def _apply_portrait_revert(character: Character) -> None:
    """Back to the previous look: instant, reuses the already-generated file."""
    history = _init_history(character)
    if len(history) < 2:
        logger.warning("portrait_revert for %r without a previous look; ignored", character.name)
        return
    history.pop()  # drop the current look
    previous = history[-1]
    character.portrait_history = history
    character.appearance_tags = previous.get("appearance_tags") or character.appearance_tags
    character.portrait_path = previous.get("portrait_path")
    character.portrait_status = "done" if character.portrait_path else "none"
    character.portrait_error = None


def _process_character_reports(
    db: Session, story: Story, turn: Turn, contract: TurnContract, settings: Settings
) -> None:
    """Upsert the characters the narrator reported for this turn.

    New characters get a row and a queued portrait; existing ones only get
    their relationship refreshed. A missing `is_new` flag on an unknown name
    is treated as new (with a warning) rather than dropping the data.
    """
    if contract.hero and (contract.hero.name or contract.hero.appearance_tags):
        hero = db.scalars(
            select(Character).where(Character.story_id == story.id, Character.is_hero.is_(True))
        ).first()
        if hero is None:
            hero = Character(
                story_id=story.id,
                name=(contract.hero.name or story.settings.get("hero_name") or "Hero").strip(),
                is_hero=True,
                role=story.settings.get("hero_role") or "Hero",
                relationship=None,
                description="The player character.",
                appearance_tags=(contract.hero.appearance_tags or "").strip() or None,
                first_seen_turn_id=turn.id,
            )
            db.add(hero)
            db.flush()
            hero.portrait_history = _init_history(hero)
            _queue_portrait(hero, settings)
        elif contract.hero.appearance_tags and not hero.appearance_tags:
            hero.appearance_tags = contract.hero.appearance_tags.strip()
            if hero.portrait_status == "none":
                _queue_portrait(hero, settings)

    for entry in contract.characters or []:
        name = entry.name.strip()
        if not name:
            continue
        existing = _find_character(db, story.id, name)
        if existing is None:
            if not entry.is_new:
                logger.warning(
                    "narrator referenced unknown character %r without is_new; creating it", name
                )
            character = Character(
                story_id=story.id,
                name=name,
                is_hero=False,
                role=entry.role,
                relationship=entry.relationship,
                description=entry.description,
                appearance_tags=(entry.appearance_tags or "").strip() or None,
                first_seen_turn_id=turn.id,
            )
            db.add(character)
            db.flush()
            character.portrait_history = [
                _history_entry(character.appearance_tags or "", entry.pose, entry.expression, None, turn.id)
            ]
            _queue_portrait(character, settings)
            continue
        # Existing character: only the relationship is refreshed; description
        # and appearance_tags are never overwritten by a non-new report.
        if entry.relationship:
            existing.relationship = entry.relationship
        if entry.is_new:
            if not existing.role and entry.role:
                existing.role = entry.role
            if not existing.description and entry.description:
                existing.description = entry.description
            if not existing.appearance_tags and entry.appearance_tags:
                existing.appearance_tags = entry.appearance_tags.strip()
                if existing.portrait_status == "none":
                    _queue_portrait(existing, settings)
        if entry.portrait_update and entry.portrait_revert:
            logger.warning("portrait_update and portrait_revert together for %r; update wins", name)
        if entry.portrait_update:
            _apply_portrait_update(existing, entry, turn, settings)
        elif entry.portrait_revert:
            _apply_portrait_revert(existing)


def _parse_contract(raw: str) -> TurnContract:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        return TurnContract.model_validate(json.loads(text))
    except json.JSONDecodeError:
        # Some models wrap the JSON in prose ("Here is the next turn: ...").
        # Salvage the outermost JSON object before giving up.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return TurnContract.model_validate(json.loads(text[start : end + 1]))
        raise


def _build_prompt(story: Story, input_type: str, input_text: str, turn_number: int) -> str:
    params = story.settings
    facts: list[str] = []
    summaries: list[str] = []
    for turn in story.turns:
        for fact in turn.state.get("facts", []):
            if fact not in facts:
                facts.append(fact)
        if turn.index < max(0, len(story.turns) - 3):
            summaries.append(f"Turn {turn.index + 1}: {turn.state.get('summary', '')}")

    recent = []
    for turn in story.turns[-3:]:
        recent.append(
            f"Turn {turn.index + 1}\n"
            f"Player: {turn.player_input_text or 'Start'}\n"
            f"Narration: {turn.narration}\n"
        )

    position_hint = ""
    if story.max_turns is not None:
        remaining = story.max_turns - turn_number
        if remaining <= 3 and turn_number > 1:
            position_hint = f"Only {remaining} turn(s) remain after this one: build to the climax and resolve."
        elif turn_number == max(2, story.max_turns // 2):
            position_hint = "This is the midpoint: a decisive, story-defining moment is appropriate."

    intro_hint = ""
    if turn_number == 1:
        if params.get("intro_exposition"):
            intro_hint = (
                "OPENING: Begin with a short explanatory prologue that introduces the world "
                "(history, rules, tensions) and the hero (name, role, personality, current "
                "situation) before the first real scene and choice."
            )
        else:
            intro_hint = (
                "OPENING: Start in medias res — drop the player directly into an active scene "
                "with at least one named character. Reveal the world and the hero gradually "
                "through play; do not open with an exposition block."
            )

    known_characters = []
    for character in story.characters:
        if character.is_hero:
            known_characters.append(f"- {character.name} — the hero (player character); role: {character.role or 'unknown'}")
        else:
            line = f"- {character.name}"
            if character.role:
                line += f" — {character.role}"
            if character.relationship:
                line += f"; relationship to the player: {character.relationship}"
            known_characters.append(line)

    language = params.get("language", "Russian")
    template = load_prompt("turn_message.txt")
    return template.format(
        title=story.title,
        setting=_setting_name(params),
        setting_description=setting_description(params.get("setting", ""), params.get("custom_setting")),
        custom_details=params.get("custom_details") or "None",
        genres=", ".join(params.get("genres", [])),
        tone=params.get("tone", ""),
        hero_role=params.get("hero_role") or "Invented by narrator",
        hero_name=params.get("hero_name") or "Invented by narrator",
        hero_appearance=params.get("hero_appearance") or "Invented by narrator",
        language=language,
        setting_culture=effective_culture(params.get("setting_culture"), language),
        naming_culture=effective_naming_culture(
            params.get("naming_culture"), params.get("setting_culture"), language
        ),
        content_restrictions=params.get("content_restrictions") or "None",
        length=params.get("length", "short"),
        turn_number=turn_number,
        max_turns=story.max_turns or "No fixed limit",
        position_hint=position_hint,
        intro_hint=intro_hint,
        known_characters="\n".join(known_characters) or "None yet",
        facts="\n".join(f"- {fact}" for fact in facts) or "None yet",
        summary="\n".join(summaries) or "None yet",
        recent_turns="\n".join(recent) or "No previous turns",
        player_input=f"{input_type}: {input_text}",
    )


def list_stories(db: Session) -> list[Story]:
    return list(db.scalars(select(Story).order_by(Story.updated_at.desc())).all())

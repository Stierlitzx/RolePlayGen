import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Character, Story, Turn
from ..schemas import TurnContract, TurnCreate
from ..setup_options import (
    age_rating_clause,
    choice_prompt_fallback,
    effective_culture,
    effective_naming_culture,
    narrator_style_fragment,
    resolve_randoms,
    setting_description,
)
from .character_matching import find_character, is_hero_placeholder
from .image_tags import clean_tag_string, ensure_trait_tags, has_cyrillic
from .llm import (
    LLMConfigurationError,
    LLMResponseError,
    call_model,
    faithful_appearance_tags,
    translate_image_tags,
)
from .narration_style import narration_problems, repetition_problems

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


def _provider_for_story(story: Story) -> str | None:
    """The story's own provider choice; None means "follow the server default",
    which keeps stories created before per-story providers unchanged."""
    return story.settings.get("llm_provider") or None


def _effective_provider(payload: Any, settings: Settings) -> str:
    """Provider a new story will use: the player's setup choice wins, then the
    server-wide LLM_PROVIDER. "openai"/"local" both mean the local server;
    "groq"/"openrouter"/"mistral" are the named cloud providers."""
    raw = (getattr(payload, "llm_provider", None) or settings.llm_provider or "gemini").lower()
    if raw in ("openai", "local"):
        return "local"
    if raw in ("groq", "openrouter", "mistral"):
        return raw
    return "gemini"


def _store_hero_image(db: Session, story: Story, data_url: str | None, settings: Settings) -> str | None:
    """Write the player's hero photo under IMAGE_DIR and return its path.

    The picture is what every scene illustration is built around (image_1 of
    the edit graph), so a wrong upload is worth failing loudly on — but with a
    message the player can act on, not a 500.
    """
    if not data_url or not data_url.strip():
        return None
    from . import image_service

    try:
        data = image_service.decode_upload(data_url)
    except image_service.ImageGenerationError as exc:
        raise InvalidPlayerInputError(str(exc)) from exc
    return image_service.save_upload(data, settings, story.id, "hero_photo.png")


def create_story(db: Session, payload: Any, settings: Settings) -> Story:
    if not settings.mock_llm:
        provider = _effective_provider(payload, settings)
        if provider == "gemini" and not settings.gemini_api_key:
            raise MissingAIKeyError(
                "Gemini API key is not configured. Add GEMINI_API_KEY to .env, pick "
                "another text model source in the story setup, or enable MOCK_LLM=true."
            )
        if provider == "local" and not settings.openai_base_url:
            raise MissingAIKeyError(
                "The local model is not configured. Set OPENAI_BASE_URL and "
                "OPENAI_MODEL in .env (Ollama: http://localhost:11434/v1), or pick "
                "another text model source in the story setup."
            )
        if provider == "groq" and not settings.groq_api_key:
            raise MissingAIKeyError(
                "Groq API key is not configured. Add GROQ_API_KEY to .env "
                "(free key at console.groq.com), or pick another text model source."
            )
        if provider == "openrouter" and not settings.openrouter_api_key:
            raise MissingAIKeyError(
                "OpenRouter API key is not configured. Add OPENROUTER_API_KEY to .env "
                "(key at openrouter.ai/keys), or pick another text model source."
            )
        if provider == "mistral" and not settings.mistral_api_key:
            raise MissingAIKeyError(
                "Mistral API key is not configured. Add MISTRAL_API_KEY to .env "
                "(free Experiment tier key at console.mistral.ai, no card needed), "
                "or pick another text model source."
            )
    settings_data = resolve_randoms(payload.model_dump())
    hero_image = settings_data.pop("hero_image", None)
    story = Story(
        title=story_title(settings_data),
        settings=settings_data,
        max_turns=max_turns_for_length(payload.length, payload.custom_turns),
    )
    db.add(story)
    db.flush()
    stored_hero = _store_hero_image(db, story, hero_image, settings)
    if stored_hero:
        story.settings = {**settings_data, "hero_image": stored_hero}
    _generate_turn(db, story, "start", "Begin the story.", settings)
    db.commit()
    db.refresh(story)
    return story


def update_story(db: Session, story_id: int, payload: Any, settings: Settings) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    if len(story.turns) > 1:
        # Mid-story only the narrator voice may change; every other field is
        # frozen. The hero photo is the exception: swapping the picture the
        # scenes are built from must stay possible, so it is never a mismatch.
        incoming = payload.model_dump()
        hero_image = incoming.pop("hero_image", None)
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
        stored_hero = _store_hero_image(db, story, hero_image, settings)
        if stored_hero:
            current["hero_image"] = stored_hero
        story.settings = {**current, "narrator_style": payload.narrator_style}
        db.commit()
        db.refresh(story)
        return story
    settings_data = resolve_randoms(payload.model_dump())
    hero_image = settings_data.pop("hero_image", None)
    story.title = story_title(settings_data)
    story.settings = settings_data
    story.max_turns = max_turns_for_length(payload.length, payload.custom_turns)
    stored_hero = _store_hero_image(db, story, hero_image, settings)
    if stored_hero:
        story.settings = {**settings_data, "hero_image": stored_hero}
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
    # Same in-memory collection pitfall as regenerate_last_turn: without this
    # the replacement opening would be numbered turn 2.
    story.turns.remove(first_turn)
    db.flush()
    story.status = "active"
    _generate_turn(db, story, "start", "Begin the story.", settings)
    db.commit()
    db.refresh(story)
    return story


def regenerate_last_turn(db: Session, story_id: int, settings: Settings) -> Story:
    """Delete the last turn and replay the player input that produced it.

    Works on finished stories too (a bad ending is redone like any other turn).
    Single-turn stories fall through to the opening regeneration. Characters
    first introduced on the deleted turn were never met after the redo, so they
    are removed with it; portrait updates from that turn are rolled back.
    """
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    if not story.turns:
        raise StoryNotFoundError("This story has no turns.")
    last_turn = story.turns[-1]
    if last_turn.player_input_type == "start":
        return regenerate_start(db, story_id, settings)

    input_type = last_turn.player_input_type
    input_text = last_turn.player_input_text or ""
    deleted_turn_id = last_turn.id
    deleted_image = last_turn.image_path
    # The player's note survives the redo (it is replayed with the same input),
    # but a fact it pinned is rolled back first — the replacement turn re-pins
    # it (or classifies it differently) on its own.
    note_text = last_turn.note_text
    if last_turn.note_type == "fact" and last_turn.note_normalized:
        _unpin_fact(story, last_turn.note_normalized)
    db.delete(last_turn)
    # db.delete() alone leaves the object in the loaded collection until the
    # session expires it, which would off-by-one the next turn's index.
    story.turns.remove(last_turn)

    for character in list(story.characters):
        if character.is_hero:
            continue
        if character.first_seen_turn_id == deleted_turn_id:
            db.delete(character)
            story.characters.remove(character)
            continue
        # A portrait_update on the deleted turn must not survive it.
        history = [dict(entry) for entry in (character.portrait_history or [])]
        if history and history[-1].get("turn_id") == deleted_turn_id and len(history) > 1:
            history.pop()
            previous = history[-1]
            character.appearance_tags = previous.get("appearance_tags")
            character.portrait_path = previous.get("portrait_path")
            character.portrait_status = "done" if previous.get("portrait_path") else "none"
            character.portrait_error = None
            character.portrait_history = history
    db.flush()

    story.status = "active"
    _generate_turn(db, story, input_type, input_text, settings, note_text=note_text)
    db.commit()
    db.refresh(story)
    _delete_turn_image_file(settings, deleted_image)
    return story


def _delete_turn_image_file(settings: Settings, image_path: str | None) -> None:
    """Best-effort removal of a replaced turn's illustration; never fatal."""
    if not image_path:
        return
    try:
        base = Path(settings.image_dir).resolve()
        target = (base / image_path).resolve()
        if base not in target.parents:  # defensive: stay inside IMAGE_DIR
            logger.error("refusing to delete suspicious image path: %s", target)
            return
        target.unlink(missing_ok=True)
    except OSError:
        logger.exception("could not delete replaced turn image %s", image_path)


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
        # A custom action is ALWAYS available. `allow_custom` used to gate this
        # (and a "locked"/"binary" turn sent false), so the input row vanished
        # and a turn like the player's could only be played by picking one of
        # the narrator's options. The player is the one who has to live with the
        # choice, so the freedom is not the narrator's to withdraw.
        custom_text = (payload.custom_text or "").strip()
        if not custom_text:
            raise InvalidPlayerInputError("Custom action cannot be empty.")
        if len(custom_text) > 1500:
            raise InvalidPlayerInputError("Custom action must be at most 1500 characters.")
        input_type = "custom"
        input_text = custom_text

    # The note never replaces the action; an empty or whitespace-only note is
    # the same as no note and changes nothing.
    note_text = (payload.note_text or "").strip() or None
    turn = _generate_turn(db, story, input_type, input_text, settings, note_text=note_text)
    db.commit()
    db.refresh(turn)
    return turn


# Pinned player facts are capped like the narrator's own facts list (TurnState
# allows 30); the newest fact wins on overflow and on exact re-pinning.
MAX_PINNED_FACTS = 30


def _pin_fact(story: Story, fact: str) -> None:
    """Add a player fact to the story's pinned list (latest wins, deduped)."""
    fact = fact.strip()
    if not fact:
        return
    facts = [f for f in (story.pinned_facts or []) if f.strip().lower() != fact.lower()]
    facts.append(fact)
    story.pinned_facts = facts[-MAX_PINNED_FACTS:]


def _unpin_fact(story: Story, fact: str) -> None:
    """Remove a pinned fact (case-insensitive); used by regenerate rollback and
    by the player's pinned-facts editor."""
    target = fact.strip().lower()
    story.pinned_facts = [
        f for f in (story.pinned_facts or []) if f.strip().lower() != target
    ]


def delete_pinned_fact(db: Session, story_id: int, index: int) -> list[str]:
    """The player's manual fix for a mistaken fact note ("pinned facts" panel)."""
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError("Story not found.")
    facts = list(story.pinned_facts or [])
    if not 0 <= index < len(facts):
        raise InvalidPlayerInputError("This pinned fact does not exist.")
    facts.pop(index)
    story.pinned_facts = facts
    db.commit()
    return facts


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


def _english_tags(tags: str | None, story: Story, settings: Settings) -> str | None:
    """Make a narrator tag string a clean English tag list.

    Two jobs in one place, because every tag field (image_prompt, appearance,
    pose, expression) goes through here:

    * a model that answered with `{"tags": [...]}` or a markdown list instead of
      comma-separated tags is flattened back into plain tags — that JSON used to
      be pasted into the image prompt verbatim;
    * a narrator that answered in the story's language (Cyrillic) is re-emitted
      in English by one narrow call, because the image model cannot read it.
      A failed translation keeps the original text — a picture with
      half-readable tags beats no picture.
    """
    text = clean_tag_string(tags)
    if not text:
        return tags
    if not has_cyrillic(text):
        return text
    translated = translate_image_tags(
        text,
        settings,
        model_name=story.settings.get("model") or None,
        provider=_provider_for_story(story),
    )
    if translated is None:
        logger.warning("narrator image tags are not English and could not be translated; used as they are")
        return text
    logger.info("translated narrator image tags into English: %.80s", translated)
    return translated


def _generate_turn(
    db: Session,
    story: Story,
    input_type: str,
    input_text: str,
    settings: Settings,
    note_text: str | None = None,
) -> Turn:
    turn_number = len(story.turns) + 1
    user_prompt = _build_prompt(story, input_type, input_text, turn_number, note_text)
    system_prompt = _system_prompt(story)
    errors: list[str] = []

    for attempt in range(2):
        prompt = user_prompt
        if errors:
            prompt += (
                "\nPREVIOUS RESPONSE ERROR\n"
                + "\n".join(errors)
                + "\nFix the problem(s) above and return only the corrected object."
            )
        try:
            raw = call_model(
                system_prompt,
                prompt,
                settings,
                mock_index=turn_number - 1,
                mock_language=story.settings.get("language", "English"),
                mock_setting=_setting_name(story.settings),
                mock_hero_appearance=story.settings.get("hero_appearance") or "",
                mock_hero_gender=story.settings.get("hero_gender") or "",
                mock_max_turns=story.max_turns,
            # Seed the mock rotation with (story.id - 1) so the very first
            # story gets the classic opening and later stories diverge.
            mock_seed=(story.id or 1) - 1,
                model_name=story.settings.get("model") or None,
                provider=_provider_for_story(story),
            )
            contract = _parse_contract(
                raw, language=story.settings.get("language", "English")
            )
            if turn_number == 1 and contract.hero is not None:
                # The narrator invents the hero's tags inside a big JSON and
                # small models compress the player's description. A dedicated
                # conversion call keeps every detail; failure keeps the
                # narrator's tags.
                hero_description = (story.settings.get("hero_appearance") or "").strip()
                if hero_description:
                    fixed_tags = faithful_appearance_tags(
                        hero_description,
                        story.settings.get("hero_gender") or "",
                        settings,
                        model_name=story.settings.get("model") or None,
                        provider=_provider_for_story(story),
                    )
                    if fixed_tags:
                        contract.hero.appearance_tags = fixed_tags
                    if contract.hero.appearance_tags:
                        # Deterministic backstop for the model's own compression:
                        # a proportion the player stated is put back even when the
                        # conversion dropped it ("большая грудь" came back flat).
                        contract.hero.appearance_tags = ensure_trait_tags(
                            hero_description, contract.hero.appearance_tags
                        )
                contract.hero.appearance_tags = _english_tags(
                    contract.hero.appearance_tags, story, settings
                )
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

        # A wall of dialogue lines and italic thoughts instead of prose (Mistral
        # does this) gets ONE more request, and so does a turn that re-plays what
        # the previous turns already wrote. Neither ever loses the turn: the second
        # answer is accepted whatever it looks like, because readability and
        # novelty are not worth failing a turn over.
        style_problems = narration_problems(contract.narration) + repetition_problems(
            contract.narration, [previous.narration for previous in story.turns[-3:]]
        )
        if style_problems and attempt == 0:
            logger.warning(
                "story %s turn %s: narration style problem, asking for a rewrite: %s",
                story.id, turn_number, "; ".join(style_problems),
            )
            errors.extend(style_problems)
            continue
        if style_problems:
            logger.warning(
                "story %s turn %s: narration style problem accepted after the rewrite: %s",
                story.id, turn_number, "; ".join(style_problems),
            )

        turn = Turn(
            story_id=story.id,
            index=turn_number - 1,
            player_input_type=input_type,
            player_input_text=None if input_type == "start" else input_text,
            note_text=note_text,
            narration=contract.narration,
            choice=contract.choice.model_dump() if contract.choice else None,
            state=contract.state.model_dump(),
            is_ending=contract.is_ending,
        )
        if note_text:
            _apply_note_classification(story, turn, contract)
        if contract.characters_in_scene:
            turn.characters_in_scene = [str(name)[:100] for name in contract.characters_in_scene]
        if settings.image_generation_enabled:
            image_prompt = (contract.image_prompt or "").strip()
            if not image_prompt:
                # Small narrators sometimes drop the image fields entirely;
                # fall back to a generic scene shot so the turn still gets an
                # illustration (the hero's stored tags are spliced in later).
                image_prompt = "solo, standing, detailed background, wide shot"
            # The image model reads English tags only: a narrator that answered
            # in the story's language gets one narrow translation call.
            image_prompt = _english_tags(image_prompt, story, settings) or image_prompt
            turn.image_prompt = image_prompt
            # Scene illustrations always render with the wide workflow:
            # framing (close-up vs wide shot) lives in the prompt tags, and a
            # narrator-chosen portrait crop keeps losing the scene context.
            turn.image_format = "wide"
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


def _apply_note_classification(story: Story, turn: Turn, contract: TurnContract) -> None:
    """Store the narrator's classification of this turn's player note.

    A "fact" is pinned to the story and passed in every following request; an
    "event" is fulfilled by this very response and never passed again. When the
    model returns no classification (empty or meaningless note) nothing is
    pinned — the note is only kept on the turn for the history display.
    """
    turn.note_type = contract.note_type
    if contract.note_type != "fact":
        return
    # The model's neutral reformulation is what gets pinned; fall back to the
    # player's own words when the model omitted it.
    normalized = (contract.normalized_text or "").strip() or turn.note_text or ""
    turn.note_normalized = normalized
    _pin_fact(story, normalized)


def _find_character(db: Session, story_id: int, name: str) -> Character | None:
    # SQLite's lower() is ASCII-only, so a SQL-side case-insensitive compare
    # silently fails for Cyrillic names and spawns duplicate rows. The shared
    # matcher compares Python-side (exact -> prefix -> shared descriptor
    # token), which also merges a re-described known character ("Тайный
    # странник" / "Странник в чёрном") instead of creating a second entry.
    characters = list(db.scalars(select(Character).where(Character.story_id == story_id)).all())
    return find_character(characters, name)


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


# The two aliases below expose the history mechanics `portrait_update` uses, so a
# player-driven look change (`PATCH /characters/{id}/look`) follows exactly the
# same rules as a narrator-driven one instead of re-implementing them in the
# router. They are assigned AFTER both functions exist (see below).
portrait_history_entry = _history_entry


def replace_current_look(character: Character, new_tags: str) -> list[dict[str, Any]]:
    """Rewrite the CURRENT look in place instead of appending a new version.

    A player iterating on a portrait prompt repaints several times, and every
    repaint appends a history entry — the "Past looks" gallery fills with
    near-identical versions and the feed grows a "New look" row per tweak. This
    keeps the number of versions and replaces the last one, which is what
    `keep_history=false` asks for.
    """
    history = _init_history(character)
    if not history:
        return [_history_entry(new_tags, None, None, None, None)]
    current = dict(history[-1])
    current["appearance_tags"] = new_tags
    history[-1] = current
    return history


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


# Assigned here, not above: both source functions have to exist first.
init_portrait_history = _init_history


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


def _hero_row_name(reported: str | None, configured: str | None) -> str:
    """The name of the hero's own row.

    The narrator's `hero.name` normally wins, but small models sometimes put the
    `__hero__` sentinel (or a bare "hero"/"player") there instead of an actual
    name — the row would then be titled "__hero__" in the character list. Fall
    back to the player's setup name, then to a neutral "Hero".
    """
    for candidate in (reported, configured):
        if candidate and candidate.strip() and not is_hero_placeholder(candidate):
            return candidate.strip()
    return "Hero"


def _process_character_reports(
    db: Session, story: Story, turn: Turn, contract: TurnContract, settings: Settings
) -> None:
    """Upsert the characters the narrator reported for this turn.

    New characters get a row and a queued portrait; existing ones only get
    their relationship refreshed. A missing `is_new` flag on an unknown name
    is treated as new (with a warning) rather than dropping the data.
    """
    hero_report = contract.hero
    hero_evolves = bool(
        hero_report
        and (hero_report.portrait_update or hero_report.portrait_revert)
    )
    if hero_report and (
        hero_report.name
        or hero_report.appearance_tags
        or hero_report.age
        or hero_evolves
    ):
        hero = db.scalars(
            select(Character).where(Character.story_id == story.id, Character.is_hero.is_(True))
        ).first()
        if hero is None:
            hero = Character(
                story_id=story.id,
                name=_hero_row_name(hero_report.name, story.settings.get("hero_name")),
                is_hero=True,
                role=story.settings.get("hero_role") or "Hero",
                relationship=None,
                description="The player character.",
                appearance_tags=(hero_report.appearance_tags or "").strip() or None,
                age=(hero_report.age or "").strip() or None,
                first_seen_turn_id=turn.id,
            )
            db.add(hero)
            db.flush()
            # The hero's first portrait carries the narrator's pose and
            # expression, exactly like an NPC's: without them every hero of
            # every story got the same generic standing look.
            hero.portrait_history = [
                _history_entry(
                    hero.appearance_tags or "",
                    hero_report.pose,
                    hero_report.expression,
                    None,
                    turn.id,
                )
            ]
            _queue_portrait(hero, settings)
        elif hero_evolves:
            # The hero is a character like any other: a persistent change of look
            # (new clothes, a disguise, armor, an injury) repaints the portrait,
            # and the new tags are spliced into every later scene prompt too.
            # Without this the player character is frozen in the outfit they
            # happened to wear when the story opened.
            hero_report.appearance_tags = _english_tags(
                hero_report.appearance_tags, story, settings
            )
            hero_report.pose = _english_tags(hero_report.pose, story, settings)
            hero_report.expression = _english_tags(hero_report.expression, story, settings)
            if hero_report.portrait_update and hero_report.portrait_revert:
                logger.warning("hero portrait_update and portrait_revert together; update wins")
            if hero_report.portrait_update:
                _apply_portrait_update(hero, hero_report, turn, settings)
            else:
                _apply_portrait_revert(hero)
        elif hero_report.appearance_tags and not hero.appearance_tags:
            hero.appearance_tags = hero_report.appearance_tags.strip()
            if hero.portrait_status == "none":
                _queue_portrait(hero, settings)
        # The hero's age, like an NPC's: kept once, for the picture model only.
        if hero_report.age and not hero.age:
            hero.age = hero_report.age.strip()

    for entry in contract.characters or []:
        name = entry.name.strip()
        if not name:
            continue
        if is_hero_placeholder(name):
            # The narrator mixed the two fields up and reported the player
            # character as a character of its own — usually by copying the
            # "__hero__" sentinel from characters_in_scene into "characters".
            # That is the hero, not a new NPC: creating a row here produced a
            # duplicate "hero" entry with a wasted portrait job, and it showed
            # up in the feed as a second copy of the player.
            logger.debug("character report %r is the player character; skipped", name)
            continue
        # Tags the narrator answered in the story language are translated once,
        # so both the stored look and every later prompt stay English.
        entry.appearance_tags = _english_tags(entry.appearance_tags, story, settings)
        entry.pose = _english_tags(entry.pose, story, settings)
        entry.expression = _english_tags(entry.expression, story, settings)
        # The age is a picture-model hint, so it is translated like the tags
        # (the narrator answers in the story language, the model reads English).
        entry.age = _english_tags(entry.age, story, settings) if entry.age else None
        existing = _find_character(db, story.id, name)
        if existing is not None and existing.is_hero:
            # The narrator must not list the hero in "characters" (small models
            # do anyway) — never create a duplicate NPC row for the player.
            logger.debug("character report %r names the hero; skipped", name)
            continue
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
                age=(entry.age or "").strip() or None,
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
        # The age is filled once and then kept: a later report that drops it
        # must not make a 50-year-old look 25 again.
        if entry.age and not existing.age:
            existing.age = entry.age.strip()
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

    if turn.characters_in_scene:
        # Store canonical DB names so the image step (appearance tags and
        # reference portraits) matches exactly, even when the narrator used a
        # loose variant ("Странник в чёрном" for "Тайный странник").
        canonical: list[str] = []
        for raw_name in turn.characters_in_scene:
            raw = str(raw_name).strip()
            match = None if raw == "__hero__" else _find_character(db, story.id, raw)
            canonical.append(match.name if match is not None else raw)
        turn.characters_in_scene = list(dict.fromkeys(canonical))


def _repair_empty_choice_prompt(data: Any, language: str | None) -> None:
    """Replace an empty/blank choice prompt with the default question in place.

    The prompt above the options is cosmetic UI text ("What will you do?"): a
    model that forgets it must never cost the player a turn. Everything else is
    still validated strictly — this repairs one field, nothing else.
    """
    if not isinstance(data, dict):
        return
    choice = data.get("choice")
    if not isinstance(choice, dict):
        return
    prompt = choice.get("prompt")
    if prompt is None or (isinstance(prompt, str) and not prompt.strip()):
        logger.warning("narrator sent an empty choice prompt; using the default question")
        choice["prompt"] = choice_prompt_fallback(language)


def _parse_contract(raw: str, language: str | None = None) -> TurnContract:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap the JSON in prose ("Here is the next turn: ...").
        # Salvage the outermost JSON object before giving up.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise
    _repair_empty_choice_prompt(data, language)
    return TurnContract.model_validate(data)


def _build_prompt(
    story: Story,
    input_type: str,
    input_text: str,
    turn_number: int,
    note_text: str | None = None,
) -> str:
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
                "OPENING: Begin with a full introductory prologue of several paragraphs that "
                "introduces the world (history, rules, tensions, atmosphere) and the hero "
                "(name, role, personality, current situation) before the first real scene and "
                "choice. Keep it open-ended: raise possibilities and questions rather than "
                "closing anything off."
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
            hero_line = f"- {character.name} — the hero (player character); role: {character.role or 'unknown'}"
            # The current look travels with the hero's name: without it the
            # narrator updates a portrait from memory and loses the face, hair
            # and build it established in an earlier turn.
            if character.appearance_tags:
                hero_line += f"; current look: {character.appearance_tags}"
            known_characters.append(hero_line)
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
        hero_gender=params.get("hero_gender") or "Unspecified",
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
        player_facts="\n".join(f"- {fact}" for fact in (story.pinned_facts or [])) or "None",
        player_note=note_text or "None",
    )


def list_stories(db: Session) -> list[Story]:
    return list(db.scalars(select(Story).order_by(Story.updated_at.desc())).all())

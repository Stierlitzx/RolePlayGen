import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.schemas import StoryCreate, TurnCreate
from app.services import story_engine


def story_payload() -> StoryCreate:
    return StoryCreate(
        setting="Medieval kingdom",
        genres=["Fantasy", "Adventure"],
        tone="Dark",
        hero_role="Exiled cartographer",
        hero_name="Mira",
        length="custom",
        custom_turns=50,
        content_restrictions="No graphic violence",
        language="English",
    )


def test_create_story_generates_start_turn(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    assert story.id is not None
    assert len(story.turns) == 1
    assert story.turns[0].player_input_type == "start"
    assert story.turns[0].choice["mode"] == "open"


def test_player_turns_cover_modes_and_completion(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    assert story.max_turns == 50

    seen_modes = {story.turns[0].choice["mode"]}
    binary_turns = []
    ending = None
    for _ in range(49):
        turn = story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
        if turn.choice:
            seen_modes.add(turn.choice["mode"])
            if turn.choice["mode"] == "binary":
                binary_turns.append(turn.index + 1)
        if turn.is_ending:
            ending = turn
            break

    assert ending is not None
    assert ending.index == 49
    assert ending.choice is None
    assert seen_modes == {"open", "locked", "binary"}
    assert binary_turns == [25]
    db_session.refresh(story)
    assert story.status == "finished"

    with pytest.raises(story_engine.StoryFinishedError):
        story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)


def test_custom_text_rejected_in_locked_mode(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    with pytest.raises(story_engine.InvalidPlayerInputError, match="not allowed"):
        story_engine.add_turn(db_session, story.id, TurnCreate(custom_text="Break the rules"), settings)


def test_invalid_model_response_retries_once_then_fails(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def invalid_response(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "not json"

    monkeypatch.setattr(story_engine, "call_model", invalid_response)
    with pytest.raises(story_engine.InvalidModelResponseError):
        story_engine.create_story(db_session, story_payload(), settings)
    assert calls == 2


def test_update_story_and_regenerate_start(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)

    payload = story_payload()
    payload.hero_name = "Yuri"
    payload.language = "Russian"
    updated = story_engine.update_story(db_session, story.id, payload, settings)
    assert updated.title.startswith("Yuri")
    assert updated.settings["language"] == "Russian"

    regenerated = story_engine.regenerate_start(db_session, story.id, settings)
    assert len(regenerated.turns) == 1
    assert regenerated.turns[0].player_input_type == "start"
    assert regenerated.turns[0].player_input_text is None
    assert "ваш" in regenerated.turns[0].narration or "Вы" in regenerated.turns[0].narration

    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    payload.hero_name = "Not Yuri"  # any non-style change is frozen mid-story
    with pytest.raises(story_engine.InvalidPlayerInputError):
        story_engine.update_story(db_session, story.id, payload, settings)
    with pytest.raises(story_engine.InvalidPlayerInputError):
        story_engine.regenerate_start(db_session, story.id, settings)

    # the narrator voice is the one thing that may change mid-story
    mid_story = StoryCreate(**story.settings)
    mid_story.narrator_style = "Disco Elysium"
    restyled = story_engine.update_story(db_session, story.id, mid_story, settings)
    assert restyled.settings["narrator_style"] == "Disco Elysium"
    assert restyled.settings["hero_name"] == "Yuri"  # everything else untouched


def test_prose_wrapped_json_is_salvaged() -> None:
    import json as _json

    from app.services.llm import _mock_contract

    contract = _json.dumps(_mock_contract(1, 50, "English", "Medieval kingdom"), ensure_ascii=False)
    wrapped = f"Sure! Here is the next turn:\n{contract}\nHope that helps."
    parsed = story_engine._parse_contract(wrapped)
    assert parsed.state.scene


def test_hero_appearance_reaches_prompt(db_session: Session, settings: Settings) -> None:
    payload = story_payload()
    payload.hero_appearance = "Tall woman with a silver braid and a burned left hand"
    story = story_engine.create_story(db_session, payload, settings)
    assert story.settings["hero_appearance"].startswith("Tall woman")
    prompt = story_engine._build_prompt(story, "start", None, 2)
    assert "Hero appearance: Tall woman with a silver braid" in prompt

    plain = story_engine.create_story(db_session, story_payload(), settings)
    prompt_without = story_engine._build_prompt(plain, "start", None, 2)
    assert "Hero appearance: Invented by narrator" in prompt_without


def test_openai_provider_needs_no_gemini_key(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    local_settings = Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="openai",
        openai_base_url="http://localhost:11434/v1",
    )
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *args, **kwargs: _json.dumps(
            _mock_contract(1, 50, "English", "Medieval kingdom"), ensure_ascii=False
        ),
    )
    story = story_engine.create_story(db_session, story_payload(), local_settings)
    assert story.turns[0].player_input_type == "start"


def test_custom_length_requires_turns() -> None:
    with pytest.raises(ValueError):
        StoryCreate(
            setting="Medieval kingdom",
            genres=["Fantasy"],
            tone="Dark",
            length="custom",
            language="English",
        )

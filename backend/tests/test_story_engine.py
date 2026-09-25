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
    assert regenerated.turns[0].index == 0  # replacement opening keeps turn numbering
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



def test_empty_choice_prompt_is_repaired_with_a_localized_fallback() -> None:
    import json as _json

    from app.services.llm import _mock_contract

    def contracted(language: str, prompt: object) -> str:
        contract = _mock_contract(2, 50, language, "Medieval kingdom")
        contract["choice"]["prompt"] = prompt
        return _json.dumps(contract, ensure_ascii=False)

    for language, expected in (
        ("Russian", "Что ты сделаешь?"),
        ("English", "What will you do?"),
        ("Kazakh", "Не істейсің?"),
    ):
        parsed = story_engine._parse_contract(contracted(language, "   "), language=language)
        assert parsed.choice is not None
        assert parsed.choice.prompt == expected

    # ...a real prompt is never touched, and nothing else is repaired.
    parsed = story_engine._parse_contract(contracted("Russian", "Выбирай!"), language="Russian")
    assert parsed.choice is not None
    assert parsed.choice.prompt == "Выбирай!"
    # ...so a genuinely broken answer still fails loudly, not silently.
    # (a narration that violates a real min_length rule is not repairable)
    bad = _json.loads(contracted("Russian", "Выбирай!"))
    bad["narration"] = ""
    with pytest.raises(Exception):
        story_engine._parse_contract(_json.dumps(bad), language="Russian")



def test_hero_tags_get_a_stated_chest_size_back() -> None:
    # The engine's hero pipeline: the narrator compresses the hero's look and
    # drops the figure its own text promised — the deterministic backstop
    # re-adds what the PLAYER wrote.
    import json as _json

    from app.services.llm import _mock_contract
    contract = _json.dumps(_mock_contract(1, 50, "English", "Medieval kingdom"), ensure_ascii=False)
    parsed = story_engine._parse_contract(contract.replace(
        '"appearance_tags": "1girl",', '"appearance_tags": "1girl, traveler, cloak",', 1
    ))
    assert story_engine._parse_contract(contract)  # still valid
    from app.services.image_tags import ensure_trait_tags
    fixed = ensure_trait_tags(
        "Эльфийка с большой грудью и тонкой талией",
        parsed.hero.appearance_tags or "",
    )
    assert "large breasts" in fixed and "narrow waist" in fixed
    assert "traveler, cloak" in fixed
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
    assert "Hero appearance at the opening" in prompt
    assert "Tall woman with a silver braid" in prompt

    plain = story_engine.create_story(db_session, story_payload(), settings)
    prompt_without = story_engine._build_prompt(plain, "start", None, 2)
    assert "Hero appearance at the opening" in prompt_without
    assert "Invented by narrator" in prompt_without


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


def test_per_story_local_provider_needs_no_gemini_key(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Server default is Gemini with no key, but the story picked "local" in the
    # setup form — creation must not 503.
    import json as _json

    from app.services.llm import _mock_contract

    gemini_default = Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="gemini",
        openai_base_url="http://localhost:11434/v1",
    )
    monkeypatch.setattr(
        story_engine,
        "call_model",
        lambda *args, **kwargs: _json.dumps(
            _mock_contract(1, 50, "English", "Medieval kingdom"), ensure_ascii=False
        ),
    )
    payload = story_payload()
    payload.llm_provider = "local"
    story = story_engine.create_story(db_session, payload, gemini_default)
    assert story.settings["llm_provider"] == "local"
    assert story.turns[0].player_input_type == "start"


def test_per_story_gemini_provider_requires_key(db_session: Session) -> None:
    # Server default is the local provider, but the story picked Gemini and no
    # key is configured — a clear 503, not a failed turn.
    local_default = Settings(
        mock_llm=False,
        gemini_api_key="",
        llm_provider="openai",
        openai_base_url="http://localhost:11434/v1",
    )
    payload = story_payload()
    payload.llm_provider = "gemini"
    with pytest.raises(story_engine.MissingAIKeyError, match="Gemini API key"):
        story_engine.create_story(db_session, payload, local_default)


def test_per_story_groq_provider_requires_key(db_session: Session) -> None:
    settings = Settings(mock_llm=False, gemini_api_key="", llm_provider="gemini", groq_api_key="")
    payload = story_payload()
    payload.llm_provider = "groq"
    with pytest.raises(story_engine.MissingAIKeyError, match="GROQ_API_KEY"):
        story_engine.create_story(db_session, payload, settings)


def test_per_story_openrouter_provider_requires_key(db_session: Session) -> None:
    settings = Settings(
        mock_llm=False, gemini_api_key="", llm_provider="gemini", openrouter_api_key=""
    )
    payload = story_payload()
    payload.llm_provider = "openrouter"
    with pytest.raises(story_engine.MissingAIKeyError, match="OPENROUTER_API_KEY"):
        story_engine.create_story(db_session, payload, settings)


def test_per_story_mistral_provider_requires_key(db_session: Session) -> None:
    settings = Settings(mock_llm=False, gemini_api_key="", llm_provider="gemini", mistral_api_key="")
    payload = story_payload()
    payload.llm_provider = "mistral"
    with pytest.raises(story_engine.MissingAIKeyError, match="MISTRAL_API_KEY"):
        story_engine.create_story(db_session, payload, settings)


def test_hero_gender_reaches_prompt_and_mock_tags(db_session: Session, settings: Settings) -> None:
    payload = story_payload()
    payload.hero_gender = "Male"
    payload.hero_appearance = "Tall man with a silver braid. Burned left hand."
    story = story_engine.create_story(db_session, payload, settings)
    assert story.settings["hero_gender"] == "Male"
    prompt = story_engine._build_prompt(story, "start", None, 2)
    assert "Hero gender: Male" in prompt
    hero = next(c for c in story.characters if c.is_hero)
    assert hero.appearance_tags.startswith("1boy")
    assert "silver braid" in hero.appearance_tags

    with pytest.raises(ValueError, match="hero_gender"):
        StoryCreate(**{**story_payload().model_dump(), "hero_gender": "Robot"})


def test_custom_length_requires_turns() -> None:
    with pytest.raises(ValueError):
        StoryCreate(
            setting="Medieval kingdom",
            genres=["Fantasy"],
            tone="Dark",
            length="custom",
            language="English",
        )


def test_invalid_image_format_falls_back_to_wide(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Small local narrators sometimes write image_format "medium" — per SPEC
    # that must normalize to "wide", not fail contract validation.
    import json as _json

    from app.services.llm import _mock_contract

    def odd_format(*args: object, **kwargs: object) -> str:
        contract = _mock_contract(1, 50, "English", "Medieval kingdom")
        contract["image_format"] = "medium"
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", odd_format)
    image_settings = Settings(mock_llm=True, image_generation_enabled=True)
    story = story_engine.create_story(db_session, story_payload(), image_settings)
    assert story.turns[0].image_format == "wide"
    assert story.turns[0].image_status == "queued"


def test_regenerate_last_turn_replays_the_same_input(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(story)
    old_last = story.turns[-1]

    # Marker narration proves the turn was actually regenerated, not kept —
    # SQLite reuses the deleted row's id, so comparing ids proves nothing.
    def marked(*args: object, **kwargs: object) -> str:
        contract = _mock_contract(2, 50, "English", "Medieval kingdom")
        contract["narration"] = "REGENERATED MARKER"
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", marked)
    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)

    assert len(updated.turns) == 2
    assert updated.turns[-1].narration == "REGENERATED MARKER"
    assert updated.turns[-1].index == old_last.index == 1
    assert updated.turns[-1].player_input_type == "option"
    assert updated.turns[-1].player_input_text == old_last.player_input_text


def test_regenerate_last_turn_redoes_an_ending(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    story.max_turns = 2  # the next turn becomes the ending
    db_session.commit()
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(story)
    assert story.status == "finished"

    def marked_ending(*args: object, **kwargs: object) -> str:
        contract = _mock_contract(2, 2, "English", "Medieval kingdom")
        contract["narration"] = "NEW ENDING MARKER"
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", marked_ending)
    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)

    assert updated.turns[-1].narration == "NEW ENDING MARKER"
    assert updated.turns[-1].is_ending is True
    assert updated.status == "finished"  # same max_turns: the redo is a NEW ending


def test_regenerate_last_turn_removes_characters_introduced_on_it(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)

    def with_new_npc(*args: object, **kwargs: object) -> str:
        contract = _mock_contract(2, 50, "English", "Medieval kingdom")
        contract["characters"] = [{
            "name": "Shady Finn", "is_new": True, "role": "informant",
            "relationship": "unknown", "description": "A man who knows things.",
            "appearance_tags": "1boy, adult, hood",
        }]
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", with_new_npc)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    db_session.refresh(story)
    assert any(c.name == "Shady Finn" for c in story.characters)

    monkeypatch.undo()  # regenerate with the plain mock
    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)
    assert not any(c.name == "Shady Finn" for c in updated.characters)
    assert len(updated.turns) == 2


def test_regenerate_last_turn_single_turn_story_redoes_opening(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)
    assert len(updated.turns) == 1
    assert updated.turns[0].player_input_type == "start"


def test_regenerate_last_turn_missing_story(db_session: Session, settings: Settings) -> None:
    with pytest.raises(story_engine.StoryNotFoundError):
        story_engine.regenerate_last_turn(db_session, 9999, settings)


def test_hero_description_translated_losslessly_on_turn_one(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The narrator invents hero tags inside the big turn JSON and small models
    # compress the player's description; the dedicated conversion wins.
    payload = story_payload()
    payload.hero_appearance = "Huge breasts, wolfcut ponytail, sheer blouse, stockings"
    monkeypatch.setattr(
        story_engine,
        "faithful_appearance_tags",
        lambda *a, **k: "1girl, solo, huge breasts, wolfcut, ponytail, see-through blouse, stockings, adult",
    )
    story = story_engine.create_story(db_session, payload, settings)
    hero = next(c for c in story.characters if c.is_hero)
    assert hero.appearance_tags == (
        "1girl, solo, huge breasts, wolfcut, ponytail, see-through blouse, stockings, adult"
    )


def test_hero_tags_fall_back_to_narrator_when_translation_fails(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = story_payload()
    payload.hero_appearance = "Silver braid, red coat"
    monkeypatch.setattr(story_engine, "faithful_appearance_tags", lambda *a, **k: None)
    story = story_engine.create_story(db_session, payload, settings)
    hero = next(c for c in story.characters if c.is_hero)
    assert "Silver braid" in hero.appearance_tags  # the mock narrator's own conversion
    assert "fully clothed" in hero.appearance_tags


def _dialogue_wall() -> str:
    """A Mistral-style turn: one block of quoted lines and italic thoughts."""
    return " ".join(
        [
            "Лирна замерла на пороге хижины, сердце колотилось так сильно, что она боялась, "
            "как бы оно не выпрыгнуло из груди.",
            "*«Бабушка…»* — мысль об этом не давала ей дышать.",
            "— Уходи, эльфийка, — сказал он, голос дрожа от ненависти.",
            "— Или я действительно её убью.",
            "*«Я не уйду. Я не оставлю её.»*",
            "— Тогда отпусти её! — крикнула Лирна, и в её голосе зазвучала такая сила.",
            "— Ты не понимаешь, что делаешь, — сказал он, голос низкий и хриплый.",
            "*«Магия… она внутри меня.»*",
            "— Что это?! — закричал он, но Лирна не обратила на него внимания.",
            "— Оставь её, — сказал он, голос теперь звучал как предупреждение.",
            "— Это не твоя война, мальчик.",
            "— Моя девочка… — прошептала она.",
            "— Нет, — сказала она. — Я не их. Я не твоя. Я — мага.",
        ]
    )


def test_dialogue_wall_narration_is_rewritten_once(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A wall of dialogue and italic thoughts is asked for once more; the second
    # answer is the one the player gets.
    import json as _json

    from app.services.llm import _mock_contract

    wall = _dialogue_wall()
    prompts: list[str] = []

    def narrator(*args: object, **kwargs: object) -> str:
        prompts.append(args[1])  # the user prompt is the second argument
        contract = _mock_contract(1, 50, "English", "Medieval kingdom")
        if len(prompts) == 1:
            contract["narration"] = wall
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", narrator)
    story = story_engine.create_story(db_session, story_payload(), settings)

    assert len(prompts) == 2
    assert story.turns[0].narration != wall
    assert "NARRATION FORMAT" in prompts[1]  # the retry carries the complaint
    assert wall not in prompts[1]


def test_dialogue_wall_is_accepted_after_the_rewrite(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A style problem must never fail a turn: the second answer is stored as it is.
    import json as _json

    from app.services.llm import _mock_contract

    wall = _dialogue_wall()
    calls = 0

    def narrator(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        contract = _mock_contract(1, 50, "English", "Medieval kingdom")
        contract["narration"] = wall
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", narrator)
    story = story_engine.create_story(db_session, story_payload(), settings)

    assert calls == 2
    assert story.turns[0].narration == wall


def test_a_turn_replaying_the_previous_one_is_rewritten_once(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The player's complaint: every turn re-plays the same beat. The first turn
    # is clean (nothing to compare against), the second one is the previous
    # narration word for word — it gets ONE more request, and the retry says why.
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    first_narration = story.turns[0].narration
    prompts: list[str] = []

    def narrator(*args: object, **kwargs: object) -> str:
        prompts.append(args[1])  # the user prompt is the second argument
        contract = _mock_contract(2, 50, "English", "Medieval kingdom")
        if len(prompts) == 1:
            contract["narration"] = first_narration
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", narrator)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    assert len(prompts) == 2
    assert "REPEATED CONTENT" in prompts[1]
    assert "REPEATED DIALOGUE" in prompts[1]
    assert story.turns[-1].narration != first_narration


def test_a_repeated_turn_is_never_lost(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A narrator that repeats itself twice is still a story: the second answer is
    # stored, exactly like a format problem.
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    first_narration = story.turns[0].narration
    calls = 0

    def narrator(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        contract = _mock_contract(2, 50, "English", "Medieval kingdom")
        contract["narration"] = first_narration
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", narrator)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    assert calls == 2
    assert story.turns[-1].narration == first_narration


def test_the_hero_s_current_look_reaches_the_next_prompt(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The narrator updates a look from the tags it is shown, not from memory: the
    # hero's current appearance has to travel with the hero's name.
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    hero = next(c for c in story.characters if c.is_hero)
    hero.appearance_tags = "1girl, red hair, green eyes, brown cloak, adult"
    db_session.commit()

    prompts: list[str] = []

    def capturing(*args: object, **kwargs: object) -> str:
        prompts.append(args[1])
        return _json.dumps(_mock_contract(2, 50, "English", "Medieval kingdom"), ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", capturing)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    assert "current look: 1girl, red hair, green eyes, brown cloak, adult" in prompts[0]

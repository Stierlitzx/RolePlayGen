import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Story
from app.schemas import StoryCreate, TurnCreate
from app.services import story_engine


def story_payload() -> StoryCreate:
    return StoryCreate(
        setting="Medieval kingdom",
        genres=["Fantasy"],
        tone="Dark",
        hero_role="Exiled cartographer",
        hero_name="Mira",
        length="custom",
        custom_turns=50,
        language="English",
    )


def api_payload() -> dict:
    return {
        "setting": "Space station",
        "custom_setting": None,
        "genres": ["Science fiction"],
        "tone": "Serious",
        "hero_role": "Engineer",
        "hero_name": "Ada",
        "length": "custom",
        "custom_turns": 50,
        "model": "gemini-3.6-flash",
        "content_restrictions": None,
        "language": "English",
    }


def test_fact_note_is_pinned_and_passed_to_later_turns(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)

    turn = story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="my character has no lighter"),
        settings,
    )
    assert turn.note_text == "my character has no lighter"
    assert turn.note_type == "fact"  # the mock narrator classifies states as facts
    db_session.refresh(story)
    assert story.pinned_facts == ["my character has no lighter"]

    # The pinned fact is still there several turns later.
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="b"), settings)
    db_session.refresh(story)
    assert story.pinned_facts == ["my character has no lighter"]


def test_fact_note_reaches_the_prompt_on_every_following_turn(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []
    real_call_model = story_engine.call_model

    def capturing(*args: object, **kwargs: object) -> str:
        prompts.append(args[1])  # the user prompt is the second argument
        return real_call_model(*args, **kwargs)

    story = story_engine.create_story(db_session, story_payload(), settings)
    monkeypatch.setattr(story_engine, "call_model", capturing)
    story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="Mira is wounded in the leg"),
        settings,
    )
    story_engine.add_turn(db_session, story.id, TurnCreate(option_id="a"), settings)

    assert len(prompts) == 2
    # The first prompt carries the raw note; the pinned fact block is not there yet.
    assert "Mira is wounded in the leg" in prompts[0]
    # The second prompt carries the pinned fact even without a new note.
    assert "PLAYER FACTS" in prompts[1]
    assert "Mira is wounded in the leg" in prompts[1]
    # No new note on the second turn: the note block explicitly says "None".
    assert re.search(r"PLAYER NOTE FOR THIS TURN[^\n]*\nNone\n", prompts[1])


def test_event_note_is_not_pinned(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    turn = story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="bandits attack me from the bushes"),
        settings,
    )
    assert turn.note_type == "event"  # "attack" triggers the event heuristic
    db_session.refresh(story)
    assert story.pinned_facts in (None, [])  # an event is fulfilled once, never pinned


def test_empty_and_whitespace_notes_change_nothing(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    turn = story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="   "),
        settings,
    )
    assert turn.note_text is None
    assert turn.note_type is None
    db_session.refresh(story)
    assert story.pinned_facts in (None, [])


def test_player_input_and_note_are_binding_orders(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The narrator must treat PLAYER INPUT and PLAYER NOTE as direct orders:
    # whatever they ask to happen must appear in THIS turn's narration.
    prompts: list[str] = []
    real_call_model = story_engine.call_model

    def capturing(*args: object, **kwargs: object) -> str:
        prompts.append(args[1])  # the user prompt is the second argument
        return real_call_model(*args, **kwargs)

    story = story_engine.create_story(db_session, story_payload(), settings)
    monkeypatch.setattr(story_engine, "call_model", capturing)
    story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="a dragon lands in front of me"),
        settings,
    )
    assert "DIRECT ORDER" in prompts[0]
    assert "PLAYER NOTE FOR THIS TURN" in prompts[0]
    assert "a dragon lands in front of me" in prompts[0]
    system = story_engine._system_prompt(db_session.get(Story, story.id))
    assert "BINDING DIRECTIVES" in system


def test_unclassified_note_is_kept_on_turn_but_not_pinned(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    def silent_narrator(*args: object, **kwargs: object) -> str:
        # A narrator that does not support note classification (or read spam).
        return _json.dumps(_mock_contract(2, 50, "English", "Medieval kingdom"))

    story = story_engine.create_story(db_session, story_payload(), settings)
    monkeypatch.setattr(story_engine, "call_model", silent_narrator)
    turn = story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="asdkjh qwerty"),
        settings,
    )
    assert turn.note_text == "asdkjh qwerty"
    assert turn.note_type is None
    db_session.refresh(story)
    assert story.pinned_facts in (None, [])


def test_regenerate_replays_note_and_rolls_back_pinned_fact(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="my character has no lighter"),
        settings,
    )
    db_session.refresh(story)
    assert story.pinned_facts == ["my character has no lighter"]

    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)
    # The note is kept in the replayed request, not duplicated or lost.
    assert updated.turns[-1].note_text == "my character has no lighter"
    assert updated.turns[-1].note_type == "fact"
    assert updated.pinned_facts == ["my character has no lighter"]


def test_regenerate_removes_fact_when_new_classification_is_event(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from app.services.llm import _mock_contract

    story = story_engine.create_story(db_session, story_payload(), settings)
    story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="my character has no lighter"),
        settings,
    )
    db_session.refresh(story)
    assert story.pinned_facts == ["my character has no lighter"]

    def event_narrator(*args: object, **kwargs: object) -> str:
        contract = _mock_contract(2, 50, "English", "Medieval kingdom")
        contract["note_type"] = "event"
        contract["normalized_text"] = "my character has no lighter"
        return _json.dumps(contract, ensure_ascii=False)

    monkeypatch.setattr(story_engine, "call_model", event_narrator)
    updated = story_engine.regenerate_last_turn(db_session, story.id, settings)
    # The redo classified the note as an event: the old pinned fact is gone.
    assert updated.turns[-1].note_type == "event"
    assert updated.pinned_facts in (None, [])


def test_delete_pinned_fact(
    db_session: Session, settings: Settings
) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    story_engine.add_turn(
        db_session, story.id,
        TurnCreate(option_id="a", note_text="my character has no lighter"),
        settings,
    )
    facts = story_engine.delete_pinned_fact(db_session, story.id, 0)
    assert facts == []
    db_session.refresh(story)
    assert story.pinned_facts == []

    with pytest.raises(story_engine.InvalidPlayerInputError):
        story_engine.delete_pinned_fact(db_session, story.id, 0)
    with pytest.raises(story_engine.StoryNotFoundError):
        story_engine.delete_pinned_fact(db_session, 9999, 0)


def test_note_flows_through_api(client: TestClient) -> None:
    story = client.post("/api/stories", json=api_payload()).json()
    assert story["pinned_facts"] == []

    turn = client.post(
        f"/api/stories/{story['id']}/turns",
        json={"option_id": "a", "note_text": "Ada carries no weapon"},
    )
    assert turn.status_code == 201
    body = turn.json()
    assert body["note_text"] == "Ada carries no weapon"
    assert body["note_type"] == "fact"

    fetched = client.get(f"/api/stories/{story['id']}").json()
    assert fetched["pinned_facts"] == ["Ada carries no weapon"]
    assert fetched["turns"][-1]["note_text"] == "Ada carries no weapon"

    removed = client.delete(f"/api/stories/{story['id']}/pinned-facts/0")
    assert removed.status_code == 200
    assert removed.json() == {"pinned_facts": []}
    assert client.get(f"/api/stories/{story['id']}").json()["pinned_facts"] == []

    missing = client.delete(f"/api/stories/{story['id']}/pinned-facts/5")
    assert missing.status_code == 400


def test_note_over_2000_chars_is_rejected(client: TestClient) -> None:
    story = client.post("/api/stories", json=api_payload()).json()
    too_long = client.post(
        f"/api/stories/{story['id']}/turns",
        json={"option_id": "a", "note_text": "x" * 2001},
    )
    assert too_long.status_code == 422
    ok = client.post(
        f"/api/stories/{story['id']}/turns",
        json={"option_id": "a", "note_text": "x" * 2000},
    )
    assert ok.status_code == 201


def test_note_works_with_custom_action(db_session: Session, settings: Settings) -> None:
    story = story_engine.create_story(db_session, story_payload(), settings)
    turn = story_engine.add_turn(
        db_session, story.id,
        TurnCreate(custom_text="Light a campfire", note_text="it starts to rain"),
        settings,
    )
    assert turn.player_input_type == "custom"
    assert turn.note_text == "it starts to rain"
    assert turn.note_type == "event"


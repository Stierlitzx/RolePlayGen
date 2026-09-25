"""Setup options: lists served to the frontend, culture helpers, Random picks."""

from app.setup_options import (
    CULTURE_OPTIONS,
    GENRE_OPTIONS,
    MAX_GENRES,
    SETTING_ANCHOR_TAGS,
    SETTING_DESCRIPTIONS,
    SETTING_OPTIONS,
    effective_culture,
    effective_naming_culture,
    resolve_randoms,
    setting_anchor,
    setting_description,
)


def test_every_preset_has_a_description() -> None:
    for preset in SETTING_OPTIONS:
        if preset in ("Custom", "Random"):
            continue
        assert SETTING_DESCRIPTIONS[preset], preset


def test_every_preset_has_an_image_world_anchor() -> None:
    # The anchor is what keeps a medieval hut from growing a modern house: it
    # must exist for every real preset, and stay empty for Custom/unknown.
    for preset in SETTING_OPTIONS:
        if preset in ("Custom", "Random"):
            continue
        assert SETTING_ANCHOR_TAGS[preset], preset
    assert "medieval" in setting_anchor("Medieval kingdom")
    assert setting_anchor("Custom", "my own world") == ""
    assert setting_anchor("Made-up universe") == ""
    for preset in SETTING_OPTIONS:
        if preset in ("Custom", "Random"):
            continue
        assert SETTING_DESCRIPTIONS[preset], preset


def test_custom_and_random_stay_at_the_end() -> None:
    assert SETTING_OPTIONS[-2:] == ["Custom", "Random"]
    assert GENRE_OPTIONS[-1] == "Random"


def test_setting_description_custom_uses_free_text() -> None:
    assert setting_description("Custom", "  my own world ") == "my own world"
    assert "medieval kingdom" in setting_description("Medieval kingdom", None)


def test_neutral_culture_follows_language() -> None:
    assert "Russian" in effective_culture(None, "Russian")
    assert "Russian" in effective_culture("Match story language", "Russian")
    assert effective_culture("East Asian", "Russian") == "East Asian"


def test_naming_culture_falls_back_to_setting_culture() -> None:
    assert effective_naming_culture(None, "Slavic/Russian", "English") == "Slavic/Russian"
    assert effective_naming_culture("East Asian", "Slavic/Russian", "English") == "East Asian"
    assert "English" in effective_naming_culture(None, None, "English")


def test_resolve_randoms_picks_concrete_presets() -> None:
    data = {"setting": "Random", "genres": ["Random", "Horror"], "tone": "Random"}
    for _ in range(20):
        resolved = resolve_randoms(data)
        assert resolved["setting"] not in ("Custom", "Random")
        assert "Random" not in resolved["genres"]
        assert "Horror" in resolved["genres"]
        assert len(resolved["genres"]) == 2
        assert len(set(resolved["genres"])) == 2  # no duplicates
        assert resolved["tone"] != "Random"
    assert data["setting"] == "Random"  # input dict not mutated


def test_max_genres_matches_schema() -> None:
    import pytest
    from app.schemas import StoryCreate

    assert MAX_GENRES == 5
    # five genres accepted
    StoryCreate(
        setting="Modern city", genres=["Drama", "Comedy", "Romance", "Action", "Mystery"],
        tone="Light", length="short", language="English",
    )
    # six genres rejected
    with pytest.raises(ValueError):
        StoryCreate(
            setting="Modern city",
            genres=["Drama", "Comedy", "Romance", "Action", "Mystery", "Horror"],
            tone="Light", length="short", language="English",
        )

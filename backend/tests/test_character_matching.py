"""Shared fuzzy character-name matching (the duplicate-character guard)."""

from app.models import Character
from app.services.character_matching import (
    find_character,
    is_hero_placeholder,
    normalize_name,
)


def _char(name: str, is_hero: bool = False) -> Character:
    return Character(story_id=1, name=name, is_hero=is_hero)


def test_exact_match_is_case_insensitive_cyrillic() -> None:
    characters = [_char("Лирна", is_hero=True)]
    assert find_character(characters, "лирна") is characters[0]
    assert find_character(characters, "  ЛИРНА ") is characters[0]


def test_hero_placeholder_names_are_recognized() -> None:
    # The "__hero__" sentinel belongs to characters_in_scene only; a model that
    # copies it (or a bare "hero"/"player") into "characters" means the player.
    for name in ("__hero__", "_hero_", "hero", "Hero", " hero. ", "the hero",
                 "HEROINE", "player", "protagonist", "you",
                 "главный герой", "Героиня", "игрок", "ГГ"):
        assert is_hero_placeholder(name), name


def test_real_names_are_not_hero_placeholders() -> None:
    for name in ("Эльвира", "Kaelen", "Warden Hale", "Мать Эльвиры", "Hera", "Heroic Smith", ""):
        assert not is_hero_placeholder(name), name


def test_prefix_match_merges_title_and_short_name() -> None:
    characters = [_char("Мэр города"), _char("Капитан Варго")]
    assert find_character(characters, "Мэр") is characters[0]
    assert find_character(characters, "Варго") is characters[1]


def test_shared_descriptor_token_merges_redescribed_character() -> None:
    # The narrator re-titled the same person; "странник" is a lowercase
    # descriptor in "Тайный странник", so the reports merge.
    characters = [_char("Тайный странник")]
    assert find_character(characters, "Странник в чёрном") is characters[0]
    assert find_character(characters, "Старый странник") is characters[0]


def test_shared_surname_does_not_merge_distinct_people() -> None:
    # "Петров" is a capitalized surname in both, not a lowercase descriptor.
    characters = [_char("Иван Петров")]
    assert find_character(characters, "Ольга Петрова") is None
    assert find_character(characters, "Олег Петров") is None


def test_genitive_hero_name_does_not_merge() -> None:
    # "Бабушка Лирны" is a different person from the hero "Лирна"; the tokens
    # differ ("лирны" != "лирна"), so no match.
    characters = [_char("Лирна", is_hero=True)]
    assert find_character(characters, "Бабушка Лирны") is None


def test_two_title_twins_do_not_merge() -> None:
    # Two different grandmothers: the shared word is the leading title in
    # both names, never a non-initial descriptor.
    characters = [_char("Бабушка Лирны")]
    assert find_character(characters, "Бабушка Зина") is None


def test_unknown_name_returns_none() -> None:
    characters = [_char("Гаррет")]
    assert find_character(characters, "Эйра") is None
    assert find_character(characters, "") is None


def test_normalize_name_collapses_whitespace_and_case() -> None:
    assert normalize_name("  Тайный   Странник ") == "тайный странник"

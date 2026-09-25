"""Shared character-name matching.

The narrator is free-form with names: it reports "Странник в чёрном" a turn
after introducing "Тайный странник", and an exact-or-nothing lookup would
spawn a duplicate character (and a second, different portrait). All name
resolution — new-character reports, portrait updates, scene illustrations,
reference portraits — goes through `find_character` so every path benefits
from the same fuzzy rules.
"""

from collections.abc import Sequence

from ..models import Character

# Joiners that carry no identity ("Странник в чёрном" ~ "Странник").
_NAME_STOPWORDS = {
    "в", "и", "с", "о", "у", "к", "из",
    "the", "of", "a", "an", "in", "on", "de", "van", "von", "le", "la",
}


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


# Names that mean "the player character", not a character of their own. The
# narrator is told to use the "__hero__" sentinel in `characters_in_scene` and
# to keep the hero OUT of `characters`, but small models mix the two fields up
# and report the sentinel (or a bare "hero"/"player") as a character NAME —
# which created a second hero row with its own wasted portrait job.
HERO_PLACEHOLDER_NAMES = {
    "hero", "the hero", "heroine", "the heroine",
    "player", "the player", "player character", "protagonist",
    "main character", "main hero", "you",
    "герой", "героиня", "главный герой", "главная героиня",
    "игрок", "персонаж игрока", "протагонист", "гг",
}


def is_hero_placeholder(name: str) -> bool:
    """True when a reported "character name" really means the player character.

    Underscores (the `__hero__` sentinel), case and surrounding punctuation are
    ignored, so "__hero__", "Hero." and "the hero" are all the same thing.
    """
    plain = " ".join((name or "").casefold().replace("_", " ").split())
    return plain.strip(".,!?;:—–-") in HERO_PLACEHOLDER_NAMES


def _significant_tokens(name: str) -> set[str]:
    """Identity-carrying words of a name: long enough, not a joiner."""
    return {
        token
        for token in normalize_name(name).split()
        if len(token) >= 4 and token not in _NAME_STOPWORDS
    }


def _descriptor_tokens(raw_name: str) -> set[str]:
    """Lowercase non-initial words — title-like descriptors ('странник' in
    'Тайный странник'), as opposed to capitalized proper names. This is what
    keeps 'Иван Петров' and 'Ольга Петров' (a shared surname) apart while
    still merging two descriptions of the same stranger."""
    words = raw_name.split()
    return {
        normalize_name(word)
        for word in words[1:]
        if word[:1].islower() and len(normalize_name(word)) >= 4
    }


def find_character(characters: Sequence[Character], name: str) -> Character | None:
    """Resolve a narrator-supplied name to a known character.

    Three passes, most exact first:
    1. exact case-insensitive match;
    2. prefix match ("Мэр" -> "Мэр города") or a one-word name matching a full
       token of the other ("Варго" -> "Капитан Варго");
    3. shared significant token that is a lowercase descriptor in at least
       one of the names ("Тайный странник" -> "Странник в чёрном").
    """
    candidate = normalize_name(name)
    if not candidate:
        return None
    for character in characters:
        if normalize_name(character.name) == candidate:
            return character
    candidate_tokens = candidate.split()
    for character in characters:
        known = normalize_name(character.name)
        if known.startswith(candidate) or candidate.startswith(known):
            return character
        known_tokens = known.split()
        if (len(candidate_tokens) == 1 and candidate_tokens[0] in known_tokens) or (
            len(known_tokens) == 1 and known_tokens[0] in candidate_tokens
        ):
            return character
    candidate_tokens = _significant_tokens(name)
    if candidate_tokens:
        candidate_descriptors = _descriptor_tokens(name)
        for character in characters:
            shared = candidate_tokens & _significant_tokens(character.name)
            if shared and (
                shared & candidate_descriptors
                or shared & _descriptor_tokens(character.name)
            ):
                return character
    return None

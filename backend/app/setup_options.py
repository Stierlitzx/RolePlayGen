"""Setup option lists and preset descriptions.

Single source of truth for the setup screen: the frontend renders whatever
`GET /api/setup-options` serves, so lists are extended here only.
"""

import random
from typing import Any

# How many genres the player may combine in one story.
MAX_GENRES = 3

SETTING_OPTIONS = [
    "Medieval kingdom",
    "Space station",
    "Modern city",
    "Post-apocalypse",
    "Wizard school",
    "Wild West",
    "Underwater world",
    "Cyberpunk metropolis",
    "High fantasy epic",
    "Noir detective city",
    "Horror mansion",
    "Historical drama",
    "Superhero city",
    "Fairy tale kingdom",
    "Pirate seas",
    "Dystopia",
    "Steampunk",
    "Wuxia / martial arts",
    "Survival island",
    "Cosmic horror",
    "Slice-of-life school",
    "Custom",
    "Random",
]

# Short internal world description per preset, fed to the narrator prompt.
SETTING_DESCRIPTIONS = {
    "Medieval kingdom": "a classic medieval kingdom of castles, feudal lords, guilds and old superstitions",
    "Space station": "an isolated space station with tight corridors, fragile life support and corporate politics",
    "Modern city": "a present-day big city with ordinary life hiding secrets, crime and ambition",
    "Post-apocalypse": "a ruined world after the collapse, scarce resources, roaming gangs and fragile settlements",
    "Wizard school": "a school of magic with rival houses, strict mentors, forbidden libraries and young mages",
    "Wild West": "a frontier of dusty towns, gunslingers, sheriffs, gold fever and lawless badlands",
    "Underwater world": "an underwater realm of sunken ruins, pressure domes, sea creatures and deep trenches",
    "Cyberpunk metropolis": "a neon megacity of megacorps, implants, hackers and street-level survival",
    "High fantasy epic": "a sweeping epic fantasy world of ancient prophecies, great kingdoms and rising darkness",
    "Noir detective city": "a rain-soaked noir city of detectives, femme fatales, corruption and smoky bars",
    "Horror mansion": "an isolated mansion or asylum with a dark past, locked rooms and something that watches",
    "Historical drama": "a grounded historical period with court intrigue, social rules and real-world stakes",
    "Superhero city": "a modern city of caped heroes, villains, secret identities and collateral damage",
    "Fairy tale kingdom": "a fairy tale kingdom of enchanted forests, curses, talking animals and hidden morals",
    "Pirate seas": "the age of sail: pirate crews, naval hunters, treasure maps and lawless ports",
    "Dystopia": "a totalitarian dystopia of surveillance, propaganda, forbidden feelings and quiet resistance",
    "Steampunk": "a steampunk world of airships, clockwork, brass machinery and industrial barons",
    "Wuxia / martial arts": "a wuxia world of martial sects, honor codes, wandering swordsmen and hidden masters",
    "Survival island": "a deserted island where survival, scarce supplies and strange discoveries drive every day",
    "Cosmic horror": "a world under the shadow of incomprehensible cosmic entities, cults and eroding sanity",
    "Slice-of-life school": "a cozy school slice-of-life of clubs, friendships, festivals and small everyday dramas",
}

GENRE_OPTIONS = [
    "Fantasy",
    "Science fiction",
    "Detective",
    "Horror",
    "Adventure",
    "Romance",
    "Thriller",
    "Comedy",
    "Drama",
    "Action",
    "Mystery",
    "Slice of life",
    "Historical",
    "Psychological",
    "Mythology",
    "Cyberpunk",
    "Dark fantasy",
    "Survival",
    "Political intrigue",
    "Tragedy",
    "Random",
]

TONE_OPTIONS = ["Dark", "Serious", "Light", "Ironic", "Epic", "Cozy", "Random"]

LENGTH_OPTIONS = [
    {"value": "short", "label": "Short (50 turns)"},
    {"value": "medium", "label": "Medium (100 turns)"},
    {"value": "long", "label": "Long (no limit)"},
    {"value": "custom", "label": "Custom (choose your own count, min 50)"},
]

LANGUAGE_OPTIONS = ["Russian", "English", "Kazakh"]

# "Match story language" is the neutral default: culture follows the language,
# exactly how stories behaved before this field existed.
CULTURE_OPTIONS = [
    "Match story language",
    "Slavic/Russian",
    "Western European",
    "East Asian",
    "Norse/Scandinavian",
    "Middle Eastern",
    "South Asian",
    "Latin American",
    "African",
    "Generic/international fantasy",
    "Custom",
]

MODEL_OPTIONS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]

_SPECIAL = {"Custom", "Random"}
_NEUTRAL_CULTURE = "Match story language"


def setting_description(setting: str, custom_setting: str | None) -> str:
    """Short world description for the narrator prompt."""
    if setting == "Custom":
        return (custom_setting or "a custom world invented together with the player").strip()
    return SETTING_DESCRIPTIONS.get(setting, setting)


def effective_culture(setting_culture: str | None, language: str) -> str:
    """Neutral/unset culture keeps the old behavior: culture follows language."""
    if not setting_culture or setting_culture == _NEUTRAL_CULTURE:
        return f"the culture naturally associated with the {language} language"
    return setting_culture


def effective_naming_culture(naming_culture: str | None, setting_culture: str | None, language: str) -> str:
    """Naming override falls back to the setting culture when left empty."""
    if naming_culture and naming_culture.strip():
        return naming_culture.strip()
    return effective_culture(setting_culture, language)


def resolve_randoms(data: dict[str, Any]) -> dict[str, Any]:
    """Replace Random picks in the settings dict with concrete uniform choices.

    `Random` picks uniformly among all presets except `Custom` and `Random`.
    """
    resolved = dict(data)
    if resolved.get("setting") == "Random":
        resolved["setting"] = random.choice([s for s in SETTING_OPTIONS if s not in _SPECIAL])
    genres = [g for g in resolved.get("genres", []) if g != "Random"]
    random_slots = len(resolved.get("genres", [])) - len(genres)
    pool = [g for g in GENRE_OPTIONS if g != "Random" and g not in genres]
    for _ in range(random_slots):
        if not pool:
            break
        pick = random.choice(pool)
        genres.append(pick)
        pool.remove(pick)
    if not genres:
        genres = [random.choice([g for g in GENRE_OPTIONS if g != "Random"])]
    resolved["genres"] = genres
    if resolved.get("tone") == "Random":
        resolved["tone"] = random.choice([t for t in TONE_OPTIONS if t != "Random"])
    return resolved


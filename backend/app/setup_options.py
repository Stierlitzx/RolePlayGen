"""Setup option lists and preset descriptions.

Single source of truth for the setup screen: the frontend renders whatever
`GET /api/setup-options` serves, so lists are extended here only.
"""

import random
from typing import Any

# How many genres the player may combine in one story.
MAX_GENRES = 5

# Hero gender choice; "Unspecified" leaves it to the narrator.
HERO_GENDER_OPTIONS = ["Unspecified", "Female", "Male"]
DEFAULT_HERO_GENDER = "Unspecified"

# The image tag a gender maps to in appearance tags (drives 1girl/1boy).
GENDER_TAGS = {"Female": "1girl", "Male": "1boy"}

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
    "Medieval kingdom": "a classic medieval kingdom of castles and world",
    "Space station": "an isolated space station with tight corridors, fragile life support and corporate politics",
    "Modern city": "a present-day big city with ordinary life",
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

# PEGI-like age ratings. The rating gates both the narration and the images.
AGE_RATING_OPTIONS = ["3+", "7+", "12+", "16+", "18+"]
DEFAULT_AGE_RATING = "12+"
ADULT_RATING = "18+"

# Extra genres unlocked only for 18+ stories.
ADULT_GENRE_OPTIONS = ["Hentai", "Erotica", "Slasher / gore", "Extreme horror"]

# Art style presets for the image pipeline. Each maps to a phrase appended to
# every image prompt of the story. These are SENTENCES, not danbooru tags:
# Qwen-Image-2.1 was trained on natural captions, and a single word like
# "anime style" loses against a long photographic description (see DECISIONS
# 2026-09-26). No negative tags: the workflow runs at cfg=1 and has no
# negative-prompt node. NB: no "flat"/"muted"/"soft colours" — those words are
# what made the portraits look washed out and grey.
IMAGE_STYLE_TAGS = {
    "Anime (default)": {
        "positive": (
            "a modern anime illustration in full colour, clean line art, bold cel "
            "shading, rich saturated colours, bright lighting, expressive eyes"
        ),
        "negative": "",
    },
    "Semi-realistic": {
        "positive": "semi-realistic, painterly",
        "negative": "",
    },
    "Cinematic realistic": {
        "positive": "realistic, cinematic lighting, film still",
        "negative": "",
    },
    "Comic book": {
        "positive": "comic book art, bold outlines, flat colors",
        "negative": "",
    },
    "Watercolor storybook": {
        "positive": "watercolor painting, storybook illustration, soft colors",
        "negative": "",
    },
}
IMAGE_STYLE_OPTIONS = list(IMAGE_STYLE_TAGS)
DEFAULT_IMAGE_STYLE = IMAGE_STYLE_OPTIONS[0]

# Narrator voice presets. The fragment is appended to the narrator system
# prompt for every turn of the story. "Classic" adds nothing — exactly the
# behavior stories had before this feature existed.
NARRATOR_STYLE_FRAGMENTS = {
    "Classic narrator": "",
    "Noir": (
        "NARRATOR STYLE: hard-boiled noir. Cynical, terse, metaphor-rich prose; "
        "rain, smoke and moral decay; the narrator judges everyone quietly."
    ),
    "Epic saga": (
        "NARRATOR STYLE: elevated epic-saga voice. Grand, mythic phrasing; "
        "events feel like verses of a legend being sung around a fire."
    ),
    "Light and witty": (
        "NARRATOR STYLE: playful and ironic. Dry humor, gentle mockery of genre "
        "tropes, warm sarcasm — without ever breaking the fourth wall or the stakes."
    ),
    "Gothic dread": (
        "NARRATOR STYLE: gothic slow-burn. Dense atmosphere, decay, whispers and "
        "dread building under ordinary scenes; beautiful but unsettling prose."
    ),
    "Disco Elysium": (
        "NARRATOR STYLE: Disco Elysium. Second person, present tense. The hero's "
        "fractured psyche speaks in capitalized skill-voices that interrupt the "
        "narration with their own lines, e.g. ELECTROCHEMISTRY: …, LOGIC: …, "
        "INLAND EMPIRE: … Let objects, places and memories talk. Surreal, "
        "self-deprecating, unexpectedly profound. Weave 1-3 skill-voice "
        "interjections into most turns, formatted as their own paragraphs."
    ),
}
NARRATOR_STYLE_OPTIONS = list(NARRATOR_STYLE_FRAGMENTS)
DEFAULT_NARRATOR_STYLE = NARRATOR_STYLE_OPTIONS[0]


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


# Era/world anchor tags per setting preset, appended to every IMAGE prompt of a
# story (scene and portrait alike). The narrator is told to keep the picture
# inside the established world, but a small model cheerfully writes "wooden hut"
# in a medieval story and lets the image model add a modern house next door — the
# setting is therefore carried as deterministic tags, not as a prompt wish.
# Positive phrasing only: the workflow runs at cfg=1, so there is no negative
# prompt to put "not modern" into.
SETTING_ANCHOR_TAGS = {
    "Medieval kingdom": "medieval fantasy setting, rustic stone and timber architecture, thatched roofs, period-accurate props, no modern objects",
    "Space station": "science fiction setting, futuristic metal corridors, technology panels, space station interior",
    "Modern city": "contemporary urban setting, modern city street, glass and concrete architecture",
    "Post-apocalypse": "post-apocalyptic setting, ruined buildings, overgrown rubble, scavenged tech",
    "Wizard school": "fantasy magic academy, old stone halls, arcane library, candlelight",
    "Wild West": "wild west frontier town, wooden saloon buildings, dusty street, 19th century",
    "Underwater world": "underwater setting, submerged ruins, coral, drifting light caustics",
    "Cyberpunk metropolis": "cyberpunk city, neon signs, holographic advertisements, wet asphalt",
    "High fantasy epic": "high fantasy setting, ancient kingdoms, magical landscape, period architecture",
    "Noir detective city": "film noir city, 1940s streets, rain-slicked asphalt, vintage cars",
    "Horror mansion": "victorian gothic mansion, candlelit dusty corridors, dark wood panelling",
    "Historical drama": "historical period setting, period-accurate architecture and clothing, pre-modern era",
    "Superhero city": "modern metropolis, skyscrapers, comic book city skyline",
    "Fairy tale kingdom": "fairy tale village, enchanted forest, quaint cottages",
    "Pirate seas": "age of sail, wooden sailing ships, tropical port town, 18th century",
    "Dystopia": "dystopian city, brutalist concrete blocks, propaganda banners, surveillance cameras",
    "Steampunk": "steampunk setting, brass machinery, steam pipes, victorian technology",
    "Wuxia / martial arts": "ancient chinese setting, traditional wooden architecture, bamboo forest, hanfu",
    "Survival island": "deserted island, palm trees, sandy shore, wild jungle",
    "Cosmic horror": "cosmic horror atmosphere, eldritch fog, impossible geometry, decaying old town",
    "Slice-of-life school": "modern japanese school, classroom, school uniforms, cherry blossoms",
}


def setting_anchor(setting: str | None, custom_setting: str | None = None) -> str:
    """Image tags that pin the story's world, or "" when the preset has none.

    "Custom" worlds carry no anchor: the player's own freeform setting is the
    only description available, and inventing an era for it would fight it.
    """
    if not setting or setting == "Custom":
        return ""
    return SETTING_ANCHOR_TAGS.get(setting, "")


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


def narrator_style_fragment(narrator_style: str | None) -> str:
    """Prompt fragment for the chosen narrator voice; empty for classic/unset."""
    if not narrator_style:
        return ""
    return NARRATOR_STYLE_FRAGMENTS.get(narrator_style, "")


_RATING_CLAUSES = {
    "3+": "wholesome, all-ages content: no violence beyond cartoonish, no romance beyond innocent, no swearing, scary moments stay mild",
    "7+": "family-friendly content: mild fantasy violence, no swearing, no sexual content, frightening moments stay brief and safe",
    "12+": "teen content: action violence without gore, romance without sexual content, mild language only",
    "16+": "mature content: realistic violence without lingering gore, sexual references and fade-to-black at most, stronger language allowed",
    "18+": "adult content: unrestricted adult themes, strong language and dark subject matter allowed and more sexual content, with sexualized female characters",
}


_CHOICE_PROMPT_FALLBACKS = {
    "Russian": "Что ты сделаешь?",
    "English": "What will you do?",
    "Kazakh": "Не істейсің?",
}


def choice_prompt_fallback(language: str | None) -> str:
    """The question used when the narrator sends an empty choice prompt.

    The prompt is cosmetic UI text ("What will you do?" above the options), so a
    model that forgets it must never cost the player a turn.
    """
    return _CHOICE_PROMPT_FALLBACKS.get(str(language or ""), _CHOICE_PROMPT_FALLBACKS["English"])


def age_rating_clause(params: dict[str, Any]) -> str:
    """AGE RATING prompt section, or an empty string for stories created before
    ratings existed (their voice must not change retroactively)."""
    rating = params.get("age_rating")
    if not rating:
        return ""
    clause = _RATING_CLAUSES.get(str(rating))
    if clause is None:
        return ""
    lines = [
        f"AGE RATING: This story is rated {rating} — keep every turn within {clause}.",
    ]
    if rating == ADULT_RATING:
        explicit = bool(params.get("explicit_sexual"))
        gore = bool(params.get("graphic_violence"))
        if explicit:
            lines.append(
                "The player explicitly opted into explicit sexual content: it is permitted "
                "and expected when the story calls for it."
            )
        else:
            lines.append("No explicit sexual detail — keep intimacy non-graphic.")
        if gore:
            lines.append(
                "The player explicitly opted into graphic violence: gore and brutality "
                "may be depicted in detail when the story calls for it."
            )
        else:
            lines.append("No graphic gore — violence stays non-gratuitous.")
    lines.append(
        "Absolute rules at every rating: every character in sexual or romantic content is an adult; "
        "the player's content restrictions override everything; the rating sets the content ceiling, "
        "not the prose quality."
    )
    return "\n".join(lines)


def image_style_tags(image_style: str | None) -> dict[str, str]:
    """Positive/negative style tags for the story's images; empty when unset."""
    if not image_style:
        return {"positive": "", "negative": ""}
    return IMAGE_STYLE_TAGS.get(image_style, {"positive": "", "negative": ""})


def images_are_explicit(params: dict[str, Any]) -> bool:
    """Only an 18+ story with the explicit-sexual flag gets explicit-rated images."""
    return params.get("age_rating") == ADULT_RATING and bool(params.get("explicit_sexual"))


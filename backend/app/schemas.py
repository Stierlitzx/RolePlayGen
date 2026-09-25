from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .setup_options import (
    ADULT_GENRE_OPTIONS,
    ADULT_RATING,
    AGE_RATING_OPTIONS,
    HERO_GENDER_OPTIONS,
    IMAGE_STYLE_OPTIONS,
    NARRATOR_STYLE_OPTIONS,
)

ChoiceMode = Literal["open", "locked", "binary"]
PlayerInputType = Literal["option", "custom", "start"]
StoryStatus = Literal["active", "finished"]


class ChoiceOption(BaseModel):
    id: Literal["a", "b", "c", "d"]
    text: str = Field(min_length=1, max_length=300)


class Choice(BaseModel):
    mode: ChoiceMode
    options: list[ChoiceOption]
    allow_custom: bool
    prompt: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_mode(self) -> "Choice":
        count = len(self.options)
        if self.mode == "open" and not (3 <= count <= 4 and self.allow_custom):
            raise ValueError("open mode requires 3-4 options and allow_custom=true")
        if self.mode == "locked" and not (2 <= count <= 4 and not self.allow_custom):
            raise ValueError("locked mode requires 2-4 options and allow_custom=false")
        if self.mode == "binary" and not (count == 2 and not self.allow_custom):
            raise ValueError("binary mode requires exactly 2 options and allow_custom=false")
        expected_ids = ["a", "b", "c", "d"][:count]
        if [option.id for option in self.options] != expected_ids:
            raise ValueError("option ids must be consecutive letters starting with a")
        return self


class TurnState(BaseModel):
    scene: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
    facts: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("facts")
    @classmethod
    def non_empty_facts(cls, value: list[str]) -> list[str]:
        if any(not fact.strip() for fact in value):
            raise ValueError("facts cannot contain empty values")
        return value


class CharacterReport(BaseModel):
    """One character entry the narrator reports for the current turn."""

    name: str = Field(min_length=1, max_length=100)
    is_new: bool = False
    role: str | None = Field(default=None, max_length=200)
    relationship: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    appearance_tags: str | None = Field(default=None, max_length=1000)
    # Rough age in ENGLISH words ("early thirties", "a child of about eight",
    # "ageless"), never shown to the player: it exists so a mother is not painted
    # as a teenager. Omit it for a creature without a human age (a cat, a
    # dragon) or write "ageless" for an immortal.
    age: str | None = Field(default=None, max_length=60)
    # Per-portrait variation (never part of the fixed appearance_tags).
    pose: str | None = Field(default=None, max_length=200)
    expression: str | None = Field(default=None, max_length=200)
    # Portrait evolution: update = new persistent look; revert = back to previous.
    portrait_update: bool = False
    portrait_revert: bool = False


class HeroReport(BaseModel):
    """Hero identity/appearance: reported on the first turn, and again whenever the
    hero's persistent look changes (see portrait_update / portrait_revert)."""

    name: str | None = Field(default=None, max_length=100)
    appearance_tags: str | None = Field(default=None, max_length=1000)
    # The hero's first portrait is a portrait like any other: the narrator picks
    # its pose, expression and gaze. Empty values fall back to a generic
    # standing look (see `image_service._portrait_framing`).
    pose: str | None = Field(default=None, max_length=200)
    expression: str | None = Field(default=None, max_length=200)
    # Same rule as for the NPCs: a rough age in English words, for the picture
    # model only. Never shown to the player.
    age: str | None = Field(default=None, max_length=60)
    # The hero evolves like every other character. A look that PERSISTS (a
    # disguise, new clothes or armor, hair cut, a wound that stays) repaints the
    # hero's portrait and every later scene prompt; the previous look comes back
    # with portrait_revert. One-scene details (mud, sweat, rain) belong in
    # image_prompt, not here.
    portrait_update: bool = False
    portrait_revert: bool = False


class TurnContract(BaseModel):
    narration: str = Field(min_length=1, max_length=30000)
    choice: Choice | None
    state: TurnState
    is_ending: bool
    image_prompt: str | None = Field(default=None, max_length=2000)
    # Plain string, not a Literal: small narrators sometimes write "medium" or
    # "square" — the engine normalizes anything unexpected to "wide" (SPEC).
    image_format: str | None = Field(default=None, max_length=20)
    characters: list[CharacterReport] | None = Field(default=None, max_length=20)
    characters_in_scene: list[str] | None = Field(default=None, max_length=10)
    hero: HeroReport | None = None
    # Service fields for the "note to the narrator" feature: when the turn
    # message carries a PLAYER NOTE, the narrator classifies it here so the
    # backend knows whether to pin it as a lasting fact or treat it as a
    # one-shot event. Both stay null when there is no note (or the note is
    # meaningless spam) — the backend then changes nothing.
    note_type: Literal["fact", "event"] | None = None
    normalized_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_ending_choice(self) -> "TurnContract":
        if self.is_ending and self.choice is not None:
            raise ValueError("ending turns must have choice=null")
        if not self.is_ending and self.choice is None:
            raise ValueError("non-ending turns must include a choice")
        return self


class StoryCreate(BaseModel):
    setting: str = Field(min_length=1, max_length=200)
    custom_setting: str | None = Field(default=None, max_length=3000)
    genres: list[str] = Field(min_length=1, max_length=5)
    tone: str = Field(min_length=1, max_length=100)
    hero_role: str | None = Field(default=None, max_length=3000)
    hero_name: str | None = Field(default=None, max_length=200)
    hero_appearance: str | None = Field(default=None, max_length=3000)
    hero_gender: str | None = Field(default=None, max_length=20)
    length: Literal["short", "medium", "long", "custom"]
    custom_turns: int | None = Field(default=None, ge=50, le=500)
    # Which text model backend narrates this story: "gemini" (Google cloud),
    # "local" (the OpenAI-compatible server from OPENAI_* in .env), or a named
    # cloud provider — "groq" / "openrouter" / "mistral" (own keys in .env).
    # None = the server's default LLM_PROVIDER, which keeps stories created
    # before this field unchanged.
    llm_provider: Literal["gemini", "local", "groq", "openrouter", "mistral"] | None = None

    model: str | None = Field(default=None, max_length=100)
    content_restrictions: str | None = Field(default=None, max_length=6000)
    language: Literal["Russian", "English", "Kazakh"] = "Russian"
    custom_details: str | None = Field(default=None, max_length=15000)
    setting_culture: str | None = Field(default=None, max_length=100)
    naming_culture: str | None = Field(default=None, max_length=100)
    intro_exposition: bool = True
    age_rating: str | None = Field(default=None, max_length=10)
    explicit_sexual: bool = False
    graphic_violence: bool = False
    image_style: str | None = Field(default=None, max_length=100)
    narrator_style: str | None = Field(default=None, max_length=100)
    # Optional player photo of the hero, as a data URL ("data:image/png;base64,…").
    # It is written under IMAGE_DIR and becomes image_1 of every scene picture,
    # so the story is illustrated around the face the player actually chose.
    # Empty / absent = the old text-to-image behaviour, unchanged.
    hero_image: str | None = Field(default=None, max_length=12_000_000)

    @model_validator(mode="after")
    def custom_length_needs_turns(self) -> "StoryCreate":
        if self.length == "custom" and self.custom_turns is None:
            raise ValueError("custom length requires custom_turns (50-500)")
        return self

    @model_validator(mode="after")
    def adult_options_require_adult_rating(self) -> "StoryCreate":
        if self.age_rating is not None and self.age_rating not in AGE_RATING_OPTIONS:
            raise ValueError(f"age_rating must be one of {AGE_RATING_OPTIONS}")
        if self.image_style is not None and self.image_style not in IMAGE_STYLE_OPTIONS:
            raise ValueError("unknown image_style")
        if self.narrator_style is not None and self.narrator_style not in NARRATOR_STYLE_OPTIONS:
            raise ValueError("unknown narrator_style")
        if self.hero_gender is not None and self.hero_gender not in HERO_GENDER_OPTIONS:
            raise ValueError(f"hero_gender must be one of {HERO_GENDER_OPTIONS}")
        if self.age_rating != ADULT_RATING:
            if self.explicit_sexual or self.graphic_violence:
                raise ValueError("explicit content options require age_rating 18+")
            adult_used = [g for g in self.genres if g in ADULT_GENRE_OPTIONS]
            if adult_used:
                raise ValueError(f"adult genres require age_rating 18+: {adult_used}")
        return self


class StoryUpdate(StoryCreate):
    pass


class PortraitUpload(BaseModel):
    """A player-supplied picture for one character (the Characters tab)."""

    # Data URL, same encoding as `StoryCreate.hero_image`.
    image: str = Field(min_length=8, max_length=12_000_000)
    # Show it as the character's portrait right away (no GPU job), instead of
    # only keeping it as the reference the picture generator works from.
    use_as_portrait: bool = True


class TurnCreate(BaseModel):
    option_id: Literal["a", "b", "c", "d"] | None = None
    custom_text: str | None = Field(default=None, max_length=1500)
    # Optional "note to the narrator", sent together with the action. It never
    # replaces the action: exactly one of option_id/custom_text is still
    # required, and an empty/whitespace note is treated as no note at all.
    note_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def exactly_one_input(self) -> "TurnCreate":
        has_option = self.option_id is not None
        has_custom = self.custom_text is not None and self.custom_text.strip() != ""
        if has_option == has_custom:
            raise ValueError("provide exactly one of option_id or custom_text")
        return self


class TurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    index: int
    player_input_type: PlayerInputType
    player_input_text: str | None
    note_text: str | None = None
    note_type: str | None = None
    narration: str
    choice: dict[str, Any] | None
    state: dict[str, Any]
    is_ending: bool
    image_status: str = "none"
    image_format: str | None = None
    image_url: str | None = None
    image_error: str | None = None
    # What was actually sent to the picture model for this turn ("Image log").
    image_build_log: str | None = None
    created_at: datetime


class StoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    settings: dict[str, Any]
    status: StoryStatus
    max_turns: int | None
    created_at: datetime
    updated_at: datetime
    turns: list[TurnRead] = []
    pinned_facts: list[str] = []

    @field_validator("pinned_facts", mode="before")
    @classmethod
    def _none_means_no_facts(cls, value: Any) -> list[str]:
        # The column is nullable; stories without notes yet store NULL.
        return value if isinstance(value, list) else []


class PinnedFactsRead(BaseModel):
    pinned_facts: list[str]


class StorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    settings: dict[str, Any]
    status: StoryStatus
    max_turns: int | None
    created_at: datetime
    updated_at: datetime
    turn_count: int


class SetupOptions(BaseModel):
    settings: list[str]
    genres: list[str]
    tones: list[str]
    lengths: list[dict[str, str]]
    languages: list[str]
    cultures: list[str]
    max_genres: int
    age_ratings: list[str]
    adult_genres: list[str]
    image_styles: list[str]
    narrator_styles: list[str]
    default_age_rating: str
    default_image_style: str
    default_narrator_style: str
    models: list[str]
    default_model: str
    # Per-story provider choice: all configured providers are served side by
    # side so the setup screen can offer Gemini / Groq / OpenRouter / Mistral /
    # local per story.
    default_provider: Literal["gemini", "local", "groq", "openrouter", "mistral"]
    gemini_models: list[str]
    default_gemini_model: str
    gemini_configured: bool
    local_model: str | None
    local_configured: bool
    groq_model: str | None
    groq_configured: bool
    openrouter_model: str | None
    openrouter_configured: bool
    mistral_model: str | None
    mistral_configured: bool
    hero_genders: list[str]
    default_hero_gender: str

    ai_configured: bool
    mock_llm: bool


class PortraitVersionRead(BaseModel):
    """One entry of a character's portrait history (the gallery)."""

    turn_id: int | None = None
    portrait_url: str | None = None
    current: bool = False


class CharacterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    name: str
    is_hero: bool
    role: str | None
    relationship: str | None
    description: str | None
    first_seen_turn_id: int | None = None
    portrait_status: str
    portrait_url: str | None
    portrait_error: str | None
    # The picture the player uploaded for this character (the Characters tab),
    # if any: the generator works from it and it can be shown as the portrait.
    photo_url: str | None = None
    # What was actually sent to the picture model for the last portrait.
    portrait_build_log: str | None = None
    portrait_history: list[PortraitVersionRead] = []
    created_at: datetime

    @field_validator("portrait_history", mode="before")
    @classmethod
    def _map_history(cls, value: Any) -> list[dict[str, Any]]:
        """Raw JSON entries ({appearance_tags, pose, expression, portrait_path,
        turn_id}) become gallery items with media URLs; the last entry is the
        current look. Entries without a file yet (still generating) get a null
        URL and are skipped by the UI."""
        entries = value if isinstance(value, list) else []
        result = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            path = entry.get("portrait_path")
            result.append(
                {
                    "turn_id": entry.get("turn_id"),
                    "portrait_url": f"/media/{path}" if path else None,
                    "current": index == len(entries) - 1,
                }
            )
        return result

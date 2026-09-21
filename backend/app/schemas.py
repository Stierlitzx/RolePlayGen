from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class HeroReport(BaseModel):
    """Hero identity/appearance, reported once on the first turn."""

    name: str | None = Field(default=None, max_length=100)
    appearance_tags: str | None = Field(default=None, max_length=1000)


class TurnContract(BaseModel):
    narration: str = Field(min_length=1, max_length=30000)
    choice: Choice | None
    state: TurnState
    is_ending: bool
    image_prompt: str | None = Field(default=None, max_length=2000)
    image_format: Literal["portrait", "wide"] | None = None
    characters: list[CharacterReport] | None = Field(default=None, max_length=20)
    characters_in_scene: list[str] | None = Field(default=None, max_length=10)
    hero: HeroReport | None = None

    @model_validator(mode="after")
    def validate_ending_choice(self) -> "TurnContract":
        if self.is_ending and self.choice is not None:
            raise ValueError("ending turns must have choice=null")
        if not self.is_ending and self.choice is None:
            raise ValueError("non-ending turns must include a choice")
        return self


class StoryCreate(BaseModel):
    setting: str = Field(min_length=1, max_length=200)
    custom_setting: str | None = Field(default=None, max_length=300)
    genres: list[str] = Field(min_length=1, max_length=3)
    tone: str = Field(min_length=1, max_length=100)
    hero_role: str | None = Field(default=None, max_length=200)
    hero_name: str | None = Field(default=None, max_length=100)
    length: Literal["short", "medium", "long", "custom"]
    custom_turns: int | None = Field(default=None, ge=50, le=500)
    model: str | None = Field(default=None, max_length=100)
    content_restrictions: str | None = Field(default=None, max_length=500)
    language: Literal["Russian", "English", "Kazakh"] = "Russian"
    custom_details: str | None = Field(default=None, max_length=2000)
    setting_culture: str | None = Field(default=None, max_length=100)
    naming_culture: str | None = Field(default=None, max_length=100)
    intro_exposition: bool = False

    @model_validator(mode="after")
    def custom_length_needs_turns(self) -> "StoryCreate":
        if self.length == "custom" and self.custom_turns is None:
            raise ValueError("custom length requires custom_turns (50-500)")
        return self


class StoryUpdate(StoryCreate):
    pass


class TurnCreate(BaseModel):
    option_id: Literal["a", "b", "c", "d"] | None = None
    custom_text: str | None = Field(default=None, max_length=500)

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
    narration: str
    choice: dict[str, Any] | None
    state: dict[str, Any]
    is_ending: bool
    image_status: str = "none"
    image_format: str | None = None
    image_url: str | None = None
    image_error: str | None = None
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
    models: list[str]
    default_model: str
    ai_configured: bool
    mock_llm: bool


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
    created_at: datetime

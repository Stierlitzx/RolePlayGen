from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import relationship as sa_relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    max_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Facts the player pinned via a "note to the narrator" (type "fact"); they
    # are passed to the model in every following request until deleted.
    pinned_facts: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="story", cascade="all, delete-orphan", order_by="Turn.index"
    )
    characters: Mapped[list["Character"]] = relationship(
        back_populates="story", cascade="all, delete-orphan", order_by="Character.id"
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    player_input_type: Mapped[str] = mapped_column(String(20), nullable=False)
    player_input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional "note to the narrator" sent with the player's action. note_type
    # is the model's classification ("fact"/"event"); note_normalized is the
    # model's neutral reformulation of a fact — kept so a regenerate can roll
    # back exactly the pinned fact this turn added.
    note_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    choice: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_ending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    image_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The ComfyUI job id of the picture being drawn. Persisted so a restart can
    # ADOPT a job that outlived the app (ComfyUI keeps rendering it) instead of
    # discarding a finished picture and marking the turn failed.
    image_prompt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Human-readable record of what was actually sent to the picture model for
    # this turn (mode, steps, seed, references, final positive prompt). The UI's
    # "Image log" shows it verbatim, so a picture that looks wrong can be traced
    # to the prompt that produced it.
    image_build_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    characters_in_scene: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    story: Mapped[Story] = relationship(back_populates="turns")

    @property
    def image_url(self) -> str | None:
        if self.image_status == "done" and self.image_path:
            return f"/media/{self.image_path}"
        return None


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_hero: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    relationship: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Rough age in English words, kept for the picture model only: it is never
    # shown in the UI. Empty = the narrator named no age (a cat, a dragon, or a
    # character whose age simply was not established).
    age: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Version history of the character's look; the latest entry is current:
    # [{"appearance_tags", "pose", "expression", "portrait_path", "turn_id"}]
    portrait_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    first_seen_turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portrait_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    portrait_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portrait_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ComfyUI job id of the portrait being drawn (same restart-adoption reason
    # as Turn.image_prompt_id).
    portrait_prompt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The same record for portraits, shown in the character card's image log.
    portrait_build_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The picture the player uploaded for this character (the Characters tab).
    # It is what the picture generator edits (image_1) and, when the player
    # asked for it, what the portrait card shows.
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # NB: this class has a column named "relationship", which shadows the
    # sqlalchemy.orm function inside the class body — hence the alias.
    story: Mapped[Story] = sa_relationship(back_populates="characters")

    @property
    def portrait_url(self) -> str | None:
        if self.portrait_status == "done" and self.portrait_path:
            return f"/media/{self.portrait_path}"
        return None

    @property
    def photo_url(self) -> str | None:
        return f"/media/{self.photo_path}" if self.photo_path else None

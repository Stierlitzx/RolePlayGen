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
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    choice: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_ending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    image_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    first_seen_turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portrait_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    portrait_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portrait_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # NB: this class has a column named "relationship", which shadows the
    # sqlalchemy.orm function inside the class body — hence the alias.
    story: Mapped[Story] = sa_relationship(back_populates="characters")

    @property
    def portrait_url(self) -> str | None:
        if self.portrait_status == "done" and self.portrait_path:
            return f"/media/{self.portrait_path}"
        return None

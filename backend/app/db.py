from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Add new columns to existing SQLite databases (idempotent)."""
    from sqlalchemy import inspect, text

    wanted_by_table = {
        "stories": {
            "pinned_facts": "JSON",
        },
        "turns": {
            "image_status": "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "image_format": "VARCHAR(20)",
            "image_prompt": "TEXT",
            "image_path": "VARCHAR(500)",
            "image_error": "TEXT",
            "image_prompt_id": "VARCHAR(64)",
            "image_build_log": "TEXT",
            "characters_in_scene": "JSON",
            "note_text": "TEXT",
            "note_type": "VARCHAR(20)",
            "note_normalized": "TEXT",
        },
        "characters": {
            "portrait_history": "JSON",
            "age": "VARCHAR(60)",
            "portrait_prompt_id": "VARCHAR(64)",
            "portrait_build_log": "TEXT",
            "photo_path": "VARCHAR(500)",
        },
    }
    with engine.begin() as conn:
        for table, wanted in wanted_by_table.items():
            existing = {col["name"] for col in inspect(engine).get_columns(table)}
            for name, ddl in wanted.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

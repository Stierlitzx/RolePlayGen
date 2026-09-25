import os
import sys
from collections.abc import Generator
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["MOCK_LLM"] = "true"
os.environ["GEMINI_API_KEY"] = ""
# Tests must not inherit the developer's provider choice from backend/.env.
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["OPENAI_MODEL"] = "llama3.1:8b"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["MISTRAL_API_KEY"] = ""
# Never start image jobs in tests; the backend/.env file enables them locally.
os.environ["IMAGE_GENERATION_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _no_writes_into_the_real_image_dir() -> Generator[None, None, None]:
    """Guard rail: no test may create a file under the real ./data/images.

    The default `image_dir` is relative to the working directory, so a test
    that forgets to pin it silently writes into the developer's own story
    folders. The most recent regression was the upload tests leaving two
    5-byte files in `data/images/1/`.
    """
    real = (Path.cwd() / "data" / "images").resolve()
    before = {path for path in real.rglob("*") if path.is_file()} if real.exists() else set()
    yield
    after = {path for path in real.rglob("*") if path.is_file()} if real.exists() else set()
    leaked = sorted(str(path.relative_to(real)) for path in after - before)
    assert not leaked, (
        "tests wrote into the real IMAGE_DIR: " + ", ".join(leaked)
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # `image_dir` MUST be a temp path: the default is the real ./data/images, and
    # a test that writes a picture (an upload, a mock image) would drop junk into
    # the developer's own story folders.
    return Settings(
        gemini_api_key="",
        model_name="test-model",
        database_url="sqlite:///:memory:",
        max_tokens=1200,
        mock_llm=True,
        image_dir=str(tmp_path / "images"),
    )


@pytest.fixture
def client(db_session: Session, settings: Settings) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield db_session

    def override_settings() -> Settings:
        return settings

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

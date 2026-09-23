"""Docs consistency checks.

1. Every setting read in `config.py` (a `Settings` field) is documented in
   `.env.example`.
2. Every `/api/...` path listed in `docs/ARCHITECTURE.md` exists in the
   FastAPI route table.

No prose is checked — only these two machine-verifiable facts.
"""

import re
from pathlib import Path

from app.config import Settings
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_covers_config() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"(?m)^([A-Z0-9_]+)=", env_example))
    missing = [
        field.upper()
        for field in Settings.model_fields
        if field.upper() not in documented
    ]
    assert not missing, (
        f"Settings fields missing from .env.example: {', '.join(missing)}"
    )


def test_architecture_api_paths_exist() -> None:
    doc = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    # Paths as written in the doc, with any {placeholder} normalized away.
    doc_paths = {
        re.sub(r"\{[^}]*\}", "{}", match)
        for match in re.findall(r"/api/[\w{}/-]+", doc)
    }
    # app.openapi() resolves the lazily-included routers into the full route
    # table (app.routes only holds _IncludedRouter wrappers in this version).
    route_paths = {
        re.sub(r"\{[^}]*\}", "{}", path) for path in app.openapi()["paths"]
    }
    missing = sorted(doc_paths - route_paths)
    assert not missing, (
        f"API paths documented in docs/ARCHITECTURE.md but missing from the "
        f"FastAPI route table: {', '.join(missing)}"
    )

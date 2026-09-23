# Operational gotchas (read before touching anything)

- **`uvicorn --reload` watches only `.py` files — after editing `.env` the backend MUST be restarted manually.** "Gemini is not configured" with a key in `.env` = stale process. Also the project lives in OneDrive, where WatchFiles reloads are unreliable — restart after code changes too (the last server runs WITHOUT `--reload` for this reason).
- Run the backend from `backend/` (`Settings` reads `.env` relative to CWD): `cd backend && .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`.
- `backend/.env` is gitignored; `backend/tests/conftest.py` pins `OPENAI_MODEL`/`LLM_PROVIDER`/`MOCK_LLM` so tests never inherit the developer's `.env` — keep it that way.
- Story creation writes to the real `story.db` — smoke-test with `DATABASE_URL=sqlite:///./smoke.db` and delete it after.
- Full checks: `cd backend && pytest` and `cd frontend && npx vitest run && npx tsc --noEmit`. Run both before declaring a task done; do not paste hardcoded test counts into docs — they go stale.

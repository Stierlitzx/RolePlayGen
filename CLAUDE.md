# Project: AI interactive story

A local web app. The player picks story parameters (setting, genre, tone and a few others), then an AI narrates the story turn by turn. At the end of each turn the player gets a choice: several options plus a custom input, or a locked choice from fixed options, sometimes only two.

The app runs locally only: no deployment, no accounts, no external database. Every decision should favor simple setup and readable code.

## Before you start

Read, in this order: `docs/FEATURES.md` (what exists — the project's memory), `docs/ARCHITECTURE.md` (how it is built), `docs/SPEC.md` (what we are building), `docs/GOTCHAS.md` (operational traps), and the last twenty lines of `docs/DECISIONS.md` (recent choices). Features have been lost and re-added across sessions — `docs/FEATURES.md` is the guard against that.

## Working rules

- Never remove or weaken a feature listed as `done` in `docs/FEATURES.md` without an explicit instruction from the user and an entry in `docs/DECISIONS.md`.
- When the user asks for a new feature, first add it to `docs/FEATURES.md` as `planned`, then implement it.
- If a request conflicts with an existing feature, ask one short question before acting.
- Decide small details yourself and record non-obvious choices in `docs/DECISIONS.md`.

## Stack

Backend: Python 3.11+, FastAPI, SQLAlchemy 2, SQLite, Pydantic v2, uvicorn. Frontend: Vite, React, TypeScript, plain CSS with no UI library. AI text: Google Gemini REST API, the named cloud providers Groq, OpenRouter and Mistral, or any OpenAI-compatible local endpoint (Ollama, LM Studio) — all via plain `httpx` in `services/llm.py`, switchable per story. Images: local ComfyUI. API keys and model names come from `backend/.env` (gitignored) and must never be hardcoded.

## Repository layout

```
backend/
  app/
    main.py
    config.py
    db.py
    models.py
    schemas.py
    routers/
    services/
      llm.py
      story_engine.py
      image_service.py
    prompts/
  tests/
  requirements.txt
frontend/
  src/
docs/
  SPEC.md
  ARCHITECTURE.md
  FEATURES.md
  DECISIONS.md
  GOTCHAS.md
  BACKLOG.md
  specs/done/
.env.example
README.md
```

## Code rules

Write simple, readable code without unnecessary abstractions. Type everything: annotations in Python, strict mode in TypeScript. One file is responsible for one thing. Do not add libraries outside the stack list without a solid reason and an entry in `docs/DECISIONS.md`.

All work with the AI goes through `services/llm.py` only. Routers know nothing about the SDK. Turn logic (context assembly, response validation, retry on failure) lives in `services/story_engine.py`.

Never trust the model output blindly: parse it, validate it with Pydantic, and on failure retry once with a note describing exactly what was wrong, and only then return an error to the frontend.

Show errors to the user in plain language. Never swallow exceptions silently.

Do not log or commit secrets. `.env` goes in `.gitignore`, `.env.example` stays in the repository.

## Commands

Backend: `cd backend && uvicorn app.main:app --reload --port 8000`. Frontend: `cd frontend && npm run dev`. Tests: `cd backend && pytest` and `cd frontend && npx vitest run && npx tsc --noEmit`. Keep these commands working and up to date in `README.md`.

## Definition of done

A task is finished only when:

- the code runs and its tests pass (`pytest`, `vitest`, `tsc --noEmit`);
- `docs/FEATURES.md` reflects the change (new row, status switch, or updated "where it lives");
- `docs/ARCHITECTURE.md` reflects any API, model or env change;
- `README.md` and `.env.example` reflect any new setting;
- `docs/DECISIONS.md` has an entry for any non-obvious choice.

Do not claim something works until you have run it and checked.

## End of session

Before the final message, verify:

1. Tests pass (backend and frontend).
2. `docs/FEATURES.md` and `docs/ARCHITECTURE.md` match the code you touched.
3. `README.md` / `.env.example` cover any new setting; `docs/DECISIONS.md` logs any non-obvious choice.
4. Print the list of docs you updated in your final message.

## Do not

Do not add authentication, payments, deployment, Docker or a mobile version unless asked. Do not rewrite files unrelated to the current task. Do not change the narrator response format (the "Turn contract" section in `docs/SPEC.md`) without an explicit instruction, because the frontend depends on it.

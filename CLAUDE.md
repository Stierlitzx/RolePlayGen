# Project: AI interactive story

A local web app. The player picks story parameters (setting, genre, tone and a few others), then an AI narrates the story turn by turn. At the end of each turn the player gets a choice: several options plus a custom input, or a locked choice from fixed options, sometimes only two.

The app runs locally only: no deployment, no accounts, no external database. Every decision should favor simple setup and readable code.

## Before you start

Read `docs/SPEC.md` (what we are building), `docs/ARCHITECTURE.md` (how we build it) and `docs/TASKS.md` (the order of work). Go through the tasks in `TASKS.md` one at a time, run the check after each one, and only then move on. If something in the spec is unclear and affects the architecture, ask one short question. Decide small details yourself and record the decision in `docs/DECISIONS.md`.

## Stack

Backend: Python 3.11+, FastAPI, SQLAlchemy 2, SQLite, Pydantic v2, uvicorn. Frontend: Vite, React, TypeScript, plain CSS with no UI library. AI: Anthropic API through the official `anthropic` SDK. The API key and model name come from `.env` and must never be hardcoded.

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
    prompts/
  tests/
  requirements.txt
frontend/
  src/
docs/
.env.example
README.md
```

## Code rules

Write simple, readable code without unnecessary abstractions. Type everything: annotations in Python, strict mode in TypeScript. One file is responsible for one thing. Do not add libraries outside the stack list without a solid reason and an entry in `DECISIONS.md`.

All work with the AI goes through `services/llm.py` only. Routers know nothing about the SDK. Turn logic (context assembly, response validation, retry on failure) lives in `services/story_engine.py`.

Never trust the model output blindly: parse it, validate it with Pydantic, and on failure retry once with a note describing exactly what was wrong, and only then return an error to the frontend.

Show errors to the user in plain language. Never swallow exceptions silently.

Do not log or commit secrets. `.env` goes in `.gitignore`, `.env.example` stays in the repository.

## Commands

Backend: `cd backend && uvicorn app.main:app --reload --port 8000`. Frontend: `cd frontend && npm run dev`. Tests: `cd backend && pytest`. Keep these commands working and up to date in `README.md`.

## Definition of done

A task is done when the code runs, its tests pass, and the behavior matches `SPEC.md`. Do not claim something works until you have run it and checked.

## Do not

Do not add authentication, payments, deployment, Docker or a mobile version unless asked. Do not rewrite files unrelated to the current task. Do not change the narrator response format (the "Turn contract" section in `SPEC.md`) without an explicit instruction, because the frontend depends on it.

# RolePlayGen

A local web app for AI-narrated interactive stories. Configure setting, genre, tone and hero, then play turn by turn. Stories persist in SQLite and can be resumed at any time.

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2, SQLite, Pydantic v2, Google Gemini API (free tier)
- Frontend: Vite, React, TypeScript, plain CSS

## Setup

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy ..\.env.example .env   # then edit .env
```

For development without an API key, keep `MOCK_LLM=true` in `.env`. For real model calls, get a free key at https://aistudio.google.com/api-keys, set `GEMINI_API_KEY` and `MODEL_NAME`, and set `MOCK_LLM=false`.

### Scene illustrations (optional)

Turns can get AI-drawn illustrations from a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) server. Install ComfyUI, put the `waiIllustriousSDXL` checkpoint and the `NOOB_vp1_detailer` LoRA into its model folders, then start it:

```powershell
python main.py   # serves http://127.0.0.1:8188
```

Image settings in `.env`:

| Variable | Meaning |
| --- | --- |
| `IMAGE_GENERATION_ENABLED` | `true` to draw scenes; `false` hides the feature entirely |
| `COMFYUI_URL` | where ComfyUI listens (default `http://127.0.0.1:8188`) |
| `IMAGE_TIMEOUT_SECONDS` | how long one job may take (default 300) |
| `IMAGE_DIR` | where PNGs are saved, served under `/media/` (default `./data/images`) |
| `MOCK_IMAGES` | `true` = skip ComfyUI and write a placeholder PNG after ~3 s, no GPU needed |

Images are generated one at a time in the background and never block the text. If ComfyUI is off, the story works as usual and the image block offers a Retry button.

## Run

```powershell
# Terminal 1 — backend on http://localhost:8000
cd backend
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend on http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

## Tests and build

```powershell
cd backend
.venv\Scripts\pytest

cd frontend
npm test          # component tests (vitest)
npm run build
```

## Features

- Story length: 50 turns (short), 100 turns (medium), unlimited (long), or a custom count (50-500)
- Players pick the AI model per story (Gemini 3.6 Flash / 3.5 Flash / 3.1 Flash-Lite / 3 Flash Preview); the default comes from `.env`
- 21 setting presets plus Custom/Random, up to 3 genres combined from 20, and a freeform "Custom details" field for the plot premise, wanted characters, factions and starting conflict
- The first turn either drops the player straight into a scene (default) or opens with an explanatory intro of the world and the hero — controlled by the "Explain the world and the hero" checkbox at setup
- Story language (Russian / English / Kazakh) is independent from the setting culture (Slavic, Western European, East Asian, …): narration follows the language, names and cultural flavor follow the culture. An optional naming-culture override pins character names to a specific culture
- A Characters tab on the story screen tracks every named NPC (plus the hero, pinned first) with portrait, role, relationship to the player and description; portraits are drawn by ComfyUI when a character first appears, in the same one-job-at-a-time queue as scene illustrations
- Character looks stay consistent across images: the narrator defines `appearance_tags` once per character and the backend splices them into every image prompt where the character is present
- While a story has only its opening turn, you can edit the setup ("Change beginning") or reroll the prologue ("Regenerate opening")
- Binary (two-option) choices appear only at story-defining moments, not on a schedule
- Stories play fully in Russian, English or Kazakh — mock mode included
- Optional scene illustrations via a local ComfyUI server: generated one at a time in the background, never blocking the text; `MOCK_IMAGES=true` develops the flow without a GPU

## 2026-09-21 addendum (see DECISIONS.md)

- The image worker is a single daemon thread with a `queue.Queue` instead of an asyncio task: the ComfyUI polling loop uses the synchronous `httpx.Client` already in the project, and the thread is trivially testable without an event loop.
- Frontend component tests run on vitest + Testing Library (dev-only dependencies), added for the `ImageBlock` state checks.

## Notes

- `.env` is git-ignored; `.env.example` documents all settings.
- The narrator prompt and turn template live in `backend/app/prompts/` and can be replaced without code changes. They instruct the model to write 350-700 word turns with dialogue and consistent character personalities.
- The mock AI honors the chosen language and turn limit, and ends the story exactly at the limit.

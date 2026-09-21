# Architecture

## Overview

The React frontend talks to the backend over HTTP with JSON. The backend stores data in SQLite and calls the Anthropic API. In development the frontend runs on Vite (port 5173) and proxies `/api` to the backend (port 8000).

## Data models

Story: `id`, `title`, `settings` (JSON with the chosen parameters), `status` (`active` or `finished`), `max_turns` (nullable), `created_at`, `updated_at`.

Turn: `id`, `story_id`, `index` (zero based), `player_input_type` (`option`, `custom` or `start`), `player_input_text`, `narration`, `choice` (JSON, nullable at the ending), `state` (JSON), `is_ending`, `image_status` (`none`, `queued`, `generating`, `done`, `failed`; default `none`), `image_format` (`portrait` or `wide`, nullable), `image_prompt` (nullable), `image_path` (nullable, relative to `IMAGE_DIR`), `image_error` (nullable), `created_at`.

The first turn is created automatically when the story is created and has type `start`. The image columns were added to existing databases with a small startup migration (`ALTER TABLE` for any missing column), so old stories keep working.

Character: `id`, `story_id`, `name`, `is_hero`, `role`, `relationship` (to the player character), `description`, `appearance_tags`, `first_seen_turn_id`, `portrait_status` (same states as `image_status`; default `none`), `portrait_path`, `portrait_error`, `created_at`. One row per story and name; the hero is stored as a character row with `is_hero=true`. The table is created by the same startup migration mechanism, so existing databases upgrade in place.

## API

`GET /api/setup-options` returns the lists of settings, genres, tones, lengths, languages and cultures, plus `max_genres` — the single source of truth for the setup screen, so lists are extended on the backend only.

`GET /api/stories` returns the list of stories.

`POST /api/stories` accepts the setup parameters, creates the story, generates the first turn and returns the whole story.

`GET /api/stories/{id}` returns the story with all turns.

`POST /api/stories/{id}/turns` accepts `option_id` or `custom_text` (exactly one of them), generates the next turn and returns it.

`DELETE /api/stories/{id}` deletes the story together with its turns.

`GET /api/turns/{turn_id}/image` returns `{status, format, url, error}` for the turn's illustration; `url` (under `/media/`) is set only when the status is `done`.

`POST /api/turns/{turn_id}/image/retry` re-enqueues a `failed` illustration and returns the new status; any other status is rejected with 400.

`GET /api/stories/{story_id}/characters` returns the story's characters (hero first, then by appearance) with `{name, is_hero, role, relationship, description, first_seen_turn_id, portrait_status, portrait_url, portrait_error}`; `portrait_url` is set only when `portrait_status` is `done`. `first_seen_turn_id` links a character to the turn that introduced them, so the frontend can also show their portrait inline in the turn feed at their first appearance.

`GET /api/characters/{character_id}` returns the same shape for one character.

`POST /api/characters/{character_id}/portrait/retry` re-enqueues a `failed` portrait; any other status is rejected with 400.

Turn and story responses include `image_status`, `image_format`, `image_url` and `image_error` for every turn, so a reloaded page shows saved pictures immediately. Image files are served statically from `IMAGE_DIR` under `/media/`.

Error codes: 400 for invalid input, 404 for a missing story, 409 if the story is already finished, 502 if the AI did not return a valid response after the retry, 503 if the key is not configured.

## Image generation flow

When a turn with a non-empty `image_prompt` is saved (and `IMAGE_GENERATION_ENABLED=true`), the turn is marked `queued` and its id goes into a single in-process queue. One worker thread, started at app startup, takes jobs one at a time (never two jobs on the GPU in parallel), marks the turn `generating`, and asks the local ComfyUI server: it fills the workflow JSON from `backend/comfy_workflows/{format}.json` (positive prompt into node `6`, a shared random seed into samplers `3` and `13`, `story_{story_id}_{turn_id}` as `filename_prefix` in node `9`, everything else untouched), posts it to `/prompt`, polls `/history/{prompt_id}` every 1.5 s up to `IMAGE_TIMEOUT_SECONDS`, downloads the result via `/view` and saves it to `IMAGE_DIR/{story_id}/{turn_id}.png`. The turn ends `done` with `image_path`, or `failed` with a readable `image_error` — errors never propagate into the text flow. On startup, turns stuck in `queued`/`generating` are reset to `failed` with "Interrupted" (the same cleanup covers `Character.portrait_status`). With `MOCK_IMAGES=true` the worker skips ComfyUI, waits ~3 s and writes a placeholder PNG, so the whole flow works without a GPU.

Portraits are jobs in the same queue (one job at a time across scenes and portraits combined), always rendered with the `portrait.json` workflow and saved to `IMAGE_DIR/{story_id}/char_{character_id}.png`. Before a scene job is submitted, the backend prepends the stored `appearance_tags` of every character in the turn's `characters_in_scene` (hero first, then in list order) to the sanitized narrator `image_prompt` — appearance consistency is deterministic string assembly, not a prompt instruction the model might ignore.

## How a turn is built

The `story_engine` service assembles the context for the model: the story parameters, the accumulated `state.facts` from all turns without duplicates, the short `state.summary` of older turns, the full text of the last three turns, the player choice, the turn number and `max_turns`, so the model knows where it is in the story. The context goes to `llm.py`, which calls the model and returns raw text. Then `story_engine` parses the JSON, validates it against the schema, checks the choice mode rules and stores the turn. On a parse or validation error it retries once, adding a description of the error to the request.

Player input is also checked in `story_engine`: `option_id` must exist in the last turn, `custom_text` is allowed only when `allow_custom` is `true`, and the text length is at most 500 characters.

## Prompts

Prompt files live in `backend/prompts/` as text files and are read at startup. The minimum set for the first version is the narrator system prompt (role, rules, turn contract) and a turn message template. Write a short working version to begin with. More detailed narrator instructions will be added separately, so structure it so the prompt can be replaced by files without code changes.

## Configuration

Through `.env`: `GEMINI_API_KEY`, `MODEL_NAME`, `DATABASE_URL` (default `sqlite:///./story.db`), `MAX_TOKENS` (default 4000), `MOCK_LLM`. Images: `IMAGE_GENERATION_ENABLED`, `COMFYUI_URL` (default `http://127.0.0.1:8188`), `IMAGE_TIMEOUT_SECONDS` (default 300), `IMAGE_DIR` (default `./data/images`), `MOCK_IMAGES`. Read in `config.py` with Pydantic Settings.

## Frontend

Story state is kept in one hook or context. Pages: `HomePage`, `SetupPage`, `StoryPage`. Components: `TurnView`, `ImageBlock` (four states: loading placeholder with reserved aspect ratio, done with fade-in, failed with Retry, none), `CharactersPanel` (card grid plus a detail view; polls only while a portrait is in progress), `ChoicePanel` (three display variants inside, one per mode), `LoadingIndicator`, `ErrorBanner`. `StoryPage` switches between the turn feed and `CharactersPanel` with a tab bar. API access is in a single `api.ts` module with types that match the backend schemas. The Vite dev server proxies both `/api` and `/media` to the backend.

The turn feed scrolls automatically to the latest turn. The active choice is disabled while a request is in flight, so a turn cannot be submitted twice.

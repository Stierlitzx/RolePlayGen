# Architecture

## Overview

The React frontend talks to the backend over HTTP with JSON. The backend stores data in SQLite and calls the Google Gemini API (see DECISIONS.md). In development the frontend runs on Vite (port 5173) and proxies `/api` to the backend (port 8000).

## Data models

Story: `id`, `title`, `settings` (JSON with the chosen parameters — including `age_rating`, `explicit_sexual`, `graphic_violence`, `image_style` and `narrator_style`, all absent for stories created before those fields existed, which preserves their old behavior), `status` (`active` or `finished`), `max_turns` (nullable), `created_at`, `updated_at`.

Turn: `id`, `story_id`, `index` (zero based), `player_input_type` (`option`, `custom` or `start`), `player_input_text`, `narration`, `choice` (JSON, nullable at the ending), `state` (JSON), `is_ending`, `image_status` (`none`, `queued`, `generating`, `done`, `failed`; default `none`), `image_format` (`portrait` or `wide`, nullable), `image_prompt` (nullable), `image_path` (nullable, relative to `IMAGE_DIR`), `image_error` (nullable), `created_at`.

The first turn is created automatically when the story is created and has type `start`. The image columns were added to existing databases with a small startup migration (`ALTER TABLE` for any missing column), so old stories keep working.

Character: `id`, `story_id`, `name`, `is_hero`, `role`, `relationship` (to the player character), `description`, `appearance_tags`, `portrait_history` (JSON list of look versions `{appearance_tags, pose, expression, portrait_path, turn_id}`; the latest entry is the current look), `first_seen_turn_id`, `portrait_status` (same states as `image_status`; default `none`), `portrait_path`, `portrait_error`, `created_at`. One row per story and name; the hero is stored as a character row with `is_hero=true`. The table is created by the same startup migration mechanism, so existing databases upgrade in place, and rows without `portrait_history` are treated as single-version characters.

## API

`GET /api/setup-options` returns the lists of settings, genres, tones, lengths, languages and cultures, plus `age_ratings` (with `default_age_rating`), `adult_genres`, `image_styles` (with `default_image_style`), `narrator_styles` (with `default_narrator_style`), `max_genres` (5) and the model list — the single source of truth for the setup screen, so lists are extended on the backend only. The image-style tag mappings live in backend config next to the option lists.

`GET /api/stories` returns the list of stories.

`POST /api/stories` accepts the setup parameters, creates the story, generates the first turn and returns the whole story.

`GET /api/stories/{id}` returns the story with all turns.

`PATCH /api/stories/{id}` updates the story's settings (used to change the narrator style mid-story; also backs the "Change beginning" flow while a story has only its opening turn). The same validation as creation applies (18+ flags and adult genres below 18+ are rejected with 422).

`POST /api/stories/{id}/turns` accepts `option_id` or `custom_text` (exactly one of them), generates the next turn and returns it.

`DELETE /api/stories/{id}` deletes the story together with its turns, then recursively deletes the story's image folder `IMAGE_DIR/{story_id}/` (scene illustrations and `char_*.png` portraits). The target path is resolved and verified to stay inside `IMAGE_DIR` before deleting; filesystem failures are logged, never fatal — a missing or locked folder still yields a 204.

`GET /api/turns/{turn_id}/image` returns `{status, format, url, error}` for the turn's illustration; `url` (under `/media/`) is set only when the status is `done`.

`POST /api/turns/{turn_id}/image/retry` re-enqueues a `failed` illustration and returns the new status; any other status is rejected with 400.

`GET /api/stories/{story_id}/characters` returns the story's characters (hero first, then by appearance) with `{name, is_hero, role, relationship, description, first_seen_turn_id, portrait_status, portrait_url, portrait_error}`; `portrait_url` is set only when `portrait_status` is `done`. `first_seen_turn_id` links a character to the turn that introduced them, so the frontend can also show their portrait inline in the turn feed at their first appearance.

`GET /api/characters/{character_id}` returns the same shape for one character.

`POST /api/characters/{character_id}/portrait/retry` re-enqueues a `failed` portrait; any other status is rejected with 400.

Turn and story responses include `image_status`, `image_format`, `image_url` and `image_error` for every turn, so a reloaded page shows saved pictures immediately. Image files are served statically from `IMAGE_DIR` under `/media/`.

Error codes: 400 for invalid input, 404 for a missing story, 409 if the story is already finished, 422 for schema/setting validation failures (including 18+ flags or adult genres below an 18+ rating), 502 if the AI did not return a valid response after the retry, 503 if the key is not configured.

## Image generation flow

When a turn with a non-empty `image_prompt` is saved (and `IMAGE_GENERATION_ENABLED=true`), the turn is marked `queued` and its id goes into a single in-process queue. One worker thread, started at app startup, takes jobs one at a time (never two jobs on the GPU in parallel), marks the turn `generating`, and asks the local ComfyUI server: it fills the workflow JSON from `backend/comfy_workflows/{format}.json` (positive prompt into node `6`, a shared random seed into samplers `3` and `13`, `story_{story_id}_{turn_id}` as `filename_prefix` in node `9`, everything else untouched), posts it to `/prompt`, polls `/history/{prompt_id}` every 1.5 s up to `IMAGE_TIMEOUT_SECONDS` (on timeout the stale job is cancelled server-side — deleted from the ComfyUI queue, `/interrupt` only if it is the currently running one — so it cannot block later jobs), downloads the result via `/view` and saves it to `IMAGE_DIR/{story_id}/{turn_id}.png`. The turn ends `done` with `image_path`, or `failed` with a readable `image_error` — errors never propagate into the text flow. With `IMAGE_REFERENCE_MODE=img2img`, the current portraits of the scene's characters are uploaded to ComfyUI and the first one is wired into the first sampler through an auto-injected LoadImage → ImageScale (to the scene resolution) → VAEEncode chain with lowered denoise, so likeness comes from the actual portrait picture, not only from prompt tags; turns without a finished portrait generate unchanged. On startup, turns stuck in `queued`/`generating` are reset to `failed` with "Interrupted" (the same cleanup covers `Character.portrait_status`). With `MOCK_IMAGES=true` the worker skips ComfyUI, waits ~3 s and writes a placeholder PNG, so the whole flow works without a GPU.

Prompt assembly (`assemble_positive_prompt` / `assemble_portrait_prompt` in `image_service.py`) is deterministic string building owned by the backend: the quality prefix is `masterpiece, best quality, amazing quality, ` plus a rating token — `general` by default, `explicit` only for 18+ stories with `explicit_sexual` on (which also stops stripping `questionable`/`explicit` from the narrator tags; quality words are always stripped). After the prefix come the story's image-style positive tags (empty when the story predates `image_style`), and `build_workflow` additionally appends the style's negative tags to the existing negative prompt of node `7` — append, comma-separated, never replace. The `adult` tag is enforced whenever a person tag appears, at every rating.

Portraits are jobs in the same queue (one job at a time across scenes and portraits combined), always rendered with the `portrait.json` workflow and saved to `IMAGE_DIR/{story_id}/char_{character_id}.png`. The portrait prompt is quality prefix + style tags + the character's stored `appearance_tags` + this portrait's `pose`/`expression` (narrator-supplied per portrait, never part of the fixed appearance tags) + the full-body framing suffix (`full body, standing, looking at viewer, simple background`). Before a scene job is submitted, the backend prepends the stored `appearance_tags` of every character in the turn's `characters_in_scene` (hero first, then in list order) to the sanitized narrator `image_prompt` — appearance consistency is deterministic string assembly, not a prompt instruction the model might ignore.

Portrait evolution uses the character's `portrait_history`: a narrator `portrait_update` appends a new version, switches `appearance_tags` (scene splicing follows the new look immediately) and enqueues exactly one portrait job; `portrait_revert` makes the previous version current and points `portrait_path` at its existing file with no GPU job at all (a revert with no previous entry is ignored and logged). `portrait_status`/`portrait_error` always describe the current version.

## How a turn is built

The `story_engine` service assembles the context for the model: the narrator system prompt followed by the story's narrator-style fragment and AGE RATING section (both appended only when the corresponding settings exist — stories without them get the byte-identical old prompt), the story parameters, the accumulated `state.facts` from all turns without duplicates, the short `state.summary` of older turns, the full text of the last three turns, the player choice, the turn number and `max_turns`, so the model knows where it is in the story. The context goes to `llm.py`, which calls the model and returns raw text. Then `story_engine` parses the JSON, validates it against the schema, checks the choice mode rules and stores the turn. On a parse or validation error it retries once, adding a description of the error to the request.

Player input is also checked in `story_engine`: `option_id` must exist in the last turn, `custom_text` is allowed only when `allow_custom` is `true`, and the text length is at most 500 characters.

## Prompts

Prompt files live in `backend/prompts/` as text files and are read at startup. The minimum set for the first version is the narrator system prompt (role, rules, turn contract) and a turn message template. Write a short working version to begin with. More detailed narrator instructions will be added separately, so structure it so the prompt can be replaced by files without code changes.

## Configuration

Through `.env`: `GEMINI_API_KEY`, `MODEL_NAME`, `DATABASE_URL` (default `sqlite:///./story.db`), `MAX_TOKENS` (default 4000), `MOCK_LLM`. Images: `IMAGE_GENERATION_ENABLED`, `COMFYUI_URL` (default `http://127.0.0.1:8188`), `IMAGE_TIMEOUT_SECONDS` (default 300), `IMAGE_DIR` (default `./data/images`), `MOCK_IMAGES`. Read in `config.py` with Pydantic Settings.

## Frontend

Story state is kept in one hook or context. Pages: `HomePage`, `SetupPage`, `StoryPage`. Components: `TurnView`, `ImageBlock` (four states: loading placeholder with reserved aspect ratio, done with fade-in, failed with Retry, none), `IntroducedCharacters` (inline portraits under a turn's illustration for characters first seen on that turn), `CharactersPanel` (card grid plus a detail view; polls only while a portrait is in progress), `Lightbox` (shared fullscreen overlay for every image — click to zoom between fit and actual size, closes on `Esc`, backdrop click or ✕, locks body scroll, `role="dialog"`), `ChoicePanel` (three display variants inside, one per mode), `LoadingIndicator`, `ErrorBanner`. `StoryPage` switches between the turn feed and `CharactersPanel` with a tab bar and offers a narrator-style dropdown in its header that PATCHes the story settings. API access is in a single `api.ts` module with types that match the backend schemas. The Vite dev server proxies both `/api` and `/media` to the backend.

The turn feed scrolls automatically to the latest turn. The active choice is disabled while a request is in flight, so a turn cannot be submitted twice.

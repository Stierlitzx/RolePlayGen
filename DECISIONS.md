# Decisions

## 2026-09-20: Gemini instead of Anthropic

The AI provider was switched from Anthropic Claude to Google Gemini (user request — free tier).

- `services/llm.py` calls the Gemini REST API (`generateContent`) via `httpx` (already a dependency), so no new library was added.
- Config: `GEMINI_API_KEY` + `MODEL_NAME` (default `gemini-2.5-flash`) in `.env`.
- Model picker serves Gemini models verified against the live API: `gemini-3.6-flash` (default), `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`. Note: `gemini-2.5-flash` is no longer available to new API keys.
- `generationConfig.responseMimeType = "application/json"` is used so Gemini returns raw JSON matching the turn contract.

## 2026-09-21: Scene illustrations via local ComfyUI

- `services/image_service.py` uses a single daemon worker thread with a `queue.Queue` (one GPU job at a time) and the synchronous `httpx.Client` already used by `llm.py`, instead of an asyncio task — simpler to test and no new dependency.
- New `Turn` columns (`image_status`, `image_format`, `image_prompt`, `image_path`, `image_error`) are added to existing SQLite files by a small idempotent `ALTER TABLE` check at startup, since the project has no migration tool.
- The narrator emits `image_prompt`/`image_format` in the turn JSON; the backend owns prompt assembly (quality prefix `general`, banned-token stripping, `adult` enforcement) so the rating is never the model's choice.
- `MOCK_IMAGES=true` writes a 1x1 placeholder PNG generated with `struct`/`zlib` (stdlib only) after ~3 s, so no image library was added.
- Frontend tests: vitest + @testing-library/react + @testing-library/jest-dom + jsdom (dev-only) were added to check the four `ImageBlock` states; `npm test` runs them.

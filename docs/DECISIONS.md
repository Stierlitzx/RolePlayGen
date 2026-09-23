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

## 2026-09-22: Pluggable text provider (local uncensored models)

- `LLM_PROVIDER=gemini|openai` in `.env`. `openai` talks to any OpenAI-compatible chat endpoint (Ollama, LM Studio, llama.cpp) via `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` — no new dependency, still plain `httpx.post` to `/chat/completions` with `response_format={"type": "json_object"}` as the JSON-contract counterpart of Gemini's `responseMimeType`.
- Motivation: Gemini's safety filters apply on top of the story's age rating even at `BLOCK_ONLY_HIGH`; a local uncensored fine-tune (Dolphin, Hermes, abliterated builds) has no cloud-side filter, so the app's own rating system is the only gate.
- `setup-options` becomes provider-aware: with `openai` it serves exactly the configured local model and treats `OPENAI_BASE_URL` as the "AI configured" signal; the missing-key 503 check in `create_story` only applies to the Gemini provider.
- Gemini remains the default — a local 7-12B model is weaker prose (especially in Russian), and the README says so.

## 2026-09-22: Gemini safety blocks surfaced clearly

- Requests now send `safetySettings` with `BLOCK_ONLY_HIGH` for the four harm categories. Fiction (dark themes, violence, romance — especially 18+ stories) constantly tripped Gemini's default medium threshold; the app's own age-rating system governs content, so the API threshold only guards Gemini's hard limits.
- A safety block used to reach the player as "The AI service returned an unexpected response shape." `_call_gemini` now reads `promptFeedback.blockReason` and `candidates[].finishReason`/`safetyRatings` and raises a message that names the cause ("refused the prompt", "blocked this turn as unsafe (sexually explicit)", token limit, recitation) with a hint about what to change. The generic message stays as a last resort.

## 2026-09-22: Cancel stale ComfyUI jobs on timeout

- Found by a live handoff test (Ollama qwen3-8b resident on the same 8 GB GPU as ComfyUI): image jobs exceeded `IMAGE_TIMEOUT_SECONDS` and were marked `failed`, but ComfyUI kept running them; later jobs queued behind the stale backlog and timed out too � the pipeline never recovered on its own. `wait_for_result` now calls `cancel_job` on timeout: delete the prompt from the ComfyUI queue, and `/interrupt` only when it is the currently running job. Best-effort, never raises.

## 2026-09-22: New workflows + portrait-driven scenes

- Replaced `comfy_workflows/wide.json` and `portrait.json` with the user's detailer workflows (waiIllustriousSDXL v170 + NOOB detailer, facial-expression and Expressive_H LoRAs, stronger negative prompt; wide upscales latents 1.5x then ImageScale to 1920x1080). Node-map convention unchanged (6/7 prompts, 3/13 samplers, 9 save).
- `IMAGE_REFERENCE_MODE=img2img` now needs no hand-added workflow nodes: the backend injects LoadImage->ImageScale->VAEEncode (ids 90/91/92) and rewires the first sampler's latent only when a reference portrait is actually applied, so plain txt2img runs are untouched. Likeness comes from the portrait picture, not only appearance tags.
- The new workflow negative dropped `nsfw`; `negative_extra_for` re-appends it for every story that is not explicit 18+, so the age rating keeps governing images regardless of the workflow file.

## 2026-09-22: Per-story provider choice; portraits never explicit

- `setup-options` now serves both text providers side by side (`default_provider`, `gemini_models`, `default_gemini_model`, `gemini_configured`, `local_model`, `local_configured`) and the setup form gained a "Text model source" picker: Gemini (cloud) vs the configured local model. The choice is stored in the story's settings as `llm_provider` (`"gemini"`/`"local"`); `call_model` takes a `provider` override, and stories without the field follow the server-wide `LLM_PROVIDER`, so old stories are unchanged. The 503 missing-config check in `create_story` applies to the provider the story will actually use. The legacy `models`/`default_model`/`ai_configured` fields still follow `LLM_PROVIDER` for older clients.
- Bug fix: portraits of 18+ explicit stories were generated with the `explicit` rating token and without the `nsfw` negative, so characters turned up naked from their first appearance. A portrait is the character's reference card, not a scene: portraits are now clothed and general-rated **by default** at every rating (`PORTRAIT_BANNED_TOKENS` strips nudity tags). Explicit portraits are still possible, but only when both gates open: the story is 18+ with explicit content on AND the narrator deliberately tagged that look as nude (`portrait_wants_nudity` — the text model's only channel to say "this character is actually naked in the story now", typically a plot-driven `portrait_update`). The narrator prompt states the rule: appearance tags describe the character dressed; the first portrait is normally clothed.
- The character detail endpoint now serves `portrait_history` as a gallery (`PortraitVersionRead`: `portrait_url`, `turn_id`, `current` — mapped from the raw JSON entries in a `CharacterRead` before-validator); the Characters tab detail view renders it as a "Past looks" grid with the shared lightbox, hidden when there is only one look.

## 2026-09-22: Hero gender, faithful hero look, heal-first image retry

- New setup field `hero_gender` (Unspecified/Female/Male, `HERO_GENDER_OPTIONS` + `GENDER_TAGS` in `setup_options.py`), served via setup-options, stored per story, shown in the turn prompt (`Hero gender:`) and mapped to the `1girl`/`1boy` image tags. The narrator system prompt now orders the hero's `appearance_tags` to mirror the player's hero description exactly — the mock narrator also converts the freeform description into tags (one per sentence) instead of the hardcoded "1girl, traveler, cloak" look that ignored the player's description entirely. Mock scene prompts no longer carry a hardcoded look either (appearance comes from the stored hero tags the backend splices in).
- Camera-shot prompt rule tightened: with a named character in frame the default is medium/cowboy shot and the character must fill at least half the image height; wide shots are scenery-only. Tiny characters in wide shots rendered unrecognizable and inconsistent with portraits.
- `retry_turn_image` / `retry_character_portrait` and the startup `reset_interrupted_turns` cleanup now heal to `done` when the image file already exists on disk (`_image_file_exists`) — a stale timeout or a restart after the download no longer wastes GPU time on an identical regeneration.

## 2026-09-22: Mock opening fixed and deepened


- The mock narrator interpolated the raw English preset key into Russian/Kazakh prose ("…Wizard school хранил свои легенды…") in the intro, per-turn narration, state summary and facts. `_SETTING_DISPLAY` now maps every preset to a localized display name (custom freeform settings pass through), `_narration` no longer embeds the setting at all (ungrammatical case government), and `_state` uses the localized name.
- The mock prologue grew from two clipped sentences to a three-paragraph open-ended opening, and the real-model `intro_hint` now asks for "a full introductory prologue of several paragraphs" that stays open-ended instead of a "short" one.

## 2026-09-23: Mock off, real narrator on; narrator prompt overhaul

Root cause of "every story is the same": the app ran with `MOCK_LLM=true` — one scripted opening, one stranger NPC, one companion ("Стражник Галка"). `.env` now: `MOCK_LLM=false`, `LLM_PROVIDER=gemini`, `MODEL_NAME=gemini-3.6-flash`, a real `GEMINI_API_KEY` (gitignored — never copy it into any file), `IMAGE_REFERENCE_MODE=img2img` (portraits fed into scenes for likeness). Local Ollama `huihui_ai/qwen3-abliterated:8b` stays available per story via the provider picker.

- `narrator_system.txt`: the "mysterious stranger who knows your name and leads you downstairs" opening is BANNED; prologues must contain concrete lore (places, powers, debts); openings may be solo; character designs must vary (max one facial scar per story); NPCs must talk to each other, not only to the player; turn length varies 250-800 words by scene weight instead of a fixed 350-700.
- `turn_message.txt`: final instruction defers length to the system rules and adds a FORMAT REMINDER — narration in the story language, but `image_prompt`/`appearance_tags`/`pose`/`expression` strictly English danbooru tags, `image_format` strictly "portrait"/"wide". (Live-tested: small local models otherwise emit Russian tags and `image_format: "medium"`.)
- Mock narrator rewritten (still used by tests and `MOCK_LLM=true` dev): seeded rotation — 3 intros, 3 scenes (stranger / solo road / public conflict with NPC-NPC dialogue), 3 companions per language, every 4th story opens solo. Seed = `story.id - 1` (first story keeps the classic opening; tests rely on it). Mock hero tags append `fully clothed` as an overridable default (see the clothing-guard entry).
- Bug: `image_format` was a strict `Literal["portrait","wide"]` — a small narrator writing "medium" killed the turn with 502 even though SPEC promised a fallback. Now plain `str`, engine normalizes unknown values to "wide" (SPEC text updated).
- Bug: missing/empty `image_prompt` left the turn without an illustration. Now falls back to `solo, standing, detailed background, wide shot` so every turn is illustrated when image generation is on (SPEC updated).
- Bug: `_find_character` used SQLite `func.lower()` — ASCII-only, so Cyrillic names never matched case-insensitively and the hero got duplicated as an NPC when the narrator listed them in `characters` (small models do). Now Python-side `casefold` compare + hero-named reports are skipped.

## 2026-09-23: Clothing guard is an overridable default, not a ban

- The mock hero's `fully clothed` exists only to stop accidental nudity when the description is unreadable to the image model. Plot-justified nudity still works: `portrait_update` replaces tags wholesale, and `assemble_positive_prompt` strips clothing-guard tokens (`fully clothed`, `clothed`, `fully dressed`) from spliced appearance tags when the story is 18+ explicit AND the narrator tagged the scene nude (`PORTRAIT_BANNED_TOKENS` reused as the nudity detector). Scene intent beats the default.

## 2026-09-23: Gemini PROHIBITED_CONTENT — hard filter, honest error

- `promptFeedback.blockReason: PROHIBITED_CONTENT` is a pre-generation hard block that NO setting (safety thresholds, age rating, paid tier) lifts. The usual trigger is explicit wording in the setup fields (custom details / hero description). Error messages for prompt blocks and SAFETY finishes now say this plainly and point to the per-story local-model picker (the uncensored path). Advice: keep explicit content out of the setup text; let it emerge in-story, or run that story on the local model.
- Cloud uncensored option researched for the user: OpenRouter free tier + `cognitivecomputations/dolphin-mistral-24b-venice-edition:free` (33K ctx, ~50 req/day free) via `OPENAI_BASE_URL=https://openrouter.ai/api/v1`. Works with the existing `openai` provider, no code change.

## 2026-09-23: Redo last turn

- New `POST /api/stories/{id}/regenerate-last` (`story_engine.regenerate_last_turn`): deletes the last turn and replays its stored player input, so any bad turn — including a finished story's ending — can be regenerated. Characters introduced on the deleted turn are removed, portrait updates from it are rolled back, and its image file is deleted best-effort. Single-turn stories delegate to `regenerate_start`. Frontend: "Redo last turn" button in the story header (shown whenever the opening-regenerate buttons are not).
- Latent bug found while testing: `db.delete()` leaves the object in the loaded relationship collection until expiry, so `regenerate_start` numbered the replacement opening turn 2 instead of 1. Both regenerate paths now also remove the row from the in-memory collection before generating; the old test was strengthened to assert `index == 0`.

## 2026-09-23: Portrait polling survives backend restarts; img2img denoise 0.75

- Symptom: a portrait stayed on "Drawing…" forever although its file and DB status were `done`. Cause: the character polling loops (StoryPage feed, CharactersPanel) never rescheduled after a failed request — one backend restart mid-session killed the loop. Both loops now retry every 5 s after a failure (ImageBlock already did). A page reload also heals it.
- Symptom: a portrait-referenced scene looked like a second, identical portrait. Cause: img2img reference at denoise 0.55 keeps the portrait's whole composition. `IMAGE_REFERENCE_DENOISE` default raised to 0.75 — likeness (face/outfit) stays, the scene prompt owns the composition. Tests pin their own denoise (0.6) instead of inheriting the developer's `.env`.

## 2026-09-23: VRAM conductor for Ollama + ComfyUI on one GPU

- Symptom: a turn written by the local model (Ollama, ~5 GB resident) left no VRAM for ComfyUI, so illustrations failed or stalled on an 8 GB card. New opt-in `GPU_VRAM_CONDUCTOR=true` (config `gpu_vram_conductor`, enabled in the user's `.env` since their Ollama and ComfyUI share one GPU): before every real image job the worker asks the text server to unload the model (`POST {OPENAI_BASE_URL minus /v1}/api/generate` with `keep_alive: 0`), and after the job (success or failure) asks ComfyUI to free its cache (`POST /free` with `unload_models + free_memory`). Both are best-effort with 10 s timeouts — a down or non-Ollama server is logged and ignored, the job proceeds. Skipped entirely for `MOCK_IMAGES=true`. Cost: the text model reloads on the next turn (~10-30 s). Known limitation: a text request landing DURING an image job still reloads Ollama alongside ComfyUI — no hard mutex, by design (keeps text responsive; ComfyUI's smart memory usually absorbs the overlap).
- Also this session: `Redo last turn` feature (`regenerate-last`), and `regenerate_start`'s off-by-one turn index fix (deleted rows must leave the in-memory collection before regenerating).

## Operational gotchas (read before touching anything)

- **`uvicorn --reload` watches only `.py` files — after editing `.env` the backend MUST be restarted manually.** "Gemini is not configured" with a key in `.env` = stale process. Also the project lives in OneDrive, where WatchFiles reloads are unreliable — restart after code changes too (the last server runs WITHOUT `--reload` for this reason).
- Run the backend from `backend/` (`Settings` reads `.env` relative to CWD): `cd backend && .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`.
- `backend/.env` is gitignored; `backend/tests/conftest.py` pins `OPENAI_MODEL`/`LLM_PROVIDER`/`MOCK_LLM` so tests never inherit the developer's `.env` — keep it that way.
- Story creation writes to the real `story.db` — smoke-test with `DATABASE_URL=sqlite:///./smoke.db` and delete it after.
- Full checks: `cd backend && pytest` (123 tests) and `cd frontend && npx vitest run && npx tsc --noEmit` (22 tests).

## Feature registry — do NOT silently drop in future sessions

Per-story text-provider picker (gemini/local, stored as `settings.llm_provider`) · per-story Gemini model picker · age rating + 18+ sub-options (`explicit_sexual`, `graphic_violence`) · image style picker · narrator style picker · `intro_exposition` (lore prologue vs in-medias-res) · hero gender + freeform hero appearance mirrored into `appearance_tags` · character tracking with portrait history (update/revert) · `characters_in_scene` tag splicing · img2img portrait reference mode (`IMAGE_REFERENCE_MODE`) · heal-first image retry · ComfyUI stale-job cancellation · mock narrator rotation · clothing guard · image fallbacks (format + prompt) · redo last turn (`regenerate-last`) · VRAM conductor (`GPU_VRAM_CONDUCTOR`). Removing any of these is a regression — several were re-added after being lost in earlier sessions.

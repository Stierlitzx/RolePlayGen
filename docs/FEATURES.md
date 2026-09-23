# Feature registry

One row per feature. This file is the memory of the project across sessions.

## Rules

1. A row marked `done` must not be removed, disabled or changed in behavior without an entry in `DECISIONS.md` that explains why and a matching edit of the row.
2. To rename or move code, update the "where it lives" column in the same change.
3. Every new feature gets a row before the code is written, with status `planned`, and is switched to `done` when tests pass.
4. If a feature is dropped on purpose, change its status to `rejected` and keep the row with the reason. Never just delete it.

## Text providers and models

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Gemini text provider | done | `services/llm.py` (`call_model`, `_call_gemini`, `GEMINI_API_BASE`), env `GEMINI_API_KEY`, `MODEL_NAME` | `test_llm.py` | `responseMimeType=application/json` enforces the turn contract |
| Gemini model fallback chain | done | `llm.py` `MODEL_FALLBACK_ORDER` | `test_llm.py` | 503/429 retries the next model |
| Gemini safety settings `BLOCK_ONLY_HIGH` | done | `llm.py` `SAFETY_SETTINGS` | `test_llm.py` | The app's age rating governs content; the API threshold only guards hard limits |
| Clear safety-block error messages | done | `llm.py` `_finish_reason_message`, `promptFeedback.blockReason` handling | `test_llm.py` | Names the cause (refusal, SAFETY category, MAX_TOKENS, RECITATION, PROHIBITED_CONTENT) |
| OpenAI-compatible provider (Ollama, LM Studio, llama.cpp, OpenRouter…) | done | `llm.py` (`_call_openai`), env `LLM_PROVIDER`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` | `test_llm.py` | `response_format={"type": "json_object"}`; no new dependency |
| Per-story provider picker (Gemini vs local) | done | story settings `llm_provider`; `story_engine._provider_for_story`/`_effective_provider`; setup-options fields `default_provider`, `gemini_models`, `local_model`…; `SetupPage` | `test_api.py`, `test_story_engine.py` | Stories without the field follow `LLM_PROVIDER`; the 503 check applies to the story's actual provider |
| Per-story Gemini model picker | done | `setup_options.MODEL_OPTIONS`, story settings `model`, setup-options `gemini_models`/`default_gemini_model` | `test_api.py`, `test_setup_options.py` | Legacy `models`/`default_model`/`ai_configured` fields still follow `LLM_PROVIDER` |
| Faithful hero tag conversion (dedicated LLM call) | done | `llm.py` `faithful_appearance_tags` | `test_llm.py` | Lossless danbooru-tag conversion of the freeform hero description; falls back to narrator tags |

## Setup screen

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Setup options served from backend | done | `setup_options.py`, `GET /api/setup-options`, `schemas.SetupOptions` | `test_setup_options.py`, `test_api.py` | Single source of truth; lists change on the backend only |
| Setting presets + Custom + Random | done | `SETTING_OPTIONS`, `SETTING_DESCRIPTIONS`, `resolve_randoms` | `test_setup_options.py` | 21 presets |
| Genre picker, up to 5 combined, Random | done | `GENRE_OPTIONS`, `MAX_GENRES = 5` | `test_setup_options.py` | |
| Adult genres gated behind 18+ | done | `ADULT_GENRE_OPTIONS`, `StoryCreate.adult_options_require_adult_rating` (422) | `test_content_and_style.py` | Hentai, Erotica, Slasher / gore, Extreme horror |
| Tone picker + Random | done | `TONE_OPTIONS` | `test_setup_options.py` | |
| Long freeform fields | done | `schemas.StoryCreate` limits (hero_role 1000, custom_setting 1000, content_restrictions 2000, custom_details 5000, hero_name 200) | `test_api.py` | Textareas on `SetupPage` |

## Story flow and choices

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Turn contract (JSON, three choice modes) | done | `SPEC.md` "Turn contract", `schemas.TurnContract`/`Choice` | `test_contract.py` | Do not change without an explicit instruction |
| Context assembly (facts, summary, last 3 turns) | done | `story_engine._system_prompt`, `_build_prompt` | `test_story_engine.py` | Narrator-style fragment and AGE RATING appended only when set |
| Parse/validate/retry-once | done | `story_engine._parse_contract`, `_generate_turn` | `test_story_engine.py` | The retry carries a description of what was wrong |
| Player input validation (option_id vs custom_text, 500 chars, no custom in locked/binary) | done | `schemas.TurnCreate`, `story_engine.add_turn` | `test_story_engine.py`, `test_api.py` | |
| Ending handling (`is_ending`, `choice=null`, status `finished`) | done | `story_engine._generate_turn` | `test_story_engine.py`, `test_contract.py` | The story ends exactly at `max_turns` |
| Binary choices only at story-defining moments | done | narrator prompt instructions | manual | Prompt-level rule, not enforced in code |
| Persistence + resume (SQLite) | done | `db.py`, `models.py`, `story_engine` | `test_api.py`, `test_story_engine.py` | Startup `ALTER TABLE` migration for new columns |

## Narrator prompts and styles

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Narrator system prompt + turn template as files | done | `backend/app/prompts/narrator_system.txt`, `turn_message.txt`, `story_engine.load_prompt` | `test_story_engine.py` | Replaceable without code changes |
| Narrator style picker (6 styles incl. Disco Elysium) | done | `NARRATOR_STYLE_OPTIONS`, `NARRATOR_STYLE_FRAGMENTS`, `narrator_style_fragment` | `test_content_and_style.py` | Changed mid-story via `PATCH /api/stories/{id}` + header dropdown |
| Mock narrator rotation | done | `llm.py` `_mock_contract` (seed = story id) | `test_llm.py` | Two mock stories no longer play the same episode |

## Characters and portraits

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Character tracking (`characters` table, hero pinned) | done | `models.Character`, `story_engine._process_character_reports`, `GET /api/stories/{id}/characters` | `test_characters.py` | One row per story and name |
| Character portraits on first appearance | done | `story_engine._queue_portrait`, `image_service.process_character_portrait` | `test_characters.py` | Same single-worker queue as scenes |

## Image generation and ComfyUI

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Scene illustrations via local ComfyUI | done | `services/image_service.py`, env `IMAGE_GENERATION_ENABLED`, `COMFYUI_URL`, `IMAGE_TIMEOUT_SECONDS`, `IMAGE_DIR` | `test_image_service.py`, `test_image_api.py` | One daemon worker thread + `queue.Queue`, never blocks text |
| Backend-owned prompt assembly (quality prefix, rating token, style tags, `adult` enforcement) | done | `assemble_positive_prompt`, `assemble_portrait_prompt`, `negative_extra_for` | `test_image_prompts.py` | Deterministic string building; the rating is never the model's choice |
| Image style picker per story | done | `IMAGE_STYLE_OPTIONS`, `IMAGE_STYLE_TAGS`, `image_style_tags`, story settings `image_style` | `test_content_and_style.py`, `test_image_prompts.py` | Positive tags after the quality prefix; negative tags appended to node 7, never replacing |
| `characters_in_scene` tag splicing | done | `image_service._scene_appearance_tags`, `Turn.characters_in_scene` | `test_image_prompts.py` | Hero first; falls back to hero-only tags |
| Image fallbacks (format + prompt) | done | `story_engine._generate_turn` normalization | `test_story_engine.py` | Bad `image_format` → `wide`; empty prompt → generic scene shot |
| Heal-first image retry | done | `image_service.retry_turn_image`, `retry_character_portrait` | `test_image_service.py` | An existing file on disk heals to `done` without GPU work |
| ComfyUI stale-job cancellation on timeout | done | `image_service.cancel_job` (called from `wait_for_result`) | `test_image_service.py` | Delete from the queue; `/interrupt` only if currently running |
| Interrupted-job reset at startup | done | `image_service.reset_interrupted_turns`, `main.py` lifespan | `test_image_service.py` | `queued`/`generating` → `failed` ("Interrupted") |
| img2img portrait reference mode | done | env `IMAGE_REFERENCE_MODE`, `IMAGE_REFERENCE_NODES`, `IMAGE_REFERENCE_DENOISE`; `apply_reference_images`, `_inject_img2img_chain` | `test_reference_images.py` | Auto-injected LoadImage→ImageScale→VAEEncode; denoise default 0.75 |
| Deliberate scene prompting (camera shots, composition, varied expressions) | done | `narrator_system.txt` image-tag rules | manual (prompt-level) | `medium wide shot` default for people scenes |
| VRAM conductor (Ollama + ComfyUI on one GPU) | done | env `GPU_VRAM_CONDUCTOR`; `image_service._ollama_unload`, `_comfyui_free` | `test_image_service.py` | Opt-in; best-effort with 10 s timeouts |

## Content rating

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Age rating per story (3+ to 18+, default 12+) | done | `AGE_RATING_OPTIONS`, `age_rating_clause`, story settings `age_rating` | `test_content_and_style.py` | Governs narration and images; absent for pre-rating stories |
| 18+ sub-options (`explicit_sexual`, `graphic_violence`) | done | `StoryCreate` fields + 422 validation below 18+ | `test_content_and_style.py` | Both default off |
| Absolute rules at every rating (adults only, restrictions override, ceiling not quality) | done | `age_rating_clause` closing lines | `test_content_and_style.py` | |

## Story management

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Story list / resume / delete with confirmation | done | `HomePage`, `GET/DELETE /api/stories…` | `test_api.py`, manual | Delete also removes images (see above) |
| Change beginning (edit setup while only the opening exists) | done | `PATCH /api/stories/{id}`, `StoryPage` → `SetupPage` flow | `test_api.py` | |
| Regenerate opening | done | `POST /api/stories/{id}/regenerate-start`, `story_engine.regenerate_start` | `test_story_engine.py` | Single-turn stories only |
| Redo last turn | done | `POST /api/stories/{id}/regenerate-last`, `story_engine.regenerate_last_turn`; "Redo last turn" button in `StoryPage` | `test_story_engine.py` | Works on finished stories; rolls back characters/portraits/image of the deleted turn |

## Frontend components

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Turn feed with auto-scroll | done | `StoryPage`, `TurnView` | manual | |
| ChoicePanel (three modes) | done | `components/ChoicePanel.tsx` | manual | Custom input hidden in locked/binary |
| ImageBlock (four states) | done | `components/ImageBlock.tsx` | `ImageBlock.test.tsx` | Placeholder reserves aspect ratio; polls while in progress |
| CharactersPanel (cards + detail + retry) | done | `components/CharactersPanel.tsx` | `CharactersPanel.test.tsx` | Polls only while a portrait is in progress; retries after failures |
| Shared fullscreen lightbox | done | `components/Lightbox.tsx` | `Lightbox.test.tsx` | Zoom toggle, Esc/backdrop/✕ close, scroll lock, `role="dialog"` |
| Narrator style dropdown in story header | done | `StoryPage` (PATCHes story settings) | manual | Applies from the next turn |
| Loading indicator / double-submit protection / ErrorBanner | done | `LoadingIndicator.tsx`, `ErrorBanner.tsx`, `StoryPage` | manual | |
| Single `api.ts` module typed to the backend schemas | done | `frontend/src/api.ts` | `tsc --noEmit` | |

## Developer tooling

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Mock LLM mode | done | env `MOCK_LLM`, `llm.py` mock narrator | `test_llm.py` | Honors language and turn limit; localized openings |
| Mock image mode | done | env `MOCK_IMAGES`, `image_service._mock_png` | `test_image_service.py` | 1x1 placeholder PNG via stdlib after ~3 s |
| Backend test suite | done | `backend/tests/` (conftest pins env so tests never inherit `.env`) | `cd backend && pytest` | |
| Frontend component tests (vitest + Testing Library) | done | `frontend/src/components/*.test.tsx` | `cd frontend && npx vitest run && npx tsc --noEmit` | Dev-only dependencies |
| Docs consistency test | done | `backend/tests/test_docs_consistency.py` | `pytest` | `.env.example` covers `config.py`; `ARCHITECTURE.md` API paths match routes |

| Image cleanup on story delete | done | `routers/stories.py` `_delete_story_images` | `test_api.py` | Verified to stay inside `IMAGE_DIR`; failures logged, never fatal |
| Wide-scene face detail (FaceDetailer/ADetailer node) | planned | `comfy_workflows/*.json` (user-side node, no backend change) | manual | Known SDXL limitation: distant faces smear in wide scenes; see `BACKLOG.md` |

| Portrait history / evolving portraits (`portrait_update`, `portrait_revert`) | done | `Character.portrait_history`, `_apply_portrait_update`, `_apply_portrait_revert`, `PortraitVersionRead` | `test_characters.py` | Revert reuses the existing file, zero GPU jobs |
| "Past looks" gallery | done | `CharacterRead.portrait_history`, `CharactersPanel` detail view | `CharactersPanel.test.tsx` | Hidden when there is only one look |
| Portraits clothed by default (clothing guard) | done | `image_service.PORTRAIT_BANNED_TOKENS`, `_strip_portrait_banned`, `portrait_wants_nudity`, `_strip_clothing_guard` | `test_image_prompts.py` | Explicit only when 18+ explicit AND the narrator tags the look as nude |
| Per-portrait pose/expression | done | `CharacterReport.pose`/`expression`, `assemble_portrait_prompt` | `test_image_prompts.py` | Never spliced into scene tags |
| Full-figure portrait framing | done | `assemble_portrait_prompt` framing suffix | `test_image_prompts.py` | `full body, standing, looking at viewer, simple background` |
| Inline introduction portraits in the feed | done | `first_seen_turn_id`, `IntroducedCharacters` component | `IntroducedCharacters.test.tsx` | |

| Hero gender picker | done | `HERO_GENDER_OPTIONS`, `GENDER_TAGS`, story settings `hero_gender` | `test_content_and_style.py`, `test_image_prompts.py` | Maps to `1girl`/`1boy` image tags; shown in the turn prompt |
| Freeform hero appearance mirrored into `appearance_tags` | done | `StoryCreate.hero_appearance`, `llm.faithful_appearance_tags`, mock `_mock_hero_tags` | `test_llm.py`, `test_image_prompts.py` | The narrator is ordered to mirror the description exactly |
| Story length (short/medium/long/custom 50-500) | done | `LENGTH_OPTIONS`, `story_engine.max_turns_for_length` | `test_story_engine.py` | |
| Story language (Russian/English/Kazakh) | done | `LANGUAGE_OPTIONS`, `StoryCreate.language` | `test_llm.py` (mock honors language) | |
| Setting culture + naming-culture override | done | `CULTURE_OPTIONS`, story settings `setting_culture`/`naming_culture` | `test_setup_options.py` | "Match story language" default keeps old behavior |
| Intro exposition checkbox (default on) | done | `StoryCreate.intro_exposition = True`, `story_engine._build_prompt` | `test_story_engine.py` | Off = in-medias-res opening |
| Content restrictions field (overrides everything) | done | `StoryCreate.content_restrictions`, narrator prompt | `test_story_engine.py` | Exclusionary; overrides the age rating |

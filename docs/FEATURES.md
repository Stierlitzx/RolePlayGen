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
| Per-story provider picker (Gemini / Groq / OpenRouter / Mistral / local) | done | story settings `llm_provider`; `story_engine._provider_for_story`/`_effective_provider`; `llm.py` `_cloud_endpoint`; setup-options fields `default_provider`, `gemini_models`, `local_model`, `groq_model`, `openrouter_model`, `mistral_model`…; `SetupPage` | `test_api.py`, `test_story_engine.py`, `test_llm.py` | Stories without the field follow `LLM_PROVIDER`; the 503 check applies to the story's actual provider; an empty provider key disables it in the picker |
| Groq output-token cap | done | `llm.py` `GROQ_MAX_OUTPUT_TOKENS` | `test_llm.py` | Groq free OTPM ~1000 rejects larger requests (429 "Request too large"); Groq turns capped at 950 |
| OpenRouter/Mistral model fallback chains | done | `llm.py` `OPENROUTER_FALLBACK_ORDER`, `MISTRAL_FALLBACK_ORDER`, `_call_cloud_with_fallback` | `test_llm.py` | 429/404/503 retries the next model, like the Gemini fallback; Mistral falls back across model classes (medium → small → ministral) |
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
| Long freeform fields | done | `schemas.StoryCreate` limits (hero_role/hero_appearance/custom_setting 3000, content_restrictions 6000, custom_details 15000, hero_name 200); turn fields custom_text 1500, note_text 2000 | `test_api.py`, `test_player_notes.py` | Textareas on `SetupPage`, note field in `ChoicePanel` |

## Story flow and choices

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Turn contract (JSON, three choice modes) | done | `SPEC.md` "Turn contract", `schemas.TurnContract`/`Choice` | `test_contract.py` | Do not change without an explicit instruction |
| Context assembly (facts, summary, last 3 turns) | done | `story_engine._system_prompt`, `_build_prompt` | `test_story_engine.py` | Narrator-style fragment and AGE RATING appended only when set |
| Parse/validate/retry-once | done | `story_engine._parse_contract`, `_generate_turn` | `test_story_engine.py` | The retry carries a description of what was wrong |
| Narration format guard (prose, not a dialogue wall) | done | `services/narration_style.py` (`narration_problems`, `paragraphs`, `quotes_in`, `speech_word_share`), wired in `story_engine._generate_turn`; `narrator_system.txt` PROSE FIRST + DIALOGUE SPACING rules | `test_narration_style.py`, `test_story_engine.py` | Turns over 700 characters: fewer than 3 paragraphs, more than 60% speech/thought words, or a paragraph holding more than 5 quoted exchanges (a chain of replies in one block) get ONE rewrite request; the second answer is accepted as it is, because a style problem never fails a turn |
| Repetition guard (the narrator must not replay the same turn) | done | `services/narration_style.repetition_problems`, wired in `story_engine._generate_turn`; `narrator_system.txt` NOVELTY rule; `turn_message.txt` RECENT TURNS label | `test_narration_style.py`, `test_story_engine.py` | The new turn is compared with the last three: a re-used run of 8 words (`REPEATED CONTENT`) or a verbatim quoted line / italic thought of 2+ words (`REPEATED DIALOGUE`) asks for ONE rewrite, quoting the reused text. Names, places and short turns alone never trigger it; the second answer is accepted as it is |
| Player input validation (option_id vs custom_text, 1500 chars, no custom in locked/binary) | done | `schemas.TurnCreate`, `story_engine.add_turn` | `test_story_engine.py`, `test_api.py` | |
| Ending handling (`is_ending`, `choice=null`, status `finished`) | done | `story_engine._generate_turn` | `test_story_engine.py`, `test_contract.py` | The story ends exactly at `max_turns` |
| Binary choices only at story-defining moments | done | narrator prompt instructions | manual | Prompt-level rule, not enforced in code |
| Persistence + resume (SQLite) | done | `db.py`, `models.py`, `story_engine` | `test_api.py`, `test_story_engine.py` | Startup `ALTER TABLE` migration for new columns |
| Note to the narrator (optional field, fact/event notes, pinned facts panel) | done | `schemas.TurnCreate.note_text`, `TurnContract.note_type`/`normalized_text`, `story_engine._pin_fact`/`_apply_note_classification`/`delete_pinned_fact`, prompts (`PLAYER FACTS`/`PLAYER NOTE` blocks, PLAYER NOTES rules), `ChoicePanel` note field, `TurnView` note display, `StoryPage` pinned-facts panel, `DELETE /api/stories/{id}/pinned-facts/{index}` | `test_player_notes.py`, `ChoicePanel.test.tsx`, `TurnView.test.tsx` | Empty note = no behavior change; fact pinned for the whole story, event fires once; regenerate replays the note and rolls back its pinned fact; the mock narrator classifies notes too |

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
| Backend-owned prompt assembly (rating token, style tags, `adult` enforcement) | done | `assemble_positive_prompt`, `assemble_portrait_prompt`, `negative_extra_for` | `test_image_prompts.py` | Deterministic string building; the rating is never the model's choice; the SDXL-era quality prefix is gone (it made Qwen cartoonish) |
| Image style picker per story | done | `IMAGE_STYLE_OPTIONS`, `IMAGE_STYLE_TAGS`, `image_style_tags`, `image_service._style_wrap` (the style opens AND closes every prompt), story settings `image_style` | `test_content_and_style.py`, `test_image_prompts.py` | Positive tags after the quality prefix; negative tags kept for API compatibility but not written (Qwen-Image-2.1 runs at cfg=1, no negative prompt) |
| `characters_in_scene` tag splicing | done | `image_service._scene_appearance_tags`, `Turn.characters_in_scene` | `test_image_prompts.py` | Hero first; falls back to hero-only tags |
| Image fallbacks (format + prompt) | done | `story_engine._generate_turn` normalization | `test_story_engine.py` | Bad `image_format` → `wide`; empty prompt → generic scene shot |
| Heal-first image retry | done | `image_service.retry_turn_image`, `retry_character_portrait` | `test_image_service.py` | An existing file on disk heals to `done` without GPU work |
| ComfyUI stale-job cancellation on timeout | done | `image_service.cancel_job` (called from `wait_for_result`) | `test_image_service.py` | Delete from the queue; `/interrupt` only if currently running |
| Interrupted-job reset at startup | done | `image_service.reset_interrupted_turns`, `main.py` lifespan | `test_image_service.py` | `queued`/`generating` → `failed` ("Interrupted") |
| img2img portrait reference mode | done | env `IMAGE_REFERENCE_MODE`, `IMAGE_REFERENCE_NODES`, `IMAGE_REFERENCE_DENOISE`; `apply_reference_images`, `_inject_img2img_chain`, `_reference_images_for_turn`, `_previous_portrait_reference` | `test_reference_images.py` | Auto-injected LoadImage→ImageScale→VAEEncode; denoise default 0.75; a portrait regeneration is driven by the previous portrait so an evolving look keeps the same face |
| Configurable sampler steps (IMAGE_STEPS) | done | env `IMAGE_STEPS`, `config.image_steps`, `image_service.build_workflow(steps=…)` | `test_image_prompts.py` | Generation time is roughly linear in the step count; 25 is the shipped default, 16 is the practical floor before Qwen-Image starts losing detail |
| Edit ("image → image") graph with up to 10 reference images | done | `comfy_workflows/{wide,portrait}_edit.json`, `image_service.build_edit_workflow`, `EDIT_IMAGE_SLOTS` | `test_image_prompts.py` (+ live ComfyUI 0.37 probe) | `image_1` is the picture being edited, `image_2..image_10` are references wired through `TextEncodeQwenImage21.images`; the sampler's latent comes from the encoded target unless `custom_size` is set. The graph shape was verified by running a real 2-step job on the user's ComfyUI |
| Image log (what the picture model was told) | done | `image_service.format_build_log`, `Turn.image_build_log`, `Character.portrait_build_log`, `TurnRead`/`CharacterRead`, "🖼 Image log" in `StoryPage` + the log block in `CharactersPanel` | `test_image_prompts.py` | Plain-text record per picture: mode (text to image / edit + what image_1 was), steps, seed, references, the final positive prompt. This is how a player tells "my photo was ignored" from "it was used and the result differs" |
| Re-pictured character appears in the story feed at once | done | `CharactersPanel.onCharacterUpdated` → `StoryPage.applyCharacterUpdate` | manual | The Characters tab hands the updated row up, so the feed and the sidebar show the new picture without a page reload (the feed used to keep the old portrait until reload) |
| Hero photo upload at story setup | done | `StoryCreate.hero_image`, `story_engine._store_hero_image`, `SetupPage` file field | `test_characters.py` | Sent as a base64 data URL, written to `IMAGE_DIR/{story_id}/hero_photo.png`, kept in the story settings as a path; replaceable mid-story (the only picture a running story accepts) |
| Player-supplied character picture (Characters tab) | done | `Character.photo_path`/`photo_url`, `POST /api/characters/{id}/portrait`, `CharactersPanel` upload field | `test_characters.py`, `CharactersPanel.test.tsx` | The upload becomes the reference every picture is built from and, with `use_as_portrait`, the card itself — no GPU job |
| Scenes and portraits generated through the edit graph | done | `image_service.process_turn_image`/`process_character_portrait`, `assemble_edit_prompt`/`assemble_portrait_edit_prompt`, `scene_edit_references`/`portrait_edit_reference` | `test_image_prompts.py`, `test_reference_images.py` | Scene: image_1 = the hero photo, image_2..N = the other people's pictures, canvas forced to 16:9 (`custom_size`). Portrait: image_1 = the player's photo or the previous portrait, canvas follows it. Stories without any photo keep the old tag-only jobs |
| Scene illustrations render tag-only by default | done | env `IMAGE_SCENE_REFERENCE` (default off); `apply_reference_images(..., as_latent=...)`, `_reference_images_for_turn` gating, wired in `process_turn_image` | `test_reference_images.py`, `test_scene_continuity.py` | The scene sampler no longer starts from a portrait (a 4:5 portrait center-cropped onto the 16:9 canvas forced its crop/pose/single frame onto every scene); scenes render from prompt + spliced `appearance_tags`. Opt in with `IMAGE_SCENE_REFERENCE=true` |
| Duplicate-character guard (fuzzy name matching) | done | `services/character_matching.py` `find_character`; used by `story_engine._find_character` (reports, portrait updates, `characters_in_scene` canonicalization) and `image_service` (scene tag splicing, reference portraits) | `test_character_matching.py`, `test_characters.py`, `test_reference_images.py` | Exact → prefix/one-word-token → shared lowercase descriptor token ("Тайный странник" ~ "Странник в чёрном"); capitalized surnames and genitive forms do NOT merge |
| Deliberate scene prompting (camera shots, composition, varied expressions) | done | `narrator_system.txt` image-tag rules | manual (prompt-level) | `medium wide shot` default for people scenes; wide shots with a named character restate appearance anchors in `image_prompt`; group scenes are the exception to the close-camera rule — they are pulled back into a two-shot (see the group-scene guard row) |
| Current-place rule in `image_prompt` | done | `narrator_system.txt` `CURRENT PLACE ONLY` rule | manual (prompt-level) | The place is named first and the left-behind location dropped, so a move (forest → hut) shows the new scene |
| Previous-location negative guard | done | `image_service.previous_scene_negative` (+ `PLACE_WORDS`, `_scene_moved`), wired in `process_turn_image` | `test_scene_continuity.py` | Only when `state.scene` really moved (shared word roots = same place); at most 4 place words, never whole tags (a tag may carry a character); scene references are always portraits, never previous scenes |
| ComfyUI output folders per story | done | `image_service.process_turn_image`/`process_character_portrait` `filename_prefix` | `test_scene_continuity.py` | `output/roleplaygen/story_<id>/{scene_<turn>,portrait_<char>}_*.png` instead of one flat list of every story |
| Scene illustrations always render wide | done | `story_engine` (`turn.image_format = "wide"`), `narrator_system.txt`/`turn_message.txt` | `test_story_engine.py` | Framing via shot tags, not the format; old stories keep their saved portrait scenes |
| Scene prompt order: scene first, appearance after | done | `image_service.assemble_positive_prompt` | `test_image_prompts.py`, `test_content_and_style.py` | Spliced appearance tags follow the narrator's scene tags — earlier tokens dominate composition; leading with the hero's look produced pin-ups on empty backgrounds |
| Group-scene composition guard (two-shot, facing each other) | done | `image_service._group_scene_tags`/`_group_person_tags` (+ `SHOT_TAGS`, `GROUP_INTERACTION_TAGS`, `LONE_PERSON_TAGS`, `group_scene_negative`), wired in `assemble_positive_prompt`/`process_turn_image`; `narrator_system.txt` GROUP SCENES rule | `test_image_prompts.py` | With two or more visible characters (from `characters_in_scene`, or from the spliced anchors): `solo` and a lone `1girl`/`1boy` are dropped, count tags are written from the stored anchors, anything tighter than `medium wide shot` is replaced, `two-shot, facing each other, looking at each other` is added and `looking at viewer` is negated |
| NPC gender tag mandatory in `appearance_tags` | done | `narrator_system.txt` character-reporting rule | manual (prompt-level) | `1boy`/`1girl` must be the first tag — without it the image model invents a gender |
| VRAM conductor (Ollama + ComfyUI on one GPU) | done | env `GPU_VRAM_CONDUCTOR`; `image_service._ollama_unload`, `_comfyui_free` | `test_image_service.py` | Opt-in; best-effort with 10 s timeouts |
| World anchors per setting preset | done | `setup_options.SETTING_ANCHOR_TAGS`, `setting_anchor`, `assemble_positive_prompt`/`assemble_portrait_prompt` (`world_tags=`) | `test_setup_options.py`, `test_image_prompts.py` | 21 presets get deterministic era tags (medieval fantasy, etc.) after place tags, so scenes don't spawn modern objects; Custom has none |
| Portrait face-forward guarantee | done | `image_service.BACK_TURNED_TAGS`, `_drop_back_turned`, `_portrait_framing`, `narrator_system.txt` | `test_characters.py` | "From behind", "over the shoulder" etc. stripped from portraits (kept in scenes); frontal gaze added when no gaze is stated |
| English tag enforcement (auto-translation) | done | `services/image_tags.py` (`has_cyrillic`), `llm.translate_image_tags`, `story_engine._english_tags` | `test_image_tags.py`, `test_llm.py` | Cyrillic image tags from small narrators translated to English danbooru tags once; mock mode stays out of the way |
| Hero proportion backstop | done | `services/image_tags.py` (`ensure_trait_tags`, `missing_trait_tags`), `llm.faithful_appearance_tags` prompt, `story_engine._generate_turn` | `test_image_tags.py`, `test_story_engine.py` | Ordered phrase-to-tag map ensures player-described chest size (huge/large/small), hips, waist, legs, build survive compression into tags |
| Interrupted job adoption on restart | done | `models.Turn.image_prompt_id`, `Character.portrait_prompt_id`, `image_service.job_recovery_state`, `reset_interrupted_turns`, `resume_turn_image`, `resume_character_portrait` | `test_image_service.py` | Still-drawing ComfyUI jobs resumed instead of marked failed; finished outputs adopted; prevents duplicate regeneration on Retry |
| Sentinel protection (`__hero__` is not a character) | done | `character_matching.is_hero_placeholder`, `HERO_PLACEHOLDER_NAMES`, `story_engine._hero_row_name`, `_process_character_reports`, `narrator_system.txt` | `test_character_matching.py`, `test_characters.py` | Prevents duplicate hero card when model reports `__hero__` / "hero" in `characters` list |
| Empty choice prompt repaired (no lost turn) | done | `setup_options.choice_prompt_fallback`, `story_engine._repair_empty_choice_prompt` (+ `narrator_system.txt`) | `test_story_engine.py` | A narrator returning `choice.prompt: ""` no longer costs the player the turn: the default question is filled in the story language |

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
| Turn feed as chat messages with auto-scroll | done | `StoryPage`, `TurnView` (renders `ChatMessage`) | manual | Player input is a right-aligned bubble, narration an avatar + meta line |
| Story feed scroll memory | done | `StoryPage` (`feedRef` + `sessionStorage` key `roleplaygen.storyScroll.{id}`) | manual | Position survives the Characters tab, the sidebar and Home; a genuinely new turn still jumps to its opening line |
| ChoicePanel (three modes, collapsible) | done | `components/ChoicePanel.tsx` | `ChoicePanel.test.tsx` | Custom input hidden in locked/binary; starts COLLAPSED (player request) as a slim bar with the prompt and a "Show choices" button, so the choice UI never covers the feed until it is asked for |
| ImageBlock (four states) | done | `components/ImageBlock.tsx` | `ImageBlock.test.tsx` | Placeholder reserves aspect ratio; polls while in progress |
| CharactersPanel (list + detail + retry) | done | `components/CharactersPanel.tsx` | `CharactersPanel.test.tsx` | List on the left, detail card on the right; polls only while a portrait is in progress; retries after failures |
| Shared fullscreen lightbox | done | `components/Lightbox.tsx` | `Lightbox.test.tsx` | Zoom toggle, Esc/backdrop/✕ close, scroll lock, `role="dialog"` |
| Narrator style dropdown in the story top bar | done | `StoryPage` (PATCHes story settings) | manual | Applies from the next turn |
| Loading indicator / double-submit protection / ErrorBanner | done | `LoadingIndicator.tsx`, `ErrorBanner.tsx`, `StoryPage` | manual | |
| Single `api.ts` module typed to the backend schemas | done | `frontend/src/api.ts` | `tsc --noEmit` | |
| Workspace app shell (sidebar + topbar + chat-style story feed, dark/amber theme) | done | `frontend/src/components/ui/` (`AppShell`, `TopBar`, `ChatMessage`, `ChatInputBar`), `styles.css` design tokens, pages | `SetupPage.test.tsx` + existing component tests | Visual-only redesign per the frontend redesign brief; no data or API changes |

## Developer tooling

| Feature | Status | Where it lives | Tested by | Notes |
| --- | --- | --- | --- | --- |
| Mock LLM mode | done | env `MOCK_LLM`, `llm.py` mock narrator | `test_llm.py` | Honors language and turn limit; localized openings |
| Mock image mode | done | env `MOCK_IMAGES`, `image_service._mock_png` | `test_image_service.py` | 1x1 placeholder PNG via stdlib after ~3 s |
| Backend test suite | done | `backend/tests/` (conftest pins env so tests never inherit `.env`) | `cd backend && pytest` | |
| Tests never write into the real IMAGE_DIR | done | `tests/conftest.py` (`settings.image_dir` → tmp_path + autouse `_no_writes_into_the_real_image_dir`) | `pytest` | `image_dir` defaults to the real `./data/images`; the upload tests once left two 5-byte files in the developer's story folder |
| Frontend component tests (vitest + Testing Library) | done | `frontend/src/components/*.test.tsx`, `frontend/src/pages/*.test.tsx` | `cd frontend && npx vitest run && npx tsc --noEmit` | Dev-only dependencies |
| Docs consistency test | done | `backend/tests/test_docs_consistency.py` | `pytest` | `.env.example` covers `config.py`; `ARCHITECTURE.md` API paths match routes |

| Image cleanup on story delete | done | `routers/stories.py` `_delete_story_images` | `test_api.py` | Verified to stay inside `IMAGE_DIR`; failures logged, never fatal |
| Wide-scene face detail (FaceDetailer/ADetailer node) | planned | `comfy_workflows/*.json` (user-side node, no backend change) | manual | Known SDXL limitation: distant faces smear in wide scenes; see `BACKLOG.md` |

| Portrait history / evolving portraits (`portrait_update`, `portrait_revert`) | done | `Character.portrait_history`, `_apply_portrait_update`, `_apply_portrait_revert`, `PortraitVersionRead` | `test_characters.py` | Revert reuses the existing file, zero GPU jobs |
| Character age in picture prompts (never shown to the player) | done | `Character.age`, `CharacterReport.age`/`HeroReport.age`, `image_service.assemble_portrait_prompt(age=)`/`_look_with_age`, narrator AGE rule | `test_image_prompts.py` | The narrator reports a rough age in English words ("a woman in her fifties"); it is spliced into portraits and scene anchors so a mother stops looking like a teenager, kept once it is set, and never exposed in the API. Creatures without a human age (a cat, a dragon) simply report none, and an immortal reports "ageless" |
| Hero look evolution (the player character is not frozen) | done | `schemas.HeroReport.portrait_update`/`portrait_revert`, `story_engine._process_character_reports` (hero branch) + `_build_prompt` (`current look:` in KNOWN CHARACTERS); `narrator_system.txt` hero rules | `test_content_and_style.py`, `test_story_engine.py` | A persistent change of the hero's look (disguise, new clothes, armor, a haircut, a wound) repaints the portrait and every later scene image; `portrait_revert` restores the previous look with zero GPU jobs; one-scene details (mud, sweat) stay in `image_prompt` |
| "Past looks" gallery | done | `CharacterRead.portrait_history`, `CharactersPanel` detail view | `CharactersPanel.test.tsx` | Hidden when there is only one look |
| Content tag filtering — temporarily OFF | off | `image_service.sanitize_tags` (quality dedup only); `NUDITY_TOKENS` + `portrait_wants_nudity` keep the rating gate | `test_image_prompts.py`, `test_characters.py` | The narrator's nudity/rating words reach the image model untouched and spliced appearance tags are never edited; restore by refilling the token sets (DECISIONS 2026-09-25) |
| Per-portrait pose/expression (hero included) | done | `CharacterReport.pose`/`expression`, `HeroReport.pose`/`expression`, `assemble_portrait_prompt`, `story_engine._process_character_reports` | `test_image_prompts.py`, `test_characters.py` | The hero is no longer the one portrait the narrator cannot pose; never spliced into scene tags |
| Portrait framing head-to-thighs (cowboy shot) | done | `image_service.PORTRAIT_SUFFIX`, `_portrait_framing`, `PORTRAIT_FALLBACK_POSE`/`PORTRAIT_FALLBACK_GAZE`, `assemble_portrait_prompt` | `test_characters.py` | `cowboy shot` keeps the face detailed; `standing`/`looking at viewer` are fallbacks for blank portraits only — a stated pose, gaze or shot is never overridden |
| Inline introduction portraits in the feed | done | `first_seen_turn_id`, `IntroducedCharacters` component | `IntroducedCharacters.test.tsx` | |
| "New look" portrait rows in the feed | done | `IntroducedCharacters.charactersWithNewLook` + `lookChanged`, `TurnView.updated`, `StoryPage` | `IntroducedCharacters.test.tsx`, `TurnView.test.tsx` | The turn a `portrait_update`/`portrait_revert` happened in shows the new portrait under the narration |

| Hero gender picker | done | `HERO_GENDER_OPTIONS`, `GENDER_TAGS`, story settings `hero_gender` | `test_content_and_style.py`, `test_image_prompts.py` | Maps to `1girl`/`1boy` image tags; shown in the turn prompt |
| Freeform hero appearance mirrored into `appearance_tags` | done | `StoryCreate.hero_appearance`, `llm.faithful_appearance_tags`, mock `_mock_hero_tags` | `test_llm.py`, `test_image_prompts.py` | The narrator is ordered to mirror the description exactly |
| Story length (short/medium/long/custom 50-500) | done | `LENGTH_OPTIONS`, `story_engine.max_turns_for_length` | `test_story_engine.py` | |
| Story language (Russian/English/Kazakh) | done | `LANGUAGE_OPTIONS`, `StoryCreate.language` | `test_llm.py` (mock honors language) | |
| Setting culture + naming-culture override | done | `CULTURE_OPTIONS`, story settings `setting_culture`/`naming_culture` | `test_setup_options.py` | "Match story language" default keeps old behavior |
| Intro exposition checkbox (default on) | done | `StoryCreate.intro_exposition = True`, `story_engine._build_prompt` | `test_story_engine.py` | Off = in-medias-res opening |
| Content restrictions field (overrides everything) | done | `StoryCreate.content_restrictions`, narrator prompt | `test_story_engine.py` | Exclusionary; overrides the age rating |

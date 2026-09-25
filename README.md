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

General `.env` settings:

| Variable | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | key for real Gemini calls (empty = Gemini not configured) |
| `MODEL_NAME` | default Gemini model; players can also pick one per story |
| `MOCK_LLM` | `true` = the mock narrator answers instead of any API, no key needed |
| `DATABASE_URL` | SQLAlchemy URL for the story database (default `sqlite:///./story.db`) |
| `MAX_TOKENS` | generation budget per turn (default 4000; must fit 350-700 word turns) |

### Local text model (uncensored, optional)

Gemini applies its own safety filters on top of the story's age rating. If you want no cloud-side filtering at all, point the backend at any OpenAI-compatible local server — [Ollama](https://ollama.com), LM Studio or llama.cpp — which can run uncensored fine-tunes (Dolphin, Hermes, abliterated builds, …):

```powershell
ollama pull llama3.1:8b   # or dolphin3, qwen3:8b, mistral-nemo:12b …
ollama serve              # listens on http://localhost:11434
```

then in `.env`:

```
MOCK_LLM=false
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1   # LM Studio: http://localhost:1234/v1
OPENAI_MODEL=llama3.1:8b                     # the tag from `ollama list`
```

No API key is needed. All providers can be configured at once: the setup screen has a "Text model source" picker (Gemini, Groq, OpenRouter or the local model) stored per story, and `LLM_PROVIDER` only sets the default choice. Notes: a local 7-12B model narrates noticeably weaker than Gemini (Russian especially — Qwen and Gemma-based fine-tunes handle it best), JSON contract breaks are retried once as usual, and on an 8 GB card don't run the LLM and ComfyUI at the same time — let the text finish before image jobs start (the image queue already waits, but VRAM is shared).

### Free cloud providers (Groq, OpenRouter and Mistral are built in)

If the GPU is busy drawing and a local LLM doesn't fit, **Groq**, **OpenRouter** and **Mistral** are first-class providers: give each its own key in `.env` and they join the "Text model source" picker next to Gemini and the local model, selectable per story:

```
GROQ_API_KEY=gsk-...            # free key at console.groq.com/keys
GROQ_MODEL=qwen/qwen3.8-27b
OPENROUTER_API_KEY=sk-or-...    # key at openrouter.ai/keys
OPENROUTER_MODEL=qwen/qwen3.8-27b:free
MISTRAL_API_KEY=...             # free Experiment tier key at console.mistral.ai (no card, SMS only)
MISTRAL_MODEL=mistral-medium-latest
```

An empty key disables that provider in the picker. Reality check first: *free + unlimited + uncensored* doesn't exist, you pick two. Per-turn roleplay needs only ~1 request, so even modest daily caps are plenty.

| Service | Free quota (verify on their site) | Censorship |
| --- | --- | --- |
| **Google Gemini** | ~250-1000 req/day on Flash-class models | yes, but we send `BLOCK_ONLY_HIGH` |
| **Mistral** | ~1B tokens/month, per-model-class minute limits | moderate; **free-tier prompts may be used for training** |
| **OpenRouter** | 20 RPM, 50 req/day (1000/day after a one-time $10 credit purchase) | none on uncensored fine-tunes; the general free pool is model-aligned |
| **Groq** | 30 RPM, ~1000 req/day, very fast — but only ~1000 output tokens/min | provider moderation on top |
| **Cerebras** | no permanent free tier anymore ($5 trial, 30 days, card required) | provider moderation |

Provider quirks the backend handles for you: Groq turns are capped at 950 output tokens (its free per-minute output limit rejects larger requests outright), and both OpenRouter and Mistral automatically fall back to the next model when the chosen one is rate-limited — free pools are shared and often congested (on Mistral the chain degrades medium → small → ministral-14b → ministral-8b).

Other OpenAI-compatible clouds have no dedicated picker entry — point the generic local slot at them (`LLM_PROVIDER=openai`, `OPENAI_BASE_URL=…`, `OPENAI_API_KEY=…`, `OPENAI_MODEL=…`), one at a time.

Current OpenRouter `:free` picks for narration (checked 2026-09-22 via their API; the catalog changes often, browse `openrouter.ai/models?q=free`): `qwen/qwen3.8-27b:free` (best free Russian), `z-ai/glm-5.2:free` (strong prose), `google/gemma-4-31b-it:free`, `nvidia/nemotron-3-super-120b-a12b:free`. Note: dedicated uncensored roleplay fine-tunes (Dolphin, Hermes, Magnum) are **no longer in the free pool** — they are still nearly free: `cognitivecomputations/dolphin-mistral-24b-venice-edition` costs ~$0.2/M input tokens, i.e. roughly a cent per story turn, and `nousresearch/hermes-3-llama-3.1-70b` ~$0.7/M.

Rule of thumb: for dark/gory 18+ stories stay on Gemini (best free quota, and our safety setting already stops most false blocks) or Mistral (huge monthly quota, moderate filters); for explicit 18+ the only free-ish cloud path is an uncensored fine-tune on OpenRouter; true unlimited + uncensored exists only locally (a small 3-4B model on CPU via Ollama works even while the GPU draws — slow but free).

### Scene illustrations (optional)

Turns can get AI-drawn illustrations from a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) server. Install ComfyUI, put the Qwen-Image-2.1 models into its model folders (`diffusion_models/qwen_image_2.1_int8_convrot.safetensors`, `text_encoders/qwen3vl_8b_w4a8.safetensors`, `vae/qwen_image_2.1_vae_bf16.safetensors`) plus the LoRAs used by the bundled single-pass workflows (`Pornmaster_QI2.1_Breasts_Slider_V1`, `NSFW Qwen Lora`), then start it:

```powershell
python main.py   # serves http://127.0.0.1:8188
```

Image settings in `.env`:

| Variable | Meaning |
| --- | --- |
| `IMAGE_GENERATION_ENABLED` | `true` to draw scenes; `false` hides the feature entirely |
| `COMFYUI_URL` | where ComfyUI listens (default `http://127.0.0.1:8188`) |
| `IMAGE_TIMEOUT_SECONDS` | how long one job may take (default 300; raise to ~900 if a GPU-resident local text model slows ComfyUI down) |
| `IMAGE_DIR` | where PNGs are saved, served under `/media/` (default `./data/images`) |
| `MOCK_IMAGES` | `true` = skip ComfyUI and write a placeholder PNG after ~3 s, no GPU needed |
| `IMAGE_REFERENCE_MODE` | `off` (default) or `img2img` = feed the portrait of each character in the scene back into generation, so faces/outfits stay consistent pictures, not just prompt text |
| `IMAGE_REFERENCE_NODES` | optional comma-separated extra LoadImage node ids for custom workflows (img2img needs none) |
| `IMAGE_REFERENCE_DENOISE` | how strongly the reference drives the sampler in img2img mode (default 0.75) |
| `IMAGE_SCENE_REFERENCE` | `false` (default) = scenes render from prompt + character tags; `true` = also feed the first in-scene portrait into the scene sampler (tighter faces, but the picture inherits the portrait's 4:5 crop and pose) |
| `GPU_VRAM_CONDUCTOR` | `true` when Ollama and ComfyUI share one GPU: the text model is unloaded from VRAM before each image job and ComfyUI's cache freed after it (text model reloads on the next turn, ~10-30 s once) |

Images are generated one at a time in the background by a single daemon worker thread fed from a `queue.Queue` — never two jobs on the GPU in parallel — and never block the text. If ComfyUI is off, the story works as usual and the image block offers a Retry button. All images carry the story's age rating as their rating token (`general` unless the story is 18+ with explicit content enabled) and depict adults only; the narrator's own content tags are not filtered right now (see `docs/DECISIONS.md`). Note: the bundled Qwen-Image-2.1 workflow runs the sampler at cfg=1, so there is no negative prompt — style negatives, the `nsfw` guard and the previous-place guard are computed but intentionally not applied.

With `IMAGE_REFERENCE_MODE=img2img` (plus hand-built `IMAGE_REFERENCE_NODES`, or `IMAGE_SCENE_REFERENCE=true` for scenes) the backend uploads the in-scene characters' current portraits to ComfyUI and wires the first one into the sampler through an auto-injected LoadImage → ImageScale → VAEEncode chain (no workflow editing needed; portraits and turns without a finished portrait generate exactly as before if the relevant switch is off). The reference is always a character portrait — never a previous scene — and ComfyUI writes both scenes and portraits into per-story folders of its own `output/` (`output/roleplaygen/story_3/scene_10_*.png`, `.../portrait_7_*.png`), so its raw output does not become one flat list of every story; the app then copies each file into `IMAGE_DIR/<story_id>/`.

When the story moves somewhere else, the picture must move with it. The narrator is told to name the new place first and drop the old one, and the backend helps deterministically: if the narrator's `state.scene` names a different place than the previous turn, the previous scene's place words that the new prompt no longer uses are computed (up to four; never whole tags, a tag may carry a character) by `previous_scene_negative` — but with the Qwen-Image-2.1 workflow (cfg=1, no negative prompt) they are intentionally not applied. When `IMAGE_SCENE_REFERENCE=true` is on, its 4:5 portrait latent can still pin the old place: raise `IMAGE_REFERENCE_DENOISE` toward 0.75-0.8 or turn the switch off — by default scenes render without any portrait latent at all.

Tip: faces of distant characters in wide scenes can smear — a known SDXL limitation. Adding a FaceDetailer/ADetailer node to the `comfy_workflows/*.json` graphs fixes it without any backend change (the node needs no inputs from the app); watch the extra VRAM on an 8 GB card.

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
npm test          # component tests (vitest + Testing Library, dev-only dependencies)
npm run build
```

## Features

- Story length: 50 turns (short), 100 turns (medium), unlimited (long), or a custom count (50-500)
- Players pick the text model per story: Gemini (cloud — 3.6 Flash / 3.5 Flash / 3.1 Flash-Lite / 3 Flash Preview) or the configured local model (Ollama / LM Studio); the default comes from `.env`
- 21 setting presets plus Custom/Random, up to 3 genres combined from 20, and a freeform "Custom details" field for the plot premise, wanted characters, factions and starting conflict. An optional "Hero appearance" field pins the hero's look for the narration and every generated image; a Hero gender picker (Unspecified/Female/Male) drives the narration and the `1girl`/`1boy` image tags
- The first turn either drops the player straight into a scene (default) or opens with an explanatory intro of the world and the hero — controlled by the "Explain the world and the hero" checkbox at setup
- Story language (Russian / English / Kazakh) is independent from the setting culture (Slavic, Western European, East Asian, …): narration follows the language, names and cultural flavor follow the culture. An optional naming-culture override pins character names to a specific culture
- A Characters tab on the story screen tracks every named NPC (plus the hero, pinned first) with portrait, role, relationship to the player and description; portraits are drawn by ComfyUI when a character first appears, in the same one-job-at-a-time queue as scene illustrations
- Age rating per story (3+ to 18+, PEGI-style) governs both the narration and the images; at 18+ two optional switches unlock explicit sexual content and/or graphic gore, and the genre picker gains adult genres (Hentai, Erotica, Slasher / gore, Extreme horror). Up to 5 genres can be combined. Note: Gemini's own safety filters (set to block only high-severity content) still apply on top of the story rating — if the model refuses a turn, the error message says so explicitly instead of failing obscurely
- Narrator style picker: Classic, Noir, Epic saga, Light and witty, Gothic dread — and a Disco Elysium mode with intrusive capitalized skill-voices. The narrator voice can be changed mid-story from the story screen header
- Image style picker (Anime default, Semi-realistic, Cinematic realistic, Comic book, Watercolor storybook) pins one art style for every image of the story
- Character looks stay consistent across images: the narrator defines `appearance_tags` once per character and the backend splices them into every image prompt where the character is present. Portraits are painted head-to-thighs as reference cards, each with its own narrator-supplied pose and expression (stance, camera side, gaze; a blank portrait falls back to a generic standing look), so characters no longer share one identical pose; scenes render from the scene prompt plus the spliced tags by default, so a scene owns its own framing instead of inheriting the portrait's 4:5 crop. When the story changes a character's look the portrait is regenerated and the turn that changed it shows the new picture in the story feed as a "New look" row, and when they change back the previous portrait returns instantly without new GPU work. This works for the hero as well: a persistent change of the player character's look (a disguise, different clothes, armor, a haircut, a wound) is repainted the same way, and every later scene image uses the new look — one-scene details (mud, sweat, rain) stay in that turn's own image prompt and never touch the stored look. Portraits keep the `general` rating token unless the story is 18+ explicit AND the narrator deliberately describes that look as nude (plot-driven `portrait_update`) — the rating is the backend's decision, not the narrator's; the narrator's own nudity tags are passed through as written while content filtering is off (see `docs/DECISIONS.md`, 2026-09-25). The character detail view shows a "Past looks" gallery of every portrait version
- Every turn must be new: the narrator is told to continue the story instead of replaying it (no staged entrance behind the hero twice, no NPC returning with the same farewell, no re-describing the same place), and the backend compares each new turn with the previous three — re-used wording or a repeated line gets one rewrite request, never a lost turn
- Every image opens in a fullscreen in-app lightbox (click to zoom, Esc to close) — scenes, inline portraits and the Characters tab
- Deleting a story also deletes its generated images from disk. Retry on a failed image first checks the file on disk: if it exists (stale timeout, restart after download), the status heals to done without spending GPU time on a regeneration
- While a story has only its opening turn, you can edit the setup ("Change beginning") or reroll the prologue ("Regenerate opening"); after that, "Redo last turn" deletes the last turn and replays the same choice — works on finished stories too, so a bad ending can be redone
- You can upload a photo of the hero at story setup: every scene illustration is then an edit of that picture (image_1) with the other characters' pictures behind it (image_2..image_10), so the story is drawn around the face you chose instead of a text description. The Characters tab has the same control per character — "Use your own picture" makes your file the character's portrait immediately (no GPU work) and the reference every later picture of them is built from
- Sampler steps are configurable (`IMAGE_STEPS`, default 25): render time is roughly linear, so 16 is about 1.5x faster and still keeps detail
- Binary (two-option) choices appear only at story-defining moments, not on a schedule
- Stories play fully in Russian, English or Kazakh — mock mode included
- Optional scene illustrations via a local ComfyUI server: generated one at a time in the background, never blocking the text; `MOCK_IMAGES=true` develops the flow without a GPU

## Notes

- `.env` is git-ignored; `.env.example` documents all settings.
- The narrator prompt and turn template live in `backend/app/prompts/` and can be replaced without code changes. They instruct the model to write 350-700 word turns with dialogue and consistent character personalities.
- The mock AI honors the chosen language and turn limit, and ends the story exactly at the limit. The mock opening is a three-paragraph open-ended prologue and localizes preset setting names (no raw "Wizard school" in Russian/Kazakh prose)

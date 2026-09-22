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

No API key is needed. With `LLM_PROVIDER=openai` the setup screen's model picker collapses to the configured local model. Notes: a local 7-12B model narrates noticeably weaker than Gemini (Russian especially — Qwen and Gemma-based fine-tunes handle it best), JSON contract breaks are retried once as usual, and on an 8 GB card don't run the LLM and ComfyUI at the same time — let the text finish before image jobs start (the image queue already waits, but VRAM is shared).

### Free cloud alternatives (same `openai` provider)

If the GPU is busy drawing and a local LLM doesn't fit, the same `LLM_PROVIDER=openai` mode works with any OpenAI-compatible **cloud** API — just change the three variables. Reality check first: *free + unlimited + uncensored* doesn't exist, you pick two. Per-turn roleplay needs only ~1 request, so even modest daily caps are plenty.

| Service | `OPENAI_BASE_URL` | Free quota (verify on their site) | Censorship |
| --- | --- | --- | --- |
| **Google Gemini** (current default) | — | ~250-1000 req/day on Flash-class models | yes, but we send `BLOCK_ONLY_HIGH` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | 20 RPM, 50 req/day (1000/day after a one-time $10 credit purchase) | none on uncensored fine-tunes; the general free pool is model-aligned |
| **Groq** | `https://api.groq.com/openai/v1` | ~30 RPM, ~1000 req/day (Llama 3.3 70B), very fast | provider moderation on top |
| **Mistral** | `https://api.mistral.ai/v1` | generous token/month quota | moderate; **prompts may be used for training** |
| **Cerebras** | `https://api.cerebras.ai/v1` | 30 RPM, ~14 400 req/day | provider moderation |

Current OpenRouter `:free` picks for narration (checked 2026-09-22 via their API; the catalog changes often, browse `openrouter.ai/models?q=free`): `qwen/qwen3.8-27b:free` (best free Russian), `z-ai/glm-5.2:free` (strong prose), `google/gemma-4-31b-it:free`, `nvidia/nemotron-3-super-120b-a12b:free`. Note: dedicated uncensored roleplay fine-tunes (Dolphin, Hermes, Magnum) are **no longer in the free pool** — they are still nearly free: `cognitivecomputations/dolphin-mistral-24b-venice-edition` costs ~$0.2/M input tokens, i.e. roughly a cent per story turn, and `nousresearch/hermes-3-llama-3.1-70b` ~$0.7/M.

Example (OpenRouter):

```
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-...        # real key from openrouter.ai/keys
OPENAI_MODEL=qwen/qwen3.8-27b:free
```

Rule of thumb: for dark/gory 18+ stories stay on Gemini (best free quota, and our safety setting already stops most false blocks); for explicit 18+ the only free-ish cloud path is an uncensored fine-tune on OpenRouter; true unlimited + uncensored exists only locally (a small 3-4B model on CPU via Ollama works even while the GPU draws — slow but free).

### Scene illustrations (optional)

Turns can get AI-drawn illustrations from a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) server. Install ComfyUI, put the `waiIllustriousSDXL` checkpoint into its model folder plus the LoRAs used by the bundled workflows (`NOOB_vp1_detailer`, `facial expression style v3`, `Expressive_H`), then start it:

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
| `IMAGE_REFERENCE_DENOISE` | how strongly the reference drives the scene in img2img mode (default 0.55) |

Images are generated one at a time in the background and never block the text. If ComfyUI is off, the story works as usual and the image block offers a Retry button. All images follow the story's age rating (`general` unless the story is 18+ with explicit content enabled, and `nsfw` stays in the negative prompt everywhere else) and depict adults only.

With `IMAGE_REFERENCE_MODE=img2img` the backend uploads the in-scene characters' current portraits to ComfyUI and wires the first one into the first sampler through an auto-injected LoadImage → ImageScale → VAEEncode chain (no workflow editing needed; turns without a finished portrait generate exactly as before).

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
npm test          # component tests (vitest)
npm run build
```

## Features

- Story length: 50 turns (short), 100 turns (medium), unlimited (long), or a custom count (50-500)
- Players pick the AI model per story (Gemini 3.6 Flash / 3.5 Flash / 3.1 Flash-Lite / 3 Flash Preview); the default comes from `.env`
- 21 setting presets plus Custom/Random, up to 3 genres combined from 20, and a freeform "Custom details" field for the plot premise, wanted characters, factions and starting conflict. An optional "Hero appearance" field pins the hero's look for the narration and every generated image
- The first turn either drops the player straight into a scene (default) or opens with an explanatory intro of the world and the hero — controlled by the "Explain the world and the hero" checkbox at setup
- Story language (Russian / English / Kazakh) is independent from the setting culture (Slavic, Western European, East Asian, …): narration follows the language, names and cultural flavor follow the culture. An optional naming-culture override pins character names to a specific culture
- A Characters tab on the story screen tracks every named NPC (plus the hero, pinned first) with portrait, role, relationship to the player and description; portraits are drawn by ComfyUI when a character first appears, in the same one-job-at-a-time queue as scene illustrations
- Age rating per story (3+ to 18+, PEGI-style) governs both the narration and the images; at 18+ two optional switches unlock explicit sexual content and/or graphic gore, and the genre picker gains adult genres (Hentai, Erotica, Slasher / gore, Extreme horror). Up to 5 genres can be combined. Note: Gemini's own safety filters (set to block only high-severity content) still apply on top of the story rating — if the model refuses a turn, the error message says so explicitly instead of failing obscurely
- Narrator style picker: Classic, Noir, Epic saga, Light and witty, Gothic dread — and a Disco Elysium mode with intrusive capitalized skill-voices. The narrator voice can be changed mid-story from the story screen header
- Image style picker (Anime default, Semi-realistic, Cinematic realistic, Comic book, Watercolor storybook) pins one art style for every image of the story
- Character looks stay consistent across images: the narrator defines `appearance_tags` once per character and the backend splices them into every image prompt where the character is present. Portraits show the full figure with per-portrait pose and expression; when the story changes a character's look the portrait is regenerated, and when they change back the previous portrait returns instantly without new GPU work
- Every image opens in a fullscreen in-app lightbox (click to zoom, Esc to close) — scenes, inline portraits and the Characters tab
- Deleting a story also deletes its generated images from disk
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

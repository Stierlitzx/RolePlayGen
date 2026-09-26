from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    model_name: str = "gemini-3.5-flash"
    # Text model provider: "gemini" (default, cloud) or "openai" — any
    # OpenAI-compatible server (Ollama, LM Studio, llama.cpp). Local servers
    # can run uncensored fine-tunes and need no real API key.
    llm_provider: str = "gemini"
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: str = "ollama"
    openai_model: str = "llama3.1:8b"
    # Named cloud providers on the same OpenAI-compatible protocol, each
    # selectable per story in the setup form alongside gemini/local. Both have
    # free tiers; keys come from console.groq.com and openrouter.ai/keys.
    groq_api_key: str = ""
    # Live catalog 2026-09: llama-3.3-70b-versatile was retired; qwen3.8-27b
    # (131K ctx) is the strongest multilingual free text model on Groq.
    groq_model: str = "qwen/qwen3.8-27b"
    openrouter_api_key: str = ""
    # Best free Russian narration pick as of 2026-09; the uncensored Venice
    # fine-tune left the free pool (paid slug without ":free", ~$0.2/M tokens).
    openrouter_model: str = "qwen/qwen3.8-27b:free"
    # Mistral Experiment tier: ~1B tokens/month free, no card (SMS only), all
    # models; moderate censorship, but free-tier prompts may train their models.
    # mistral-large is NOT on the free tier — medium (262K ctx) is the
    # strongest available; magistral-* are reasoning models, avoid.
    mistral_api_key: str = ""
    mistral_model: str = "mistral-medium-latest"
    database_url: str = "sqlite:///./story.db"
    max_tokens: int = 4000
    mock_llm: bool = False
    image_generation_enabled: bool = False
    comfyui_url: str = "http://127.0.0.1:8188"
    image_timeout_seconds: int = 300
    image_dir: str = "./data/images"
    mock_images: bool = False
    # Sampler steps per image. Time is roughly linear: the bundled workflows ship
    # with 25, and the same picture costs ~3x less at 12-16 on an 8 GB card. Below
    # ~12 Qwen-Image starts losing detail (hands, fabric, small props), so 16 is
    # the sensible floor for a comfortable speed/quality trade-off.
    image_steps: int = 25
    # The seed is FIXED for every picture (IMAGE_SEED) and matches the value the
    # bundled workflow files carry, so the same prompt reproduces the same image.
    image_seed: int = 593103825222985
    # How the seed is chosen per picture. "fixed" = every picture uses
    # IMAGE_SEED, so the same prompt reproduces the same image and a "repaint"
    # button cannot show anything new. "per_picture" = the base seed is mixed
    # with a counter that advances for every picture actually drawn, so
    # successive turns stop landing on the same composition while a retry of the
    # SAME job still reuses the seed recorded in its log.
    image_seed_mode: str = "per_picture"
    # Reference-image feeding (optional, requires LoadImage nodes added to the
    # ComfyUI workflows by the user). "off" disables it entirely; "img2img"
    # also lowers the first sampler's denoise so the reference drives the look.
    image_reference_mode: str = "off"
    # Comma-separated LoadImage node ids in the workflows, one per reference
    # slot (e.g. "20,21" feeds up to two character portraits per scene).
    image_reference_nodes: str = ""
    # img2img denoise for portrait-referenced scenes. 0.55 keeps the portrait's
    # composition so tightly that the scene looks like a duplicate portrait;
    # 0.75 keeps the likeness (face, outfit) but lets the scene prompt own the
    # composition.
    image_reference_denoise: float = 0.75
    # Scene images normally render from the prompt plus the characters' stored
    # appearance tags. The auto-injected img2img chain is available for looks
    # that must not drift, but it starts the sampler from the portrait — a 4:5
    # reference squeezed onto the 16:9 scene canvas — so the picture inherits
    # the portrait's crop and pose (chest-level close-up, the second character
    # cropped away) instead of the framing the scene prompt asked for. Off by
    # default; set IMAGE_SCENE_REFERENCE=true to bring the old behavior back.
    image_scene_reference: bool = False
    # VRAM conductor for one GPU shared by the text model server (Ollama) and
    # ComfyUI: before each image job the text model is unloaded from VRAM
    # (Ollama keep_alive=0), after the job ComfyUI frees its model cache
    # (POST /free), so both never hold memory at once. The text model reloads
    # on the next turn (a one-time ~10-30 s delay).
    gpu_vram_conductor: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

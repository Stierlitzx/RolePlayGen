from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    model_name: str = "gemini-3.5-flash"
    database_url: str = "sqlite:///./story.db"
    max_tokens: int = 4000
    mock_llm: bool = False
    image_generation_enabled: bool = False
    comfyui_url: str = "http://127.0.0.1:8188"
    image_timeout_seconds: int = 300
    image_dir: str = "./data/images"
    mock_images: bool = False
    # Reference-image feeding (optional, requires LoadImage nodes added to the
    # ComfyUI workflows by the user). "off" disables it entirely; "img2img"
    # also lowers the first sampler's denoise so the reference drives the look.
    image_reference_mode: str = "off"
    # Comma-separated LoadImage node ids in the workflows, one per reference
    # slot (e.g. "20,21" feeds up to two character portraits per scene).
    image_reference_nodes: str = ""
    image_reference_denoise: float = 0.55

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

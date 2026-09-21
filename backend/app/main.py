from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import create_tables
from .routers.characters import router as characters_router
from .routers.images import router as images_router
from .routers.stories import router
from .services import image_service
from .services.story_engine import StoryEngineError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    create_tables()
    settings = get_settings()
    if settings.image_generation_enabled:
        for fmt in ("portrait", "wide"):
            image_service.load_workflow(fmt)  # fail fast with a clear error
        interrupted = image_service.reset_interrupted_turns()
        if interrupted:
            print(f"Reset {interrupted} interrupted image job(s) to failed.")
        image_service.start_worker()
    yield
    image_service.stop_worker()


app = FastAPI(title="RolePlayGen", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(images_router)
app.include_router(characters_router)

_image_dir = Path(get_settings().image_dir)
_image_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_image_dir)), name="media")


@app.exception_handler(StoryEngineError)
def story_engine_error_handler(_: Request, exc: StoryEngineError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

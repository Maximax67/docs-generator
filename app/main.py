import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from beanie import init_beanie
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles
from jinja2 import TemplateError
from pymongo import AsyncMongoClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.exceptions import document_validation_exception_handler
from app.limiter import limiter
from app.routes import api
from app.settings import settings
from app.models import (
    Feedback,
    PinnedFolder,
    User,
    Result,
    Session,
    Variable,
    SavedVariable,
)
from app.utils.cleanup import periodic_cleanup

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    client: AsyncMongoClient[Any] = AsyncMongoClient(
        settings.DATABASE_URL.get_secret_value()
    )
    await init_beanie(
        database=client["docs_generator"],
        document_models=[
            Feedback,
            PinnedFolder,
            User,
            Result,
            Session,
            Variable,
            SavedVariable,
        ],
    )

    cleanup_task = asyncio.create_task(periodic_cleanup())

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS else []

app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Retry-After",
        "X-RateLimit-Reset",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
    ],
)

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_exception_handler(TemplateError, document_validation_exception_handler)

app.include_router(api.router)
# app.mount("/", StaticFiles(directory="/app/static", html=True))

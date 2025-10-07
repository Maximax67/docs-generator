import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from beanie import init_beanie
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jinja2 import TemplateError
from pymongo import AsyncMongoClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.exceptions import document_validation_exception_handler, exception_handler
from app.limiter import limiter
from app.routes import api
from app.settings import settings
from app.models.database import Feedback, PinnedFolder, User, Result, Session
from app.utils import periodic_cleanup

from bot.bot import bot
from bot.utils.notify_admins import notify_admins
from bot.utils.set_bot_commands import set_bot_commands
from bot.utils.set_webhook import set_telegram_webhook


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    client: AsyncMongoClient[Any] = AsyncMongoClient(
        settings.DATABASE_URL.get_secret_value()
    )
    await init_beanie(
        database=client["docs_generator"],
        document_models=[PinnedFolder, Feedback, User, Result, Session],
    )
    await set_telegram_webhook(bot)
    await set_bot_commands(bot)

    cleanup_task = asyncio.create_task(periodic_cleanup())

    if settings.ADMIN_GREETING_ENABLED:
        await notify_admins(bot)

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()


async def async_exception_handler(request: Request, exc: Exception) -> Response:
    return await exception_handler(request, exc, bot)


origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS else []

app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_TITLE,
    version=settings.APP_TITLE,
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
app.add_exception_handler(Exception, async_exception_handler)

app.include_router(api.router)
app.mount("/", StaticFiles(directory="/app/static", html=True))

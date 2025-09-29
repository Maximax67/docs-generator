from contextlib import asynccontextmanager
from beanie import init_beanie
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo import AsyncMongoClient

from app.exceptions import exception_handler
from app.routes import api
from app.settings import settings
from app.models.database import Feedback, TrustedFolder, User, Result

from bot.bot import bot
from bot.utils.notify_admins import notify_admins
from bot.utils.set_bot_commands import set_bot_commands
from bot.utils.set_webhook import set_telegram_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncMongoClient(settings.DATABASE_URL.get_secret_value())
    await init_beanie(
        database=client["docs_generator"],
        document_models=[TrustedFolder, Feedback, User, Result],
    )
    await set_telegram_webhook(bot)
    await set_bot_commands(bot)
    await notify_admins(bot)

    yield

    await bot.session.close()


async def async_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return await exception_handler(request, exc, bot)


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_TITLE,
    version=settings.APP_TITLE,
)
app.add_exception_handler(Exception, async_exception_handler)
app.include_router(api.router)

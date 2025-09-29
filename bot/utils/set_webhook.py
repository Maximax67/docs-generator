from urllib.parse import urljoin
from aiogram import Bot

from app.settings import settings


async def set_telegram_webhook(bot: Bot) -> None:
    await bot.set_webhook(
        url=urljoin(str(settings.API_URL), "/api/telegram"),
        secret_token=settings.TELEGRAM_SECRET.get_secret_value(),
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )

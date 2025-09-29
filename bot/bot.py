from aiogram import Bot, Dispatcher

from app.settings import settings
from bot.middleware.throttling import ThrottlingMiddleware
from bot.routers.admin_router import admin_router
from bot.routers.user_router import user_router


bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
dp = Dispatcher()

dp.update.middleware.register(ThrottlingMiddleware())

dp.include_router(admin_router)
dp.include_router(user_router)

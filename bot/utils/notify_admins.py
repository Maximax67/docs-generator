from aiogram import Bot

from app.settings import settings
from bot.keyboards.inline.close_button import close_btn


async def notify_admins(bot: Bot):
    return
    await bot.send_message(
        settings.ADMIN_CHAT_ID,
        "Я запустився!",
        message_thread_id=settings.ADMIN_GREETING_THREAD_ID,
        reply_markup=close_btn(),
    )

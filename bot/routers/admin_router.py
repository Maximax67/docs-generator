from aiogram import F, Router
from aiogram.filters import Command

from app.settings import settings
from bot.handlers.admin.ban import ban_handler, ban_list_handler, unban_handler
from bot.handlers.common.feedback import admin_feedback_reply_handler


admin_router = Router()
admin_router.message.filter(F.chat.id == settings.ADMIN_CHAT_ID)

admin_router.message.register(ban_handler, Command("ban"))
admin_router.message.register(unban_handler, Command("unban"))
admin_router.message.register(ban_list_handler, Command("ban_list"))

admin_router.message.register(admin_feedback_reply_handler, F.reply_to_message)

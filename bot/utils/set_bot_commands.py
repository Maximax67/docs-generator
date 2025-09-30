from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeAllGroupChats

from app.settings import settings


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустити бота"),
            BotCommand(command="cancel", description="Скасувати дію"),
        ]
    )
    await bot.set_my_commands(
        commands=[
            BotCommand(command="generate", description="Генерація документу"),
            BotCommand(command="feedback", description="Зворотній зв'язок"),
            BotCommand(command="statistics", description="Статистика"),
            BotCommand(command="saved_data", description="Збережені дані"),
        ],
        scope=BotCommandScopeAllGroupChats(),
    )
    await bot.set_my_commands(
        commands=[
            BotCommand(command="ban", description="Заблокувати користувача"),
            BotCommand(command="unban", description="Розблокувати користувача"),
            BotCommand(command="ban_list", description="Cписок заблокованих юзерів"),
        ],
        scope=BotCommandScopeChat(chat_id=settings.ADMIN_CHAT_ID),
    )

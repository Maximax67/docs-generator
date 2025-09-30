from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.callback import MainCallback


def close_btn() -> InlineKeyboardMarkup:
    btn = InlineKeyboardBuilder()
    btn.button(
        text="❌ Закрити",
        callback_data=MainCallback(action="close", q="").pack(),
    )

    return btn.as_markup()

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.callback import GenerationCallback, MainCallback


def suggest_save_data() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(
        text="💾 Зберегти дані",
        callback_data=GenerationCallback(action="save_data", q="").pack(),
    )
    kb.button(
        text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
    )

    return kb.as_markup()

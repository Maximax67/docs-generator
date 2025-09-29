from typing import Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.inline.button import GenerationCallback, MainCallback


def suggest_save_data():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="💾 Зберегти дані",
        callback_data=GenerationCallback(action="save_data", q="").pack(),
    )
    kb.button(
        text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
    )

    return kb.as_markup()

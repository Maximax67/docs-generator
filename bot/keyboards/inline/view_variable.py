from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.callback import SavedDataCallback, MainCallback


def view_variable_keyboard(position: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(
        text="☠️ Видалити",
        callback_data=SavedDataCallback(action="delete", q=str(position)).pack(),
    )

    kb.button(
        text="⬅️ Назад",
        callback_data=SavedDataCallback(action="goto", q=str(position)).pack(),
    )

    kb.button(
        text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
    )

    kb.adjust(2)

    return kb.as_markup()

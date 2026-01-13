from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.variables import is_variable_value_valid
from bot.keyboards.callback import GenerationCallback, MainCallback


def text_input(saved_input: str | None, is_skippable: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if saved_input and is_variable_value_valid(saved_input):
        kb.button(
            text=f"⭐️ {saved_input}",
            callback_data=GenerationCallback(
                action="use_offered_text_input", q=""
            ).pack(),
        )

    if is_skippable:
        kb.button(
            text="⏩ Пропустити ввід",
            callback_data=GenerationCallback(
                action="use_offered_text_input", q="skip"
            ).pack(),
        )

    kb.button(
        text="⬅️ Назад",
        callback_data=GenerationCallback(action="back", q="").pack(),
    )
    kb.button(
        text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
    )

    kb.adjust(1)

    return kb.as_markup()

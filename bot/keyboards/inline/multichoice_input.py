from typing import List, Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from app.services.variables import is_variable_value_valid
from bot.keyboards.inline.button import GenerationCallback, MainCallback

BREAK_COLUMNS_CHAR_LIMIT = 15


def multichoice_input(
    choices: List[str], saved_input: Optional[str], is_skippable: bool
):
    kb = InlineKeyboardBuilder()

    two_columns = all(len(choice) <= BREAK_COLUMNS_CHAR_LIMIT for choice in choices)

    if saved_input and saved_input in choices:
        idx = choices.index(saved_input)
        if is_variable_value_valid(saved_input):
            kb.row(
                InlineKeyboardButton(
                    text=f"⭐️ {saved_input}",
                    callback_data=GenerationCallback(
                        action="answer_multichoice", q=str(idx)
                    ).pack(),
                )
            )

    for i, choice in enumerate(choices):
        if choice == saved_input:
            continue

        if is_variable_value_valid(choice):
            kb.button(
                text=choice,
                callback_data=GenerationCallback(
                    action="answer_multichoice", q=str(i)
                ).pack(),
            )

    kb.adjust(2 if two_columns else 1)

    if is_skippable:
        kb.row(
            InlineKeyboardButton(
                text="⏩ Пропустити ввід",
                callback_data=GenerationCallback(
                    action="answer_multichoice", q="s"
                ).pack(),
            )
        )

    kb.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=GenerationCallback(action="back", q="").pack(),
        ),
        InlineKeyboardButton(
            text="❌ Закрити",
            callback_data=MainCallback(action="close", q="").pack(),
        ),
    )

    return kb.as_markup()

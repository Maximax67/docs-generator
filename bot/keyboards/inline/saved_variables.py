from typing import Tuple
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.keyboards.inline.button import SavedDataCallback, MainCallback

ITEMS_PER_PAGE = 3


def saved_variables_keyboard(variables: Tuple[str, str], pos: int):
    kb = InlineKeyboardBuilder()
    total = len(variables)

    page = pos // ITEMS_PER_PAGE
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = variables[start:end]

    for i, var in enumerate(page_items, start=start):
        kb.button(
            text=var[1],
            callback_data=SavedDataCallback(action="view", q=str(i)).pack(),
        )

    kb.adjust(1)

    nav_buttons = []
    if start > 0:
        prev_pos = max(0, start - ITEMS_PER_PAGE)
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=SavedDataCallback(action="goto", q=str(prev_pos)).pack(),
            )
        )
    if end < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=SavedDataCallback(action="goto", q=str(end)).pack(),
            )
        )

    if nav_buttons:
        kb.row(*nav_buttons)

    kb.row(
        InlineKeyboardButton(
            text="☠️ Видалити все",
            callback_data=SavedDataCallback(action="delete_all", q="").pack(),
        ),
        InlineKeyboardButton(
            text="❌ Закрити",
            callback_data=MainCallback(action="close", q="").pack(),
        ),
    )

    return kb.as_markup()

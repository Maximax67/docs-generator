from typing import List, Tuple
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.constants import PAGINATION_ITEMS_PER_PAGE
from bot.keyboards.callback import SavedDataCallback, MainCallback


def saved_variables_keyboard(
    variables: List[Tuple[str, str]], pos: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    total = len(variables)

    page = pos // PAGINATION_ITEMS_PER_PAGE
    start = page * PAGINATION_ITEMS_PER_PAGE
    end = start + PAGINATION_ITEMS_PER_PAGE
    page_items = variables[start:end]

    for i, var in enumerate(page_items, start=start):
        kb.button(
            text=var[1],
            callback_data=SavedDataCallback(action="view", q=str(i)).pack(),
        )

    kb.adjust(1)

    nav_buttons = []
    if start > 0:
        prev_pos = max(0, start - PAGINATION_ITEMS_PER_PAGE)
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

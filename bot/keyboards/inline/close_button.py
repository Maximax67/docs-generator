from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.inline.button import MainCallback


def close_btn():
    btn = InlineKeyboardBuilder()
    btn.button(
        text="❌ Закрити",
        callback_data=MainCallback(action="close", q="").pack(),
    )

    return btn.as_markup()

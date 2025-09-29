from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.keyboards.inline.button import GenerationCallback, MainCallback


def document_preview_keyboard(generate_now_available: bool):
    kb = InlineKeyboardBuilder()

    if generate_now_available:
        kb.button(
            text="⭐️ Згенерувати одразу",
            callback_data=GenerationCallback(action="generate_now", q="").pack(),
        )

    kb.button(
        text="🆗 Підтвердити вибір",
        callback_data=GenerationCallback(action="confirm_document", q="").pack(),
    )

    kb.adjust(1)

    kb.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=GenerationCallback(action="back", q="").pack(),
        ),
        InlineKeyboardButton(
            text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
        ),
    )

    return kb.as_markup()

import os
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List

from app.models.google import DriveFile, DriveFolder
from bot.keyboards.callback import GenerationCallback, MainCallback


def document_selector_keyboard(
    folders: List[DriveFolder],
    files: List[DriveFile],
    previous_available: bool,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    for folder in folders:
        kb.button(
            text=f"📁 {folder.name}",
            callback_data=GenerationCallback(
                action="select_folder", q=folder.id
            ).pack(),
        )

    for file in files:
        if file.mime_type == "application/vnd.google-apps.document":
            name = file.name
        else:
            name, _ = os.path.splitext(file.name)

        kb.button(
            text=f"📄 {name}",
            callback_data=GenerationCallback(
                action="select_document", q=file.id
            ).pack(),
        )

    if previous_available:
        kb.button(
            text="⬅️ Назад",
            callback_data=GenerationCallback(action="back", q="").pack(),
        )

    kb.button(
        text="❌ Закрити", callback_data=MainCallback(action="close", q="").pack()
    )

    kb.adjust(1)

    return kb.as_markup()

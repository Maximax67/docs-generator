from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="⚡ Генерація"),
            KeyboardButton(text="💬 Зворотний зв'язок"),
        ],
        [
            KeyboardButton(text="📊 Статистика"),
            KeyboardButton(text="💾 Збережені дані"),
        ],
    ],
    resize_keyboard=True,
)

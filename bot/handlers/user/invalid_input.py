from aiogram.types import Message


async def invalid_input_handler(message: Message):
    await message.answer("Я не розумію тебе 😭")

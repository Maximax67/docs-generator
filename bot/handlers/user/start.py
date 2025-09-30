from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_keyboard import main_keyboard
from bot.utils.create_user import create_user


async def start_handler(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return

    await state.clear()

    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            f"Вітаю, {user.first_name}! Я бот для генерації документів",
            reply_markup=main_keyboard,
        )
    else:
        await message.answer(
            f"Вітаю, {message.chat.title}! Я бот для генерації документів",
        )

    try:
        await create_user(user)
    except Exception:
        pass

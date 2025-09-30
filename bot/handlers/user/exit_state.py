from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_keyboard import main_keyboard


async def exit_state_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Дія скасована", reply_markup=main_keyboard)


async def exit_main_state_handler(message: Message) -> None:
    await message.answer(
        "Немає активного стану для скасування...", reply_markup=main_keyboard
    )

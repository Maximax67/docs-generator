from aiogram.types import Message
from aiogram.fsm.context import FSMContext


async def delete_last_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    message_id = data.get("last_message_id")
    if message_id is None:
        return

    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=message_id)
    except Exception:
        pass

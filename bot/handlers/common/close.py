from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext


async def close(call: CallbackQuery, state: FSMContext):
    last_message_id = await state.get_value("last_message_id")

    if not last_message_id or call.message.message_id >= last_message_id:
        await state.clear()

    await call.message.delete()

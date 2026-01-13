from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from app.db.database import Result, User
from bot.utils.delete_last_message import delete_last_message


async def statistics_handler(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    await delete_last_message(message, state)
    await state.clear()

    telegram_id = message.from_user.id
    total_count = await Result.find_all().count()
    user_doc = await User.find_one(User.telegram_id == telegram_id)

    if user_doc:
        user_count = await Result.find(Result.user.id == user_doc.id).count()
        is_banned = user_doc.is_banned
    else:
        user_count = 0
        is_banned = False

    total_users = await User.find_all().count()

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Користувачів: <b>{total_users}</b>\n"
        f"📑 Оброблено документів: <b>{total_count}</b>\n"
        f"📄 Твої документи: <b>{user_count}</b>\n"
        f"🔒 Статус акаунту: {'🚫 Заблокований' if is_banned else '✅ Активний'}"
    )

    await message.answer(text, parse_mode="HTML")

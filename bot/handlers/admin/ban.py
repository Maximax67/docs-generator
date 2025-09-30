from typing import List, Optional
from aiogram.types import Message

from app.models.database import Feedback, Result, User
from bot.utils.get_text_after_space import get_text_after_space


async def ban_unban_user(message: Message, to_ban: bool) -> Optional[int]:
    reply_message = message.reply_to_message
    user: Optional[User] = None
    user_id: Optional[int] = None
    user_id_str: Optional[str] = None

    if message.text:
        user_id_str = get_text_after_space(message.text)

    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            await message.reply("Не валідний user id")
            return None
    else:
        if not reply_message:
            await message.reply(
                "Команда /ban має бути реплаєм на повідомлення від юзера, згенерований документ або містити user id"
            )
            return None

        reply_msg_id = reply_message.message_id
        feedback_msg = await Feedback.find_one(
            Feedback.admin_message_id == reply_msg_id
        )

        if feedback_msg:
            user_id = feedback_msg.user_id
        else:
            result = await Result.find_one(
                Result.telegram_message_id == reply_msg_id, fetch_links=True
            )
            if not result:
                await message.reply(
                    "Команда /ban має бути реплаєм на повідомлення від юзера, згенерований документ або містити user id"
                )
                return None

            user = result.user

            if not user:
                await message.reply(
                    "Це анонімно згенерований документ. Забанити користувача не можливо"
                )
                return None

            if user.is_banned == to_ban:
                return 0

            user.is_banned = to_ban
            await user.save()

            return user_id

    user = await User.find_one(User.telegram_id == user_id)
    if not user:
        await message.reply("Користувача не знайдено")
        return None

    if user.is_banned == to_ban:
        return 0

    user.is_banned = to_ban
    await user.save()

    return user_id


async def ban_handler(message: Message) -> None:
    user_id = await ban_unban_user(message, True)
    if user_id is None:
        return

    if user_id == 0:
        await message.reply("Користувач вже в бані")
        return

    admin_message = await message.reply("Користувач заблокований")

    try:
        bot = message.bot
        if bot:
            user_message = await bot.send_message(user_id, "🚫 Тебе забанили")

        await Feedback(
            user_id=user_id,
            user_message_id=user_message.message_id,
            admin_message_id=admin_message.message_id,
        ).insert()
    except Exception:
        pass


async def unban_handler(message: Message) -> None:
    user_id = await ban_unban_user(message, False)
    if user_id is None:
        return

    if user_id == 0:
        await message.reply("Користувач не в бані")
        return

    admin_message = await message.reply("Користувач розбанений")

    try:
        bot = message.bot
        if bot:
            user_message = await bot.send_message(user_id, "✅ Тебе розбанили")

        await Feedback(
            user_id=user_id,
            user_message_id=user_message.message_id,
            admin_message_id=admin_message.message_id,
        ).insert()
    except Exception:
        pass


async def ban_list_handler(message: Message) -> None:
    users: List[User] = await User.find(User.is_banned == True).to_list()  # noqa: E712

    if not users:
        await message.reply("✅ Ніхто не заблокований")
        return

    lines: List[str] = []
    for u in users:
        full_name = u.first_name
        if u.last_name:
            full_name += f" {u.last_name}"

        username_label = f"\n🔗 @{u.username}" if u.username else ""
        lines.append(f"👤 {full_name}{username_label}\n🆔 {u.telegram_id}")

    text = "🚫 Заблоковані користувачі\n\n" + "\n\n".join(lines)
    await message.reply(text)

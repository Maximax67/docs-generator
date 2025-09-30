from typing import List, Optional, Union
from aiogram import Bot
from aiogram.types import (
    Message,
    MessageEntity,
    User,
    ReactionTypeEmoji,
    UNSET_PARSE_MODE,
)
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.models.database import Feedback
from app.settings import settings

from bot.handlers.user.invalid_input import invalid_input_handler
from bot.keyboards.inline.close_button import close_btn
from bot.states.feedback import FeedbackStates
from bot.utils.delete_last_message import delete_last_message


async def store_message_mapping(
    user_id: int,
    user_message_id: int,
    admin_message_id: int,
    info_message_id: Optional[int] = None,
    is_info_message_admin: Optional[bool] = None,
) -> None:
    if (info_message_id is not None) != (is_info_message_admin is not None):
        raise ValueError(
            "Both info_message_id and is_info_message_admin must be set together"
        )

    message_mapping = Feedback(
        user_id=user_id,
        user_message_id=user_message_id,
        admin_message_id=admin_message_id,
    )

    if info_message_id is None:
        await Feedback.insert(message_mapping)
        return

    if is_info_message_admin:
        info_user_message = user_message_id
        info_admin_message = info_message_id
    else:
        info_user_message = info_message_id
        info_admin_message = admin_message_id

    info_message_mapping = Feedback(
        user_id=user_id,
        user_message_id=info_user_message,
        admin_message_id=info_admin_message,
    )

    await Feedback.insert_many([message_mapping, info_message_mapping])


async def get_user_message_id(
    admin_message_id: int,
) -> Union[tuple[int, int], tuple[None, None]]:
    feedback = await Feedback.find_one(Feedback.admin_message_id == admin_message_id)
    if feedback:
        return feedback.user_id, feedback.user_message_id

    return None, None


async def get_admin_message_id(user_id: int, user_message_id: int) -> Optional[int]:
    feedback = await Feedback.find_one(
        Feedback.user_id == user_id, Feedback.user_message_id == user_message_id
    )

    return feedback.admin_message_id if feedback else None


async def send_message_with_reply(
    chat_id: int,
    reply_message_id: int,
    message_text: str,
    bot: Bot,
    thread: Optional[int] = None,
    entities: Optional[List[MessageEntity]] = None,
    parse_mode: Optional[str] = UNSET_PARSE_MODE,
) -> Message:
    try:
        return await bot.send_message(
            chat_id,
            message_text,
            message_thread_id=thread,
            protect_content=False,
            entities=entities,
            reply_to_message_id=reply_message_id,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as e:
        if e.message != "Bad Request: message to be replied not found":
            raise e

        return await bot.send_message(
            chat_id,
            message_text,
            message_thread_id=thread,
            protect_content=False,
            entities=entities,
            parse_mode=parse_mode,
        )


def adjust_entities_and_message_text(
    prefix: str,
    text: str,
    entities: Optional[List[MessageEntity]],
    user: Optional[User] = None,
) -> tuple[str, list[MessageEntity]]:
    full_name = user.full_name if user else ""
    full_name_length = len(full_name.encode("utf-16-le")) // 2

    new_entities = []

    if user:
        new_entities.append(
            MessageEntity(
                type="code",
                offset=len(prefix.encode("utf-16-le")) // 2,
                length=full_name_length,
            )
        )

        prefix += full_name

        username = user.username
        if username:
            new_entities.append(
                MessageEntity(
                    type="url",
                    offset=(len(prefix.encode("utf-16-le")) // 2) + 2,
                    length=len(username) + 1,
                    url=f"https://t.me/{username}",
                )
            )

            prefix += f" (@{username})"

    prefix += ":\n\n"
    entity_offset = len(prefix.encode("utf-16-le")) // 2

    if entities:
        for entity in entities:
            adjusted_entity = entity.model_copy()
            adjusted_entity.offset += entity_offset
            new_entities.append(adjusted_entity)

    return prefix + text, new_entities


async def notify_message_sent(message: Message, state: FSMContext) -> None:
    await delete_last_message(message, state)
    answer = await message.answer(
        'Ваше повідомленя надіслано! За потреби надішліть ще одне, або натисність "Закрити".',
        reply_markup=close_btn(),
    )
    await state.update_data(last_message_id=answer.message_id)


async def send_feedback_handler(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    user_id = message.from_user.id
    message_id = message.message_id

    if message.text:
        user = message.from_user
        prefix = "📩 Нове повідомлення від "
        info_text, entities = adjust_entities_and_message_text(
            prefix,
            message.text,
            message.entities,
            user,
        )

        bot = message.bot
        if bot is None:
            raise Exception("Bot is None")

        forwarded_message = await bot.send_message(
            settings.ADMIN_CHAT_ID,
            info_text,
            message_thread_id=settings.ADMIN_FEEDBACK_THREAD_ID,
            protect_content=False,
            entities=entities,
            parse_mode=None,
        )
        await store_message_mapping(user_id, message_id, forwarded_message.message_id)
        await notify_message_sent(message, state)
        return

    full_name = message.from_user.full_name
    username = message.from_user.username
    username_label = (
        f' (<a href="https://t.me/{username}">@{username}</a>)' if username else ""
    )

    bot = message.bot
    if bot is None:
        raise Exception("Bot is None")

    info_message = await bot.send_message(
        settings.ADMIN_CHAT_ID,
        f"📩 Нове повідомлення від <code>{full_name}</code>{username_label}:",
        message_thread_id=settings.ADMIN_FEEDBACK_THREAD_ID,
        parse_mode="HTML",
    )

    forwarded_message = await message.forward(
        settings.ADMIN_CHAT_ID,
        settings.ADMIN_FEEDBACK_THREAD_ID,
        protect_content=False,
    )

    await store_message_mapping(
        user_id,
        message_id,
        forwarded_message.message_id,
        info_message.message_id,
        True,
    )

    await notify_message_sent(message, state)


async def user_feedback_reply_handler(message: Message) -> None:
    if not message.reply_to_message:
        return

    if message.from_user is None:
        await invalid_input_handler(message)
        return

    user_id = message.from_user.id
    reply_message_id = message.reply_to_message.message_id
    admin_message_id = await get_admin_message_id(user_id, reply_message_id)

    if not admin_message_id:
        await invalid_input_handler(message)
        return

    bot = message.bot
    if bot is None:
        raise Exception("Bot is None")

    if message.text:
        user = message.from_user
        prefix = "📨 Відповідь від "
        info_text, entities = adjust_entities_and_message_text(
            prefix,
            message.text,
            message.entities,
            user,
        )
        forwarded_message = await send_message_with_reply(
            settings.ADMIN_CHAT_ID,
            admin_message_id,
            info_text,
            bot,
            entities=entities,
        )
        await store_message_mapping(
            user_id,
            message.message_id,
            forwarded_message.message_id,
        )
        return

    full_name = message.from_user.full_name
    username = message.from_user.username
    username_label = (
        f' (<a href="https://t.me/{username}">@{username}</a>)' if username else ""
    )

    info_message = await send_message_with_reply(
        settings.ADMIN_CHAT_ID,
        admin_message_id,
        f"📨 Відповідь від <code>{full_name}</code>{username_label}:",
        bot,
        parse_mode="HTML",
    )

    forwarded_actual = await message.forward(
        settings.ADMIN_CHAT_ID,
        message_thread_id=info_message.message_thread_id,
        protect_content=False,
    )

    await store_message_mapping(
        user_id,
        message.message_id,
        forwarded_actual.message_id,
        info_message.message_id,
        True,
    )


async def admin_feedback_reply_handler(message: Message) -> None:
    if not message.reply_to_message:
        return

    user_id, user_message_id = await get_user_message_id(
        message.reply_to_message.message_id
    )

    if not user_id or not user_message_id:
        return

    bot = message.bot
    if bot is None:
        raise Exception("Bot is None")

    await bot.set_message_reaction(
        message.chat.id,
        message.message_id,
        [ReactionTypeEmoji(emoji="❤")],
    )

    if message.text:
        info_text, entities = adjust_entities_and_message_text(
            "📨 Відповідь адміністраторів",
            message.text,
            message.entities,
        )
        forwarded_message = await send_message_with_reply(
            user_id, user_message_id, info_text, bot, entities=entities
        )
        await store_message_mapping(
            user_id,
            forwarded_message.message_id,
            message.message_id,
        )
        return

    info_message = await send_message_with_reply(
        user_id, user_message_id, "📨 Відповідь адміністраторів:", bot
    )
    forwarded_message_to_user = await bot.copy_message(
        user_id,
        message.chat.id,
        message.message_id,
        protect_content=False,
    )

    await store_message_mapping(
        user_id,
        forwarded_message_to_user.message_id,
        message.message_id,
        info_message.message_id,
        False,
    )


async def feedback_handler(message: Message, state: FSMContext) -> None:
    await delete_last_message(message, state)
    await state.clear()
    await state.set_state(FeedbackStates.feedback)

    answer = await message.answer(
        "📩 Надішли сюди будь-яке повідомлення, і ми його отримаємо.\n"
        '❌ Якщо передумав, натисни "Закрити".',
        reply_markup=close_btn(),
    )

    await state.update_data(last_message_id=answer.message_id)

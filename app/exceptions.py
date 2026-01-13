import traceback
from typing import Any

from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.settings import settings


class ValidationErrorsException(Exception):
    def __init__(self, errors: dict[str, Any]):
        self.errors = errors
        super().__init__(errors)


async def document_validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": {"error_type": exc.__class__.__name__, "error": str(exc)}},
    )


async def exception_handler(request: Request, exc: Exception, bot: Bot) -> Response:
    if str(exc) == "Telegram server says - Bad Request: MESSAGE_ID_INVALID":
        return Response(status_code=200)

    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    filtered_lines = [line for line in tb_lines if "app" in line or "bot" in line]
    formatted_tb = "".join(filtered_lines) or tb_lines[-1]

    chat_id_str: str | None = None

    try:
        message_info: dict[str, str] = request.state.message_info
        chat_id_str = message_info.get("chat_id")
        user_id_str = message_info.get("user_id")
        full_name = message_info.get("full_name")
        username = message_info.get("username")
        message_thread_id_str = message_info.get("message_thread_id")

        footer = f"<code>{chat_id_str}</code>"
        if user_id_str:
            footer += f" | <code>{user_id_str}</code> | "

            if username:
                footer += f"<a href='https://t.me/{username}'>{full_name}</a>"
            else:
                footer += f"<code>{full_name}</code>"
    except AttributeError:
        footer = ""

    try:
        await bot.send_message(
            chat_id=settings.ADMIN_CHAT_ID,
            message_thread_id=settings.ADMIN_ERRORS_THREAD_ID,
            text=(
                "🚨 <b>Error Alert</b> 🚨\n\n"
                + str(exc)
                + "\n\n<pre>Short Traceback:\n"
                + formatted_tb
                + "</pre>"
                + footer
            ),
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

        if chat_id_str:
            chat_id = int(chat_id_str)
            if chat_id != settings.ADMIN_CHAT_ID:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Упс. Сталася помилка 🫠. Модератори отримали сповіщення про неї та постараються виправити баг",
                    message_thread_id=(
                        int(message_thread_id_str) if message_thread_id_str else None
                    ),
                )
    except Exception as bot_error:
        print("Failed to send error message to Telegram:", bot_error)

    return Response(status_code=500)

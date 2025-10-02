from typing import Dict
from aiogram.types import Update
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.dependencies import require_admin, verify_telegram_token
from app.exceptions import exception_handler
from app.models.common_responses import DetailResponse

from bot.bot import bot, dp
from bot.utils.set_webhook import set_telegram_webhook
from app.limiter import limiter


router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post(
    "",
    response_model=DetailResponse,
    dependencies=[Depends(verify_telegram_token)],
    responses={
        400: {
            "description": "Invalid update content",
            "content": {
                "application/json": {"example": {"detail": "Invalid update content"}}
            },
        },
        403: {
            "description": "Invalid Telegram token",
            "content": {
                "application/json": {"example": {"detail": "Invalid Telegram token"}}
            },
        },
    },
)
@limiter.limit("30/minute")
async def webhook(request: Request, response: Response) -> DetailResponse:
    try:
        raw_update = await request.json()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    update = Update.model_validate(raw_update, context={"bot": bot})

    try:
        message = update.message
        if message:
            message_info: Dict[str, str] = {
                "chat_id": str(message.chat.id),
                "message_thread_id": (
                    str(message.message_thread_id) if message.message_thread_id else ""
                ),
            }

            user = message.from_user
            if user:
                message_info["user_id"] = str(user.id)
                message_info["full_name"] = user.full_name

                if user.username:
                    message_info["username"] = user.username

            request.state.message_info = message_info

        await dp.feed_update(bot, update)
    except Exception as exc:
        await exception_handler(request, exc, bot)

    return DetailResponse(detail="ok")


@router.post(
    "/set_webhook",
    response_model=DetailResponse,
    dependencies=[Depends(require_admin)],
    responses={
        403: {
            "description": "Invalid token",
            "content": {"application/json": {"example": {"detail": "Invalid token"}}},
        },
    },
)
@limiter.limit("5/minute")
async def set_webhook(request: Request, response: Response) -> DetailResponse:
    await set_telegram_webhook(bot)

    return DetailResponse(detail="Webhook set successfully")


@router.post(
    "/delete_webhook",
    response_model=DetailResponse,
    dependencies=[Depends(require_admin)],
    responses={
        403: {
            "description": "Invalid token",
            "content": {"application/json": {"example": {"detail": "Invalid token"}}},
        },
    },
)
@limiter.limit("5/minute")
async def delete_webhook(request: Request, response: Response) -> DetailResponse:
    await bot.delete_webhook(drop_pending_updates=True)

    return DetailResponse(detail="Webhook deleted successfully")

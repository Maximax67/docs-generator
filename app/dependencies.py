from typing import Optional

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import HTTPBearer

from app.enums import TokenType, UserRole
from app.models.database import User
from app.services.auth import decode_jwt_token
from app.settings import settings

http_bearer = HTTPBearer()


def verify_telegram_token(
    x_telegram_token: str = Header(..., alias="X-Telegram-Bot-Api-Secret-Token")
) -> str:
    if x_telegram_token != settings.TELEGRAM_SECRET.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram token",
        )

    return x_telegram_token


async def get_current_user(request: Request) -> User:
    access_token: Optional[str] = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_jwt_token(access_token)
    if payload.get("type") != TokenType.ACCESS:
        raise HTTPException(status_code=401, detail="Invalid access token")

    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")

    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Forbidden")

    return current_user


async def authorize_user_or_admin(
    user_id: PydanticObjectId, current_user: User = Depends(get_current_user)
) -> UserRole:
    role = current_user.role

    if role == UserRole.ADMIN or (role == UserRole.USER and current_user.id == user_id):
        return role

    raise HTTPException(status_code=403, detail="Forbidden")

from beanie import PydanticObjectId
from fastapi import HTTPException, Header, Query, Request, status
from fastapi.security import HTTPBearer

from app.enums import TokenType, UserRole
from app.db.database import User
from app.services.auth import decode_jwt_token
from app.settings import settings
from app.schemas.auth import AuthorizedUser

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


def get_authorized_user(request: Request) -> AuthorizedUser:
    access_token: str | None = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_jwt_token(access_token)
    if payload.get("type") != TokenType.ACCESS:
        raise HTTPException(status_code=401, detail="Invalid access token")

    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")

    role = payload.get("role")
    if role is None or role not in UserRole:
        raise HTTPException(status_code=401, detail="Invalid role in token")

    is_email_verified = payload.get("email_verified")
    if is_email_verified is None or not isinstance(is_email_verified, bool):
        raise HTTPException(status_code=401, detail="Invalid email verified in token")

    return AuthorizedUser(
        user_id=user_id,
        role=UserRole(role),
        is_email_verified=is_email_verified,
    )


async def get_current_user(request: Request) -> User:
    authorized_user = get_authorized_user(request)

    user = await User.find_one(User.id == authorized_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


async def require_admin(request: Request) -> AuthorizedUser:
    authorized_user = get_authorized_user(request)
    if authorized_user.role != UserRole.ADMIN and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    return authorized_user


async def require_god(request: Request) -> AuthorizedUser:
    authorized_user = get_authorized_user(request)
    if authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    return authorized_user


async def authorize_user_or_admin(
    user_id: PydanticObjectId, request: Request
) -> AuthorizedUser:
    authorized_user = get_authorized_user(request)
    role = authorized_user.role

    if (
        role == UserRole.ADMIN
        or role == UserRole.GOD
        or authorized_user.user_id == user_id
    ):
        return authorized_user

    raise HTTPException(status_code=403, detail="Forbidden")


async def authorize_user_or_admin_query(
    request: Request,
    user_id: str | None = Query(None),
) -> AuthorizedUser:
    authorized_user = get_authorized_user(request)
    role = authorized_user.role

    if (
        role == UserRole.ADMIN
        or role == UserRole.GOD
        or str(authorized_user.user_id) == user_id
    ):
        return authorized_user

    raise HTTPException(status_code=403, detail="Forbidden")


async def authorize_user_or_god(
    user_id: PydanticObjectId, request: Request
) -> AuthorizedUser:
    authorized_user = get_authorized_user(request)
    role = authorized_user.role

    if role == UserRole.GOD or authorized_user.user_id == user_id:
        return authorized_user

    raise HTTPException(status_code=403, detail="Forbidden")

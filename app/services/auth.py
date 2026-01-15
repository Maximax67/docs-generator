from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import urljoin

import jwt
from beanie import Link, PydanticObjectId
from fastapi import HTTPException, Request, Response
from passlib.context import CryptContext
from secrets import token_urlsafe

from app.models import Session, User
from app.services.email import send_email
from app.settings import settings
from app.enums import TokenType
from app.services.bloom_filter import bloom_filter


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_auth_cookies(
    response: Response,
    access: str,
    refresh: str,
    expires_in: int,
    refresh_expires_in: int,
) -> None:
    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=access,
        max_age=expires_in,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,  # type: ignore[arg-type]
        domain=settings.COOKIE_DOMAIN,
        path="/api",
    )
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh,
        max_age=refresh_expires_in,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,  # type: ignore[arg-type]
        domain=settings.COOKIE_DOMAIN,
        path="/api/auth/refresh",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/api",
    )
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/api/auth/refresh",
    )


async def send_verification_email(user: User) -> None:
    if not user.email or user.email_verified:
        return

    token = create_jwt_token(
        subject=str(user.id),
        token_type=TokenType.VERIFY_EMAIL,
        expires_delta=timedelta(hours=24),
        jti=token_urlsafe(32),
        extra_claims={"email": user.email},
    )

    url = urljoin(str(settings.FRONTEND_URL), f"/verify-email?token={token}")

    await send_email(user.email, "Verify your email", "confirm", user.first_name, url)


def auth_user(request: Request) -> PydanticObjectId:
    access_token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_jwt_token(access_token)

    if payload.get("type") != TokenType.ACCESS:
        raise HTTPException(status_code=401, detail="Invalid access token")
    try:
        return PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")


def create_jwt_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    jti: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE

    payload["jti"] = jti

    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )

    return token


def decode_jwt_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE if settings.JWT_AUDIENCE else None,
            options={"verify_aud": bool(settings.JWT_AUDIENCE)},
        )

        jti = payload.get("jti")
        if jti is None or jti in bloom_filter:
            raise HTTPException(status_code=401, detail="Invalid token")

        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def issue_token_pair(
    user: User,
    session_name: str | None = None,
    session: Session | None = None,
) -> tuple[str, str, int, int]:
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")

    subject = str(user.id)
    access_jti = token_urlsafe(32)
    refresh_jti = token_urlsafe(32)

    if session:
        session.refresh_jti = refresh_jti
        session.access_jti = access_jti
        session.name = session_name

        await session.save_changes()
    else:
        await Session(
            user=cast(Link[User], user),
            refresh_jti=refresh_jti,
            access_jti=access_jti,
            name=session_name,
        ).create()

    access = create_jwt_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES),
        jti=access_jti,
        extra_claims={
            "email_verified": user.email_verified,
            "role": user.role.value,
        },
    )
    refresh = create_jwt_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS),
        jti=refresh_jti,
    )
    expires_in = int(
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES).total_seconds()
    )
    refresh_expires_in = int(
        timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS).total_seconds()
    )

    return access, refresh, expires_in, refresh_expires_in


async def rotate_refresh_token(
    user_id: PydanticObjectId, old_jti: str, session_name: str
) -> tuple[str, str, int, int]:
    session = await Session.find_one(Session.refresh_jti == old_jti, fetch_links=True)
    if (
        not session
        or session.user.id != user_id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    bloom_filter.add(session.access_jti)

    user = await User.find_one(User.id == user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return await issue_token_pair(user, session_name, session)


async def revoke_all_sessions(user_id: PydanticObjectId) -> None:
    async for session in Session.find(
        Session.user.id == user_id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        bloom_filter.add(session.access_jti)

    await Session.find(
        Session.user.id == user_id  # pyright: ignore[reportAttributeAccessIssue]
    ).delete()


async def revoke_session_by_jti(jti: str) -> None:
    s = await Session.find_one(Session.refresh_jti == jti)
    if s:
        bloom_filter.add(s.access_jti)
        await s.delete()


async def logout_current_session(request: Request, response: Response) -> None:
    access_cookie = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not access_cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    clear_auth_cookies(response)

    payload = decode_jwt_token(access_cookie)
    if payload.get("type") != TokenType.ACCESS:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")

    session = await Session.find_one(
        Session.user.id == user_id,  # pyright: ignore[reportAttributeAccessIssue]
        Session.access_jti == payload["jti"],
    )
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    bloom_filter.add(session.access_jti)
    await session.delete()

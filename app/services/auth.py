from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from beanie import PydanticObjectId
from fastapi import HTTPException, Request, Response
from passlib.context import CryptContext
from secrets import token_urlsafe

from app.models.database import Session, User
from app.services.email import render_confirm_email, send_email
from app.settings import settings
from app.enums import TokenType


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_auth_cookies(
    response: Response, access: str, refresh: str, expires_in: int
) -> None:
    # Access token cookie
    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=access,
        max_age=expires_in,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,  # type: ignore[arg-type]
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )
    # Refresh token cookie
    refresh_max_age = int(
        timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS).total_seconds()
    )
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh,
        max_age=refresh_max_age,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,  # type: ignore[arg-type]
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )


async def send_verification_email(user: User) -> None:
    if not user.email or user.email_verified:
        return

    token = create_jwt_token(
        subject=str(user.id),
        token_type=TokenType.VERIFY_EMAIL,
        expires_delta=timedelta(hours=24),
    )

    url = f"{settings.API_URL}/api/auth/email/verify?token={token}"
    html = render_confirm_email(user.first_name or user.email, url)

    await send_email(user.email, "Verify your email", html)


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
    jti: Optional[str] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    now = _utcnow()
    payload: Dict[str, Any] = {
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
    if jti is not None:
        payload["jti"] = jti
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return token


def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE if settings.JWT_AUDIENCE else None,
            options={"verify_aud": bool(settings.JWT_AUDIENCE)},
        )

        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def issue_token_pair(
    user: User, session_name: Optional[str]
) -> Tuple[str, str, int]:
    subject = str(user.id)
    refresh_jti = token_urlsafe(32)
    await Session(
        user=user, refresh_jti=refresh_jti, session_name=session_name
    ).create()

    access = create_jwt_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES),
        extra_claims={
            "email": user.email,
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
    return access, refresh, expires_in


async def rotate_refresh_token(
    user_id: PydanticObjectId, old_jti: str
) -> Tuple[str, str, int]:
    session = await Session.find_one(Session.refresh_jti == old_jti, fetch_links=True)
    if not session or session.user.id != user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    await session.delete()

    user = await User.find_one(User.id == user_id)
    assert user is not None
    return await issue_token_pair(user, session_name=session.session_name)


async def revoke_all_sessions(user_id: PydanticObjectId) -> None:
    await Session.find(Session.user.id == user_id).delete()


async def revoke_session_by_jti(jti: str) -> None:
    s = await Session.find_one(Session.refresh_jti == jti)
    if s:
        await s.delete()


async def logout_current_session(request: Request, response: Response) -> None:
    access_cookie = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    refresh_cookie = request.cookies.get(settings.REFRESH_COOKIE_NAME)

    if not access_cookie and not refresh_cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if refresh_cookie:
        payload = decode_jwt_token(refresh_cookie)
        if payload.get("type") != TokenType.REFRESH or not isinstance(
            payload.get("jti"), str
        ):
            raise HTTPException(status_code=401, detail="Invalid token")
        await revoke_session_by_jti(payload["jti"])
    else:
        payload = decode_jwt_token(access_cookie)  # type: ignore[arg-type]
        if payload.get("type") != TokenType.ACCESS:
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            user_id = PydanticObjectId(payload["sub"])
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid subject in token")

        await revoke_all_sessions(user_id)

    clear_auth_cookies(response)

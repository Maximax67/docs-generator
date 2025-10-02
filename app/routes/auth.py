from datetime import timedelta
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.enums import TokenType
from app.models.auth import (
    LoginRequest,
    PasswordForgotRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    RegisterRequest,
    EmailChangeRequest,
)
from app.models.common_responses import DetailResponse
from app.models.database import User
from app.services.auth import (
    clear_auth_cookies,
    create_jwt_token,
    decode_jwt_token,
    hash_password,
    logout_current_session,
    issue_token_pair,
    revoke_all_sessions,
    rotate_refresh_token,
    send_verification_email,
    set_auth_cookies,
    verify_password,
)
from app.services.email import (
    render_reset_password_email,
    send_email,
)
from app.settings import settings
from app.dependencies import get_current_user
from app.limiter import limiter


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=DetailResponse,
    responses={
        400: {
            "description": "Bad request",
            "content": {"application/json": {"example": {"detail": "Bad request"}}},
        },
        409: {
            "description": "Email already registered",
            "content": {
                "application/json": {"example": {"detail": "Email already registered"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def register(
    request: Request, response: Response, body: RegisterRequest
) -> DetailResponse:
    existing = await User.find_one(User.email == body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        password_hash=hash_password(body.password),
        email_verified=False,
    )
    user = await user.create()

    await send_verification_email(user)

    try:
        await logout_current_session(request, response)
    except Exception:
        pass

    access, refresh, expires_in = await issue_token_pair(user, body.session_name)
    set_auth_cookies(response, access, refresh, expires_in)

    return DetailResponse(detail="Registered and logged in")


@router.post(
    "/login",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Invalid credentials",
            "content": {
                "application/json": {"example": {"detail": "Invalid credentials"}}
            },
        },
        403: {
            "description": "User is banned",
            "content": {"application/json": {"example": {"detail": "User is banned"}}},
        },
    },
)
@limiter.limit("5/minute")
async def login(
    request: Request, response: Response, body: LoginRequest
) -> DetailResponse:
    user = await User.find_one(User.email == body.email)
    if (
        not user
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")

    # Invalidate any current session and clear cookies (best-effort)
    try:
        await logout_current_session(request, response)
    except Exception:
        pass

    access, refresh, expires_in = await issue_token_pair(user, body.session_name)
    set_auth_cookies(response, access, refresh, expires_in)

    return DetailResponse(detail="Logged in")


@router.post(
    "/logout",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Not authenticated or invalid token",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        }
    },
)
@limiter.limit("5/minute")
async def logout(request: Request, response: Response) -> DetailResponse:
    await logout_current_session(request, response)
    clear_auth_cookies(response)

    return DetailResponse(detail="Logged out")


@router.post(
    "/logout_all",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
    },
)
@limiter.limit("2/minute")
async def logout_all(
    request: Request, response: Response, current_user: User = Depends(get_current_user)
) -> DetailResponse:
    await revoke_all_sessions(current_user.id)  # type: ignore[arg-type]
    clear_auth_cookies(response)

    return DetailResponse(detail="All sessions terminated")


@router.post(
    "/refresh",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Invalid refresh token",
            "content": {
                "application/json": {"example": {"detail": "Invalid refresh token"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def refresh(request: Request, response: Response) -> DetailResponse:
    # Read refresh token only from cookies
    raw_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    payload = decode_jwt_token(raw_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")

    jti = payload.get("jti")
    if not isinstance(jti, str):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access, refresh, expires_in = await rotate_refresh_token(user_id, jti)
    set_auth_cookies(response, access, refresh, expires_in)

    return DetailResponse(detail="Refreshed")


@router.get(
    "/me",
    response_model=User,
    responses={
        401: {
            "description": "Not authenticated or invalid access token",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        404: {
            "description": "User not found",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
@limiter.limit("5/minute")
async def me(
    request: Request, response: Response, current_user: User = Depends(get_current_user)
) -> User:
    return current_user


@router.post(
    "/email/send-confirmation",
    response_model=DetailResponse,
    responses={
        400: {
            "description": "No email on account",
            "content": {
                "application/json": {"example": {"detail": "No email on account"}}
            },
        },
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        409: {
            "description": "Email already verified",
            "content": {
                "application/json": {"example": {"detail": "Email already verified"}}
            },
        },
    },
)
@limiter.limit("1/minute")
async def email_send_confirmation(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    if not current_user.email:
        raise HTTPException(status_code=400, detail="No email on account")

    if current_user.email_verified:
        raise HTTPException(status_code=409, detail="Email already verified")

    await send_verification_email(current_user)
    return DetailResponse(detail="Verification email sent")


@router.post(
    "/email/verify",
    response_model=DetailResponse,
    responses={
        400: {
            "description": "Missing or invalid token",
            "content": {"application/json": {"example": {"detail": "Missing token"}}},
        },
        404: {
            "description": "User not found",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
@limiter.limit("5/minute")
async def verify_email(
    request: Request,
    response: Response,
    token: Optional[str] = None,
) -> DetailResponse:
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    payload = decode_jwt_token(token)
    if payload.get("type") != TokenType.VERIFY_EMAIL:
        raise HTTPException(status_code=400, detail="Invalid token type")
    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject in token")

    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        return DetailResponse(detail="Email already verified")

    user.email_verified = True
    await user.save()

    return DetailResponse(detail="Email verified")


@router.post(
    "/email/change",
    response_model=DetailResponse,
    responses={
        400: {
            "description": "New email is required or no change",
            "content": {
                "application/json": {
                    "examples": {
                        "required": {
                            "summary": "Missing email",
                            "value": {"detail": "New email is required"},
                        },
                        "no_change": {
                            "summary": "Same email",
                            "value": {"detail": "New email must differ from current"},
                        },
                    }
                }
            },
        },
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def email_change(
    request: Request,
    response: Response,
    body: EmailChangeRequest,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    new_email = body.new_email
    if not new_email:
        raise HTTPException(status_code=400, detail="New email is required")

    if current_user.email and current_user.email.lower() == new_email.lower():
        raise HTTPException(
            status_code=400, detail="New email must differ from current"
        )

    current_user.email = new_email
    current_user.email_verified = False
    await current_user.save()

    await send_verification_email(current_user)

    return DetailResponse(detail="Email updated. Verification sent")


@router.post(
    "/password/forgot",
    response_model=DetailResponse,
)
@limiter.limit("1/minute")
async def password_forgot(
    request: Request, response: Response, body: PasswordForgotRequest
) -> DetailResponse:
    user = await User.find_one(User.email == body.email)
    if not user:
        # Do not reveal whether the email exists
        return DetailResponse(detail="If the email exists, a reset link has been sent")

    token = create_jwt_token(
        subject=str(user.id),
        token_type=TokenType.PASSWORD_RESET,
        expires_delta=timedelta(hours=1),
    )
    url = f"{settings.API_URL}/auth/password/change?token={token}"
    html = render_reset_password_email(user.first_name or user.email, url)

    await send_email(user.email, "Password reset", html)

    return DetailResponse(detail="If the email exists, a reset link has been sent")


@router.post(
    "/password/reset",
    response_model=DetailResponse,
    responses={
        400: {
            "description": "Missing or invalid token",
            "content": {
                "application/json": {
                    "examples": {
                        "missing": {
                            "summary": "Missing token",
                            "value": {"detail": "Missing token"},
                        },
                        "invalid_type": {
                            "summary": "Invalid token type",
                            "value": {"detail": "Invalid token type"},
                        },
                        "invalid_subject": {
                            "summary": "Invalid subject in token",
                            "value": {"detail": "Invalid subject in token"},
                        },
                    }
                }
            },
        },
        404: {
            "description": "User not found",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
@limiter.limit("5/minute")
async def password_reset(
    request: Request, response: Response, token: str, body: PasswordResetRequest
) -> DetailResponse:
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    payload = decode_jwt_token(token)
    if payload.get("type") != TokenType.PASSWORD_RESET:
        raise HTTPException(status_code=400, detail="Invalid token type")
    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject in token")

    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        return DetailResponse(detail="Email already verified")

    user.password_hash = hash_password(body.new_password)
    await user.save()

    await revoke_all_sessions(user.id)  # type: ignore[arg-type]
    clear_auth_cookies(response)

    return DetailResponse(detail="Password reset")


@router.post(
    "/password/change",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Invalid old password or user not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid old password or user not found"}
                }
            },
        },
    },
)
@limiter.limit("5/minute")
async def password_change(
    request: Request, response: Response, body: PasswordChangeRequest
) -> DetailResponse:
    user = await User.find_one(User.email == body.email)
    if (
        not user
        or not user.password_hash
        or not verify_password(body.old_password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401, detail="Invalid old password or user not found"
        )

    user.password_hash = hash_password(body.new_password)
    await user.save()

    await revoke_all_sessions(user.id)  # type: ignore[arg-type]
    clear_auth_cookies(response)

    return DetailResponse(detail="Password updated")

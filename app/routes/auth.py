from datetime import timedelta
from secrets import token_urlsafe
from urllib.parse import urljoin

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.enums import TokenType
from app.schemas.auth import (
    LoginRequest,
    PasswordForgotRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    RegisterRequest,
    EmailChangeRequest,
    SessionInfo,
)
from app.schemas.common_responses import DetailResponse
from app.db.database import User, Session
from app.services.auth import (
    clear_auth_cookies,
    create_jwt_token,
    decode_jwt_token,
    hash_password,
    logout_current_session,
    issue_token_pair,
    revoke_all_sessions,
    revoke_session_by_jti,
    rotate_refresh_token,
    send_verification_email,
    set_auth_cookies,
    verify_password,
)
from app.services.email import send_email
from app.settings import settings
from app.dependencies import get_current_user
from app.limiter import limiter
from app.services.bloom_filter import bloom_filter
from app.utils import get_session_name_from_user_agent


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

    session_name = get_session_name_from_user_agent(request)
    access, refresh, expires_in, refresh_expires_in = await issue_token_pair(
        user, session_name
    )
    set_auth_cookies(response, access, refresh, expires_in, refresh_expires_in)

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

    try:
        await logout_current_session(request, response)
    except Exception:
        pass

    session_name = get_session_name_from_user_agent(request)
    access, refresh, expires_in, refresh_expires_in = await issue_token_pair(
        user, session_name
    )
    set_auth_cookies(response, access, refresh, expires_in, refresh_expires_in)

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


@router.get(
    "/sessions",
    response_model=list[SessionInfo],
    responses={
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def list_sessions(
    request: Request, response: Response, current_user: User = Depends(get_current_user)
) -> list[SessionInfo]:
    current_jti: str | None = None
    access_cookie = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if access_cookie:
        try:
            payload = decode_jwt_token(access_cookie)
            current_jti = payload["jti"]
        except Exception:
            current_jti = None

    sessions = await Session.find(
        Session.user.id  # pyright: ignore[reportAttributeAccessIssue]
        == current_user.id
    ).to_list()
    result: list[SessionInfo] = []
    for s in sessions:
        result.append(
            SessionInfo(
                id=s.id,  # type: ignore[arg-type]
                name=s.name,
                created_at=s.created_at,
                updated_at=s.updated_at,
                current=(current_jti is not None and s.access_jti == current_jti),
            )
        )

    return result


@router.delete(
    "/sessions/{session_id}",
    response_model=DetailResponse,
    responses={
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        404: {
            "description": "Session not found",
            "content": {
                "application/json": {"example": {"detail": "Session not found"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def revoke_session(
    session_id: PydanticObjectId,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    s = await Session.find_one(Session.id == session_id, fetch_links=True)
    if (
        not s
        or s.user.id != current_user.id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        raise HTTPException(status_code=404, detail="Session not found")

    access_cookie = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if access_cookie:
        try:
            payload = decode_jwt_token(access_cookie)
            current_jti = payload["jti"]
        except Exception:
            current_jti = None

    await revoke_session_by_jti(s.refresh_jti)
    bloom_filter.add(s.access_jti)

    if not current_jti or s.access_jti == current_jti:
        clear_auth_cookies(response)

    return DetailResponse(detail="Session revoked")


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
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    payload = decode_jwt_token(refresh_token)
    if payload.get("type") != TokenType.REFRESH:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        user_id = PydanticObjectId(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid subject in token")

    jti_refresh = payload.get("jti")
    if not isinstance(jti_refresh, str):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access_token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if access_token:
        try:
            access_payload = decode_jwt_token(access_token)
            if access_payload.get("type") == TokenType.ACCESS:
                bloom_filter.add(access_payload["jti"])
        except Exception:
            pass

    session_name = get_session_name_from_user_agent(request)
    access, refresh, expires_in, refresh_expires_in = await rotate_refresh_token(
        user_id, jti_refresh, session_name
    )
    set_auth_cookies(response, access, refresh, expires_in, refresh_expires_in)

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
@limiter.limit("10/minute")
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
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    response: Response,
    token: str | None = None,
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

    if payload.get("email") != user.email or payload.get("jti") in bloom_filter:
        raise HTTPException(status_code=401, detail="Invalid token")

    if user.email_verified:
        raise HTTPException(status_code=409, detail="Email already verified")

    user.email_verified = True
    await user.save_changes()

    bloom_filter.add(payload["jti"])

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
    await current_user.save_changes()

    await send_verification_email(current_user)
    await revoke_all_sessions(current_user.id)  # type: ignore[arg-type]
    clear_auth_cookies(response)

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
        return DetailResponse(detail="If the email exists, a reset link has been sent")

    token = create_jwt_token(
        subject=str(user.id),
        token_type=TokenType.PASSWORD_RESET,
        expires_delta=timedelta(hours=1),
        jti=token_urlsafe(32),
    )
    url = urljoin(str(settings.FRONTEND_URL), f"/reset-password?token={token}")

    await send_email(
        user.email,  # pyright: ignore
        "Password reset",
        "reset",
        user.first_name,
        url,
    )

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
    await user.save_changes()

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
    await user.save_changes()

    await revoke_all_sessions(user.id)  # type: ignore[arg-type]
    clear_auth_cookies(response)

    return DetailResponse(detail="Password updated")

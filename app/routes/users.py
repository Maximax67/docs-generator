from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pymongo import ReturnDocument
from beanie import PydanticObjectId

from app.enums import UserRole, UserStatus
from app.limiter import limiter
from app.schemas.common_responses import DetailResponse, Paginated
from app.schemas.users import (
    UserResponse,
    UserUpdateRequest,
    UserCreateRequest,
    UserBatchCreateRequest,
)
from app.services.auth import clear_auth_cookies, hash_password
from app.services.users import update_user_bool_field
from app.services.bloom_filter import bloom_filter
from app.schemas.auth import AuthorizedUser
from app.models import Generation, Session, User
from app.dependencies import (
    authorize_user_or_admin,
    require_admin,
    require_god,
)
from app.utils.paginate import paginate


router = APIRouter(prefix="/users", tags=["users"])

common_responses: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "User not found",
        "content": {"application/json": {"example": {"detail": "User not found"}}},
    },
    403: {
        "description": "Forbidden",
        "content": {"application/json": {"example": {"detail": "Forbidden"}}},
    },
    401: {
        "description": "Unauthorized",
        "content": {"application/json": {"example": {"detail": "Invalid token"}}},
    },
}


@router.get(
    "",
    response_model=Paginated[UserResponse],
    responses={403: common_responses[403]},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("20/minute")
async def get_all_users(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    q: str | None = Query(None, description="Search query for name or email"),
    role: UserRole | None = Query(None, description="Filter by role"),
    status: UserStatus | None = Query(None, description="Filter by status"),
) -> Paginated[User]:
    query = User.find_all()

    # TODO: Replace to more efficient approach
    if q:
        terms = [term for term in q.strip().lower().split() if term]
        query = query.find(
            {
                "$and": [
                    {
                        "$or": [
                            {"first_name": {"$regex": term, "$options": "i"}},
                            {"last_name": {"$regex": term, "$options": "i"}},
                            {"email": {"$regex": term, "$options": "i"}},
                        ]
                    }
                    for term in terms
                ]
            }
        )

    if role:
        query = query.find({"role": role})

    if status:
        if status == "banned":
            query = query.find({"is_banned": True})
        elif status == "active":
            query = query.find({"is_banned": False})

    users, meta = await paginate(query, page, page_size)

    return Paginated(
        data=users,
        meta=meta,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={
        409: {
            "description": "User with this email already exists",
            "content": {
                "application/json": {
                    "example": {"detail": "User with this email already exists"}
                }
            },
        },
        401: common_responses[401],
        403: common_responses[403],
    },
    dependencies=[Depends(require_god)],
)
@limiter.limit("5/minute")
async def create_user(
    request: Request, response: Response, user_data: UserCreateRequest
) -> User:
    existing = await User.find_one(User.email == user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    user_dict = user_data.model_dump(exclude_unset=True, exclude={"password"})
    user = User(**user_dict, password_hash=hash_password(user_data.password))

    return await user.create()


@router.post(
    "/batch",
    status_code=status.HTTP_201_CREATED,
    response_model=DetailResponse,
    responses={
        400: {
            "description": "Invalid request - validation failed or duplicate emails in request",
            "content": {
                "application/json": {
                    "example": {"detail": "Duplicate emails in request"}
                }
            },
        },
        409: {
            "description": "One or more users already exist",
            "content": {
                "application/json": {
                    "example": {"detail": "One or more users already exist"}
                }
            },
        },
        401: common_responses[401],
        403: common_responses[403],
    },
    dependencies=[Depends(require_god)],
)
@limiter.limit("2/minute")
async def create_users_batch(
    request: Request, response: Response, batch_data: UserBatchCreateRequest
) -> DetailResponse:
    if not batch_data.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No users provided",
        )

    emails = [user.email for user in batch_data.users]
    if len(emails) != len(set(emails)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate emails in request",
        )

    existing_users = await User.find({"email": {"$in": emails}}).to_list()
    if existing_users:
        existing_emails = [user.email for user in existing_users]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Users with these emails already exist: {', '.join(existing_emails)}",
        )

    users_to_create: list[User] = []

    for user_data in batch_data.users:
        user_dict = user_data.model_dump(exclude_unset=True, exclude={"password"})
        user = User(**user_dict, password_hash=hash_password(user_data.password))
        users_to_create.append(user)

    await User.insert_many(users_to_create)

    return DetailResponse(detail=f"Created {len(users_to_create)} users")


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses=common_responses,
    dependencies=[Depends(authorize_user_or_admin)],
)
@limiter.limit("10/minute")
async def get_user(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
) -> User:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def update_user(
    user_id: PydanticObjectId,
    user_update: UserUpdateRequest,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_admin),
) -> User:
    if (
        not authorized_user.is_email_verified
        and not authorized_user.role == UserRole.ADMIN
        and not authorized_user.role == UserRole.GOD
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    if authorized_user.role == UserRole.USER:
        if any(
            field is not None
            for field in (
                user_update.email,
                user_update.is_banned,
            )
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    if authorized_user.role != UserRole.GOD and authorized_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc)
    updated_user: User | None = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$set": {**user_update.model_dump(exclude_unset=True), "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


@router.delete(
    "/{user_id}",
    response_model=DetailResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_user(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_admin),
) -> DetailResponse:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if authorized_user.user_id != user_id and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    async for session in Session.find(
        Session.user.id == user_id  # type: ignore[attr-defined]
    ):
        bloom_filter.add(session.access_jti)

    await Session.find(
        Session.user.id == user_id  # type: ignore[attr-defined]
    ).delete()
    await Generation.find(Generation.user.id == user_id).delete()  # type: ignore
    await user.delete()

    if authorized_user.user_id == user_id:
        clear_auth_cookies(response)

    return DetailResponse(detail="User deleted")


@router.post(
    "/{user_id}/ban",
    response_model=UserResponse,
    responses={
        **common_responses,
        409: {
            "description": "User is already banned",
            "content": {
                "application/json": {"example": {"detail": "User is already banned"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def ban_user(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> User:
    return await update_user_bool_field(
        user_id, authorized_user, "is_banned", True, "User is already banned"
    )


@router.post(
    "/{user_id}/unban",
    response_model=UserResponse,
    responses={
        **common_responses,
        409: {
            "description": "User is not banned",
            "content": {
                "application/json": {"example": {"detail": "User is not banned"}}
            },
        },
    },
)
@limiter.limit("5/minute")
async def unban_user(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> User:
    return await update_user_bool_field(
        user_id, authorized_user, "is_banned", False, "User is not banned"
    )


@router.post(
    "/{user_id}/email/verify",
    response_model=UserResponse,
    responses={
        **common_responses,
        409: {
            "description": "User email is already verified",
            "content": {
                "application/json": {
                    "example": {"detail": "User email is already verified"}
                }
            },
        },
    },
)
@limiter.limit("5/minute")
async def verify_email(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> User:
    return await update_user_bool_field(
        user_id,
        authorized_user,
        "email_verified",
        True,
        "User email is already verified",
    )


@router.post(
    "/{user_id}/email/revoke-verification",
    response_model=UserResponse,
    responses={
        **common_responses,
        409: {
            "description": "User email is not verified",
            "content": {
                "application/json": {
                    "example": {"detail": "User email is not verified"}
                }
            },
        },
    },
)
@limiter.limit("5/minute")
async def revoke_email_verification(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> User:
    return await update_user_bool_field(
        user_id,
        authorized_user,
        "email_verified",
        False,
        "User email is not verified",
    )

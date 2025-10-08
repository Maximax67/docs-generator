from typing import Any, Dict, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from beanie import PydanticObjectId

from app.enums import UserRole
from app.limiter import limiter
from app.models.common_responses import DetailResponse
from app.models.users import AllUsersResponse, UserUpdateRequest
from app.services.auth import clear_auth_cookies
from app.services.bloom_filter import bloom_filter
from app.services.variables import validate_user_variable, validate_user_variables
from app.settings import settings
from app.models.auth import AuthorizedUser
from app.models.database import Result, Session, User
from app.dependencies import (
    authorize_user_or_admin,
    authorize_user_or_god,
    require_admin,
    require_god,
)
from app.utils import (
    update_user_bool_field,
    validate_saved_variables_count,
    validate_variable_name,
    validate_variable_value,
)


router = APIRouter(prefix="/users", tags=["users"])

common_responses: Dict[Union[int, str], Dict[str, Any]] = {
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
    response_model=AllUsersResponse,
    responses={403: common_responses[403]},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def get_all_users(request: Request, response: Response) -> AllUsersResponse:
    users = await User.find_all().to_list()

    return AllUsersResponse(users=users)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=User,
    responses={
        409: {
            "description": "User with this id or telegram id already exists",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "User with this id or telegram id already exists"
                    }
                }
            },
        },
        401: common_responses[401],
        403: common_responses[403],
    },
    dependencies=[Depends(require_god)],
)
@limiter.limit("5/minute")
async def create_user(request: Request, response: Response, user: User) -> User:
    validate_saved_variables_count(len(user.saved_variables))

    try:
        return await user.create()
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this id or telegram id already exists",
        )


@router.get(
    "/{user_id}",
    response_model=User,
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


@router.patch("/{user_id}", response_model=User, responses=common_responses)
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
                user_update.telegram_id,
                user_update.telegram_username,
            )
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    if authorized_user.role != UserRole.GOD and authorized_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if user_update.saved_variables:
        validate_saved_variables_count(len(user_update.saved_variables))

    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$set": user_update.model_dump(exclude_unset=True)},
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

    async for session in Session.find(Session.user.id == user_id):
        bloom_filter.add(session.access_jti)

    await Session.find(Session.user.id == user_id).delete()
    await Result.find(Result.user.id == user_id).delete()
    await user.delete()

    if authorized_user.user_id == user_id:
        clear_auth_cookies(response)

    return DetailResponse(detail="User deleted")


@router.delete(
    "/{user_id}/generations",
    response_model=DetailResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_user_generated_documents(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_admin),
) -> DetailResponse:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        user.role == UserRole.ADMIN or user.role == UserRole.GOD
    ) and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await Result.find(Result.user.id == user.id).delete()
    if not result:
        raise HTTPException(status_code=404, detail="Generations not found")

    return DetailResponse(detail=f"Deleted: {result.deleted_count}")


@router.get(
    "/{user_id}/saved_variables",
    response_model=Dict[str, str],
    responses=common_responses,
    dependencies=[Depends(authorize_user_or_admin)],
)
@limiter.limit("5/minute")
async def get_saved_variables(
    user_id: PydanticObjectId, request: Request, response: Response
) -> Dict[str, str]:
    user: Optional[User] = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user.saved_variables


@router.put(
    "/{user_id}/saved_variables",
    response_model=User,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def update_saved_variables(
    user_id: PydanticObjectId,
    saved_variables: Dict[str, str],
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_god),
) -> Union[User, JSONResponse]:
    if (
        not authorized_user.is_email_verified
        and not authorized_user.role == UserRole.ADMIN
        and not authorized_user.role == UserRole.GOD
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    validate_saved_variables_count(len(saved_variables))

    for key, value in saved_variables.items():
        validate_variable_name(key)
        validate_variable_value(value)

    errors = validate_user_variables(saved_variables)
    if errors:
        return JSONResponse(
            status_code=422, content={"detail": "Validation failed", "errors": errors}
        )

    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$set": {"saved_variables": saved_variables}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


@router.delete(
    "/{user_id}/saved_variables",
    response_model=User,
    responses=common_responses,
    dependencies=[Depends(authorize_user_or_god)],
)
@limiter.limit("5/minute")
async def delete_saved_variables(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
) -> User:
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$set": {"saved_variables": {}}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


@router.delete(
    "/{user_id}/saved_variables/{variable}",
    response_model=User,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_saved_variable(
    user_id: PydanticObjectId,
    variable: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_god),
) -> User:
    validate_variable_name(variable)
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$unset": {f"saved_variables.{variable}": ""}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


@router.patch(
    "/{user_id}/saved_variables/{variable}",
    response_model=User,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def update_saved_variable(
    user_id: PydanticObjectId,
    variable: str,
    value: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(authorize_user_or_god),
) -> User:
    if (
        not authorized_user.is_email_verified
        and not authorized_user.role == UserRole.ADMIN
        and not authorized_user.role == UserRole.GOD
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    validate_variable_name(variable)
    validate_variable_value(value)

    error = validate_user_variable(variable, value)
    if error:
        raise HTTPException(
            status_code=422,
            detail=error,
        )

    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {
            "_id": user_id,
            "$expr": {
                "$or": [
                    {
                        "$lt": [
                            {"$size": {"$objectToArray": "$saved_variables"}},
                            settings.MAX_SAVED_VARIABLES,
                        ]
                    },
                    {
                        "$in": [
                            variable,
                            {
                                "$map": {
                                    "input": {"$objectToArray": "$saved_variables"},
                                    "as": "kv",
                                    "in": "$$kv.k",
                                }
                            },
                        ]
                    },
                ]
            },
        },
        {"$set": {f"saved_variables.{variable}": value}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    existing_user: Optional[User] = await User.get_pymongo_collection().find_one(
        {"_id": user_id},
        {"_id": 1},
    )
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(
        status_code=422,
        detail=f"Cannot store more than {settings.MAX_SAVED_VARIABLES} variables",
    )


@router.post(
    "/{user_id}/ban",
    response_model=User,
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
    response_model=User,
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
    response_model=User,
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
    response_model=User,
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

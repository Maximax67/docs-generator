from typing import Any, Dict, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from beanie import PydanticObjectId

from app.enums import UserRole
from app.limiter import limiter
from app.models.common_responses import DetailResponse
from app.models.users import AllUsersResponse, UserDocumentsResponse, UserUpdateRequest
from app.services.auth import clear_auth_cookies
from app.settings import settings
from app.models.database import Result, Session, User
from app.dependencies import authorize_user_or_admin, require_admin
from app.utils import (
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
        "content": {"application/json": {"example": {"detail": "Invalid token"}}},
    },
}


@router.get(
    "",
    response_model=AllUsersResponse,
    responses={403: common_responses[403]},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
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
        403: common_responses[403],
    },
    dependencies=[Depends(require_admin)],
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
)
@limiter.limit("5/minute")
async def get_user(
    user_id: PydanticObjectId,
    request: Request,
    response: Response,
    role: UserRole = Depends(authorize_user_or_admin),
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
    role: UserRole = Depends(authorize_user_or_admin),
) -> User:
    if role == UserRole.USER:
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
    role: UserRole = Depends(authorize_user_or_admin),
) -> DetailResponse:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await Result.get_pymongo_collection().delete_many({"user.$id": user.id})
    await Session.get_pymongo_collection().delete_many({"user.$id": user.id})
    await User.get_pymongo_collection().delete_one({"_id": user.id})

    if role == UserRole.USER:
        clear_auth_cookies(response)

    return DetailResponse(detail="User deleted")


@router.get(
    "/{user_id}/documents",
    response_model=UserDocumentsResponse,
    responses=common_responses,
    dependencies=[Depends(authorize_user_or_admin)],
)
@limiter.limit("5/minute")
async def get_user_documents(
    user_id: PydanticObjectId, request: Request, response: Response
) -> UserDocumentsResponse:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    documents = await Result.find(Result.user.id == user.id).to_list()

    return UserDocumentsResponse(documents=documents)


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
    role: UserRole = Depends(authorize_user_or_admin),
) -> User:
    validate_saved_variables_count(len(saved_variables))

    for key, value in saved_variables.items():
        validate_variable_name(key)
        validate_variable_value(value)

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
    dependencies=[Depends(authorize_user_or_admin)],
)
@limiter.limit("5/minute")
async def delete_saved_variables(
    user_id: PydanticObjectId, request: Request, response: Response
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
    dependencies=[Depends(authorize_user_or_admin)],
)
@limiter.limit("5/minute")
async def delete_saved_variable(
    user_id: PydanticObjectId, variable: str, request: Request, response: Response
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
    role: UserRole = Depends(authorize_user_or_admin),
) -> User:
    validate_variable_name(variable)
    validate_variable_value(value)

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

    # Distinguish failure cause

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
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def ban_user(
    user_id: PydanticObjectId, request: Request, response: Response
) -> User:
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id, "is_banned": False},
        {"$set": {"is_banned": True}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    # Either user not found or already banned
    user_exists = await User.find_one(User.id == user_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(status_code=409, detail="User is already banned")


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
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def unban_user(
    user_id: PydanticObjectId, request: Request, response: Response
) -> User:
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id, "is_banned": True},
        {"$set": {"is_banned": False}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    # Either user not found or already unbanned
    user_exists = await User.find_one(User.id == user_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(status_code=409, detail="User is not banned")

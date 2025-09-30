from typing import Any, Dict, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.common_responses import DetailResponse
from app.models.users import AllUsersResponse, UserDocumentsResponse, UserUpdateRequest
from app.settings import settings
from app.models.database import Result, User
from app.dependencies import verify_token
from app.utils import (
    find_and_update_user,
    validate_saved_variables_count,
    validate_variable_name,
    validate_variable_value,
)


router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(verify_token)]
)

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


@router.get("", response_model=AllUsersResponse, responses={403: common_responses[403]})
async def get_all_users() -> AllUsersResponse:
    users = await User.find_all().to_list()

    return AllUsersResponse(users=users)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=User,
    responses={
        409: {
            "description": "User with this telegram_id already exists",
            "content": {
                "application/json": {
                    "example": {"detail": "User with this telegram_id already exists"}
                }
            },
        },
        403: common_responses[403],
    },
)
async def create_user(user: User) -> User:
    validate_saved_variables_count(len(user.saved_variables))

    try:
        return await user.create()
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this telegram_id already exists",
        )


@router.get("/{telegram_id}", response_model=User, responses=common_responses)
async def get_user(telegram_id: int) -> User:
    user = await User.find_one(User.telegram_id == telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.patch("/{telegram_id}", response_model=User, responses=common_responses)
async def update_user(telegram_id: int, user_update: UserUpdateRequest) -> User:
    if user_update.saved_variables:
        validate_saved_variables_count(len(user_update.saved_variables))

    return await find_and_update_user(
        telegram_id, {"$set": user_update.model_dump(exclude_unset=True)}
    )


@router.delete(
    "/{telegram_id}", response_model=DetailResponse, responses=common_responses
)
async def delete_user(telegram_id: int) -> DetailResponse:
    user = await User.find_one(User.telegram_id == telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await Result.get_pymongo_collection().update_many(
        {"user.$id": user.id}, {"$set": {"user": None}}
    )
    await user.delete()

    return DetailResponse(detail="User deleted")


@router.get(
    "/{telegram_id}/documents",
    response_model=UserDocumentsResponse,
    responses=common_responses,
)
async def get_user_documents(telegram_id: int) -> UserDocumentsResponse:
    user = await User.find_one(User.telegram_id == telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    documents = await Result.find(Result.user.id == user.id).to_list()

    return UserDocumentsResponse(documents=documents)


@router.get(
    "/{telegram_id}/saved_variables",
    response_model=Dict[str, str],
    responses=common_responses,
)
async def get_saved_variables(telegram_id: int) -> Dict[str, str]:
    user: Optional[User] = await User.find_one(User.telegram_id == telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user.saved_variables


@router.put(
    "/{telegram_id}/saved_variables", response_model=User, responses=common_responses
)
async def update_saved_variables(
    telegram_id: int, saved_variables: Dict[str, str]
) -> User:
    validate_saved_variables_count(len(saved_variables))

    for key, value in saved_variables.items():
        validate_variable_name(key)
        validate_variable_value(value)

    return await find_and_update_user(
        telegram_id, {"$set": {"saved_variables": saved_variables}}
    )


@router.delete(
    "/{telegram_id}/saved_variables", response_model=User, responses=common_responses
)
async def delete_saved_variables(telegram_id: int) -> User:
    return await find_and_update_user(telegram_id, {"$set": {"saved_variables": {}}})


@router.delete(
    "/{telegram_id}/saved_variables/{variable}",
    response_model=User,
    responses=common_responses,
)
async def delete_saved_variable(telegram_id: int, variable: str) -> User:
    validate_variable_name(variable)
    return await find_and_update_user(
        telegram_id, {"$unset": {f"saved_variables.{variable}": ""}}
    )


@router.patch(
    "/{telegram_id}/saved_variables/{variable}",
    response_model=User,
    responses=common_responses,
)
async def update_saved_variable(telegram_id: int, variable: str, value: str) -> User:
    validate_variable_name(variable)
    validate_variable_value(value)

    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {
            "telegram_id": telegram_id,
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
        {"telegram_id": telegram_id},
        {"_id": 1},
    )
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(
        status_code=422,
        detail=f"Cannot store more than {settings.MAX_SAVED_VARIABLES} variables",
    )


@router.post(
    "/{telegram_id}/ban",
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
async def ban_user(telegram_id: int) -> User:
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"telegram_id": telegram_id, "is_banned": False},
        {"$set": {"is_banned": True}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    # Either user not found or already banned
    user_exists = await User.find_one(User.telegram_id == telegram_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(status_code=409, detail="User is already banned")


@router.post(
    "/{telegram_id}/unban",
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
async def unban_user(telegram_id: int) -> User:
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"telegram_id": telegram_id, "is_banned": True},
        {"$set": {"is_banned": False}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    # Either user not found or already unbanned
    user_exists = await User.find_one(User.telegram_id == telegram_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(status_code=409, detail="User is not banned")

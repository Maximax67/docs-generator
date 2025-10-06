import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from beanie import PydanticObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.services.rules import is_rule_name_valid
from app.settings import settings
from app.services.variables import is_variable_name_valid, is_variable_value_valid
from app.models.auth import AuthorizedUser
from app.models.database import Session, User
from app.enums import UserRole


def validate_variable_name(variable: str) -> None:
    if not is_variable_name_valid(variable):
        raise HTTPException(
            status_code=422, detail=f"Invalid variable name: '{variable}'"
        )


def validate_rule_name(rule: str) -> None:
    if not is_rule_name_valid(rule):
        raise HTTPException(status_code=422, detail=f"Invalid rule name: '{rule}'")


def validate_variable_value(value: str) -> None:
    if not is_variable_value_valid(value):
        raise HTTPException(status_code=422, detail=f"Invalid variable value: '{value}")


def validate_saved_variables_count(variables_count: int) -> None:
    if variables_count > settings.MAX_SAVED_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot store more than {settings.MAX_SAVED_VARIABLES} variables",
        )


def validate_document_generation_request(variables: Dict[str, str]) -> None:
    if len(variables) > settings.MAX_DOCUMENT_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=f"Documents can not have more than {settings.MAX_DOCUMENT_VARIABLES} variables",
        )

    for variable, value in variables.items():
        validate_variable_name(variable)
        validate_variable_value(value)


def validate_document_mime_type(mime_type: str) -> None:
    if mime_type not in DOC_COMPATIBLE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Requested document mime type not supported",
        )


def ensure_folder(mime_type: str) -> None:
    if mime_type != "application/vnd.google-apps.folder":
        raise HTTPException(
            status_code=400,
            detail="The requested resource is not a folder",
        )


async def cleanup_old_sessions() -> None:
    seven_days_ago = datetime.now(timezone.utc) - timedelta(
        days=settings.REFRESH_TOKEN_EXPIRES_DAYS
    )
    await Session.find(Session.updated_at < seven_days_ago).delete()


async def periodic_cleanup(interval_seconds: int = 3600) -> None:
    while True:
        await cleanup_old_sessions()
        await asyncio.sleep(interval_seconds)


async def update_user_bool_field(
    user_id: PydanticObjectId,
    authorized_user: AuthorizedUser,
    field: str,
    value: bool,
    conflict_detail: str,
) -> User:
    collection = User.get_pymongo_collection()

    query = {"_id": user_id, field: not value}
    if authorized_user.role != UserRole.GOD:
        # Non-GOD admins can only modify regular users
        query["role"] = UserRole.USER.value

    updated_user: Optional[User] = await collection.find_one_and_update(
        query,
        {"$set": {field: value}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    user_exists = await User.find_one(User.id == user_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent unauthorized changes to higher-privileged accounts
    if user_exists.role != UserRole.USER and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    raise HTTPException(status_code=409, detail=conflict_detail)

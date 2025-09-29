from typing import Dict, Optional
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.services.rules import is_rule_name_valid
from app.settings import settings
from app.models.database import User
from app.services.variables import is_variable_name_valid, is_variable_value_valid


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


async def find_and_update_user(
    telegram_id: int, update_query: dict, return_document=ReturnDocument.AFTER
):
    updated_user = await User.get_pymongo_collection().find_one_and_update(
        {"telegram_id": telegram_id},
        update_query,
        return_document=return_document,
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


def format_document_user_mention(
    telegram_id: int, first_name: str, last_name: Optional[str], username: Optional[str]
) -> str:
    full_name = f"{first_name} {last_name}" if last_name else first_name
    if username:
        return f"{telegram_id} ({full_name}, @{username})"

    return f"{telegram_id} ({full_name})"

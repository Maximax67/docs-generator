from typing import Dict, List, Optional, Annotated
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.database import Result, User
from app.enums import UserRole
from app.constants import NAME_REGEX


class UserUpdateRequest(BaseModel):
    telegram_id: Optional[int] = None
    email: Optional[EmailStr] = None
    first_name: Optional[
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]]
    ] = None
    last_name: Optional[
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]]
    ] = None
    telegram_username: Optional[
        Annotated[str, Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")]
    ] = None
    saved_variables: Optional[Dict[str, str]] = None
    is_banned: Optional[bool] = None
    role: Optional[UserRole] = None

    @field_validator("first_name", "last_name", "telegram_username", mode="before")
    def strip_whitespace(cls: "UserUpdateRequest", v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @field_validator("first_name", "last_name")
    def validate_name(cls: "UserUpdateRequest", v: Optional[str]) -> Optional[str]:
        if v and not NAME_REGEX.fullmatch(v):
            raise ValueError("Invalid format")

        return v


class AllUsersResponse(BaseModel):
    users: List[User]


class UserDocumentsResponse(BaseModel):
    documents: List[Result]

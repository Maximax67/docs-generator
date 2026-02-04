from datetime import datetime
from typing import Annotated
from beanie import PydanticObjectId
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.enums import UserRole
from app.constants import NAME_REGEX


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    first_name: (
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]] | None
    ) = None
    last_name: (
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]] | None
    ) = None
    is_banned: bool | None = None
    role: UserRole | None = None

    @field_validator("first_name", "last_name", mode="before")
    def strip_whitespace(cls: "UserUpdateRequest", v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("first_name", "last_name")
    def validate_name(cls: "UserUpdateRequest", v: str | None) -> str | None:
        if v and not NAME_REGEX.fullmatch(v):
            raise ValueError("Invalid format")

        return v


class UserResponse(BaseModel):
    id: PydanticObjectId
    email: str
    first_name: str
    last_name: str | None = None
    is_banned: bool
    email_verified: bool
    role: UserRole
    created_at: datetime
    updated_at: datetime


class UserPublicResponse(BaseModel):
    id: PydanticObjectId
    first_name: str
    last_name: str | None = None
    is_banned: bool
    role: UserRole

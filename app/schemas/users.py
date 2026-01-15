from typing import Annotated
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.enums import UserRole
from app.constants import NAME_REGEX


class UserUpdateRequest(BaseModel):
    telegram_id: int | None = None
    email: EmailStr | None = None
    first_name: (
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]] | None
    ) = None
    last_name: (
        Annotated[str, Annotated[str, Field(min_length=1, max_length=32)]] | None
    ) = None
    telegram_username: (
        Annotated[str, Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")]
        | None
    ) = None
    is_banned: bool | None = None
    role: UserRole | None = None

    @field_validator("first_name", "last_name", "telegram_username", mode="before")
    def strip_whitespace(cls: "UserUpdateRequest", v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("first_name", "last_name")
    def validate_name(cls: "UserUpdateRequest", v: str | None) -> str | None:
        if v and not NAME_REGEX.fullmatch(v):
            raise ValueError("Invalid format")

        return v

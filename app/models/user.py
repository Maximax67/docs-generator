from typing import Annotated
from beanie import Indexed
from pydantic import Field

from app.enums import UserRole
from .timestamps import TimestampMixin


class User(TimestampMixin):
    telegram_id: Annotated[int | None, Indexed(unique=True, sparse=True)] = None
    email: Annotated[str | None, Indexed(unique=True, sparse=True)] = None

    first_name: str
    last_name: str | None = None

    telegram_username: str | None = None
    is_banned: bool = False

    password_hash: str | None = Field(default=None, exclude=True)
    email_verified: bool = False
    role: UserRole = UserRole.USER

    class Settings:
        name = "users"
        use_state_management = True
        keep_nulls = False

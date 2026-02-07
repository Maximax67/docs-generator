from typing import Annotated
from beanie import Document, Indexed
from pydantic import Field

from app.enums import UserRole
from .timestamps import TimestampMixin


class User(Document, TimestampMixin):
    email: Annotated[str, Indexed(unique=True)]

    first_name: str
    last_name: str | None = None
    is_banned: bool = False

    password_hash: str
    email_verified: bool = False
    role: UserRole = UserRole.USER

    class Settings:
        name = "users"
        use_state_management = True
        keep_nulls = False

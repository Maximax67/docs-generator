from typing import Annotated
from beanie import Document, Indexed, Link

from .timestamps import TimestampMixin
from .user import User


class Session(Document, TimestampMixin):
    user: Annotated[Link[User], Indexed()]
    refresh_jti: Annotated[str, Indexed(unique=True)]
    access_jti: str
    name: str | None = None

    class Settings:
        name = "sessions"
        use_state_management = True
        keep_nulls = False

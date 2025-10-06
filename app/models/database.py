from datetime import datetime, timezone
from typing import Annotated, Dict, Optional
from beanie import (
    Document,
    Indexed,
    Insert,
    Link,
    Replace,
    SaveChanges,
    Update,
    before_event,
)
from pydantic import Field
from app.enums import UserRole


class Feedback(Document):
    user_id: int
    user_message_id: int
    admin_message_id: int

    class Settings:
        name = "feedback"
        indexes = [
            "admin_message_id",
            [("user_id", 1), ("user_message_id", 1)],
        ]


class BaseDocument(Document):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Insert)
    def set_created_at(self) -> None:
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    @before_event(Replace, SaveChanges, Update)
    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        use_state_management = True


class PinnedFolder(BaseDocument):
    folder_id: Annotated[str, Indexed(unique=True)]

    class Settings:
        name = "pinned_folders"
        use_state_management = True


class User(BaseDocument):
    telegram_id: Annotated[Optional[int], Indexed(unique=True, sparse=True)] = None
    email: Annotated[Optional[str], Indexed(unique=True, sparse=True)] = None

    first_name: str
    last_name: Optional[str] = None

    telegram_username: Optional[str] = None
    saved_variables: Dict[str, str] = {}
    is_banned: bool = False

    password_hash: Optional[str] = Field(default=None, exclude=True)
    email_verified: bool = False
    role: UserRole = UserRole.USER

    class Settings:
        name = "users"
        use_state_management = True
        keep_nulls = False


class Result(BaseDocument):
    user: Optional[Link[User]] = None
    template_id: str
    variables: Dict[str, str] = {}

    class Settings:
        name = "results"
        use_state_management = True
        keep_nulls = False


class Session(BaseDocument):
    user: Link[User]
    refresh_jti: Annotated[str, Indexed(unique=True)]
    access_jti: str
    name: Optional[str] = None

    class Settings:
        name = "sessions"
        use_state_management = True
        keep_nulls = False
        indexes = [
            [("user", 1)],
        ]

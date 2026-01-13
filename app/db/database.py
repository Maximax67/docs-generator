from datetime import datetime, timezone
from typing import Annotated, Any
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
from pymongo import IndexModel
from app.enums import DocumentResponseFormat, UserRole


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
    telegram_id: Annotated[int | None, Indexed(unique=True, sparse=True)] = None
    email: Annotated[str | None, Indexed(unique=True, sparse=True)] = None

    first_name: str
    last_name: str | None = None

    telegram_username: str | None = None
    saved_variables: dict[str, Any] = {}
    is_banned: bool = False

    password_hash: str | None = Field(default=None, exclude=True)
    email_verified: bool = False
    role: UserRole = UserRole.USER

    class Settings:
        name = "users"
        use_state_management = True
        keep_nulls = False


class Variable(BaseDocument):
    variable: str
    allow_save: bool = Field(default=False)
    scope: str | None = None
    created_by: Link[User] | None = None
    updated_by: Link[User] | None = None
    scheme: dict[str, Any] | None = None

    class Settings:
        name = "variables"
        use_state_management = True
        indexes = [
            IndexModel(
                [
                    ("variable", 1),
                    ("scope", 1),
                ],
                unique=True,
            ),
        ]


class SavedVariable(BaseDocument):
    user: Annotated[Link[User], Indexed()]
    variable: Link[Variable]
    value: Any

    class Settings:
        name = "saved_variables"
        use_state_management = True
        indexes = [
            [("user", 1), ("variable", 1)],
        ]


class Result(BaseDocument):
    user: Annotated[Link[User] | None, Indexed(sparse=True)] = None
    template_id: str
    template_name: str
    variables: dict[str, Any] = {}
    format: DocumentResponseFormat = DocumentResponseFormat.PDF

    class Settings:
        name = "results"
        use_state_management = True
        keep_nulls = False


class Session(BaseDocument):
    user: Annotated[Link[User], Indexed()]
    refresh_jti: Annotated[str, Indexed(unique=True)]
    access_jti: str
    name: str | None = None

    class Settings:
        name = "sessions"
        use_state_management = True
        keep_nulls = False

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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

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


class User(BaseDocument):
    telegram_id: Annotated[int, Indexed(unique=True)]
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    saved_variables: Dict[str, str] = {}
    is_banned: bool = False

    class Settings:
        name = "users"


class Result(BaseDocument):
    user: Optional[Link[User]] = None
    template_id: str
    variables: Dict[str, str] = {}
    telegram_message_id: int

    class Settings:
        name = "results"

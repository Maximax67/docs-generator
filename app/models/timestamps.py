from datetime import datetime, timezone
from beanie import (
    Insert,
    Replace,
    SaveChanges,
    Update,
    before_event,
)
from pydantic import Field


class TimestampMixin:
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Insert)
    def set_created_at(self) -> None:
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    @before_event(Replace, SaveChanges, Update)
    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

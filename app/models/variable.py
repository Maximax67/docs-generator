from typing import Any
from beanie import Document, Link
from pydantic import Field
from pymongo import IndexModel

from .timestamps import TimestampMixin
from .user import User


class Variable(Document, TimestampMixin):
    variable: str
    allow_save: bool = Field(default=False)
    scope: str | None = None
    required: bool
    created_by: Link[User] | None = None
    updated_by: Link[User] | None = None
    validation_schema: dict[str, Any] | None = None
    value: Any | None = None

    class Settings:
        name = "variables"
        use_state_management = True
        keep_nulls = False
        indexes = [
            "scope",
            IndexModel(
                [
                    ("variable", 1),
                    ("scope", 1),
                ],
                unique=True,
            ),
        ]

from typing import Annotated
from beanie import Document, Indexed, Link
from pydantic import BaseModel, Field

from app.enums import AccessLevel
from .timestamps import TimestampMixin
from .user import User


class ScopeRestrictions(BaseModel):
    access_level: AccessLevel = Field(
        default=AccessLevel.ANY, description="Who can access this scope"
    )
    max_depth: int | None = Field(
        default=None,
        ge=0,
        description="How many levels down access propagates. None = infinite.",
    )


class Scope(Document, TimestampMixin):
    drive_id: Annotated[str, Indexed(unique=True)]
    is_folder: bool
    is_pinned: bool = False

    restrictions: ScopeRestrictions = Field(default_factory=ScopeRestrictions)

    created_by: Link[User] | None = None
    updated_by: Link[User] | None = None

    class Settings:
        name = "scopes"
        use_state_management = True
        keep_nulls = False

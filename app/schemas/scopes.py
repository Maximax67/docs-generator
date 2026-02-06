from datetime import datetime
from beanie import PydanticObjectId
from pydantic import BaseModel, Field

from app.enums import AccessLevel
from app.schemas.google import DriveFile, DriveFolder
from app.schemas.users import UserPublicResponse


class ScopeRestrictionsSchema(BaseModel):
    """Schema for scope restrictions."""

    access_level: AccessLevel = Field(
        default=AccessLevel.ANY, description="Who can access this scope"
    )
    max_depth: int | None = Field(
        default=None,
        ge=0,
        description="How many levels down access propagates. None = infinite.",
    )


class ScopeCreate(BaseModel):
    """Request schema for creating a scope."""

    drive_id: str = Field(..., description="Google Drive item ID")
    is_pinned: bool = Field(default=False, description="Whether to pin this scope")
    restrictions: ScopeRestrictionsSchema = Field(
        default_factory=ScopeRestrictionsSchema,
        description="Access restrictions for this scope",
    )


class ScopeUpdate(BaseModel):
    """Request schema for updating scope restrictions."""

    restrictions: ScopeRestrictionsSchema = Field(
        ..., description="Updated access restrictions"
    )


class ScopeResponse(BaseModel):
    """Response schema for a scope."""

    id: PydanticObjectId
    drive_id: str
    is_folder: bool
    is_pinned: bool
    restrictions: ScopeRestrictionsSchema
    created_by: UserPublicResponse | None
    updated_by: UserPublicResponse | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FolderTree(BaseModel):
    """Tree structure for scopes with access control."""

    folders: list["FolderTree"]
    documents: list[DriveFile]
    current_folder: DriveFolder | None = None


FolderTree.model_rebuild()


class ScopeListResponse(BaseModel):
    """Response containing list of scopes."""

    scopes: list[ScopeResponse]

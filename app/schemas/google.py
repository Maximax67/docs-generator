from datetime import datetime
from pydantic import BaseModel, field_validator

from app.constants import DRIVE_FOLDER_MIME_TYPE


class DriveItem(BaseModel):
    id: str
    name: str
    modified_time: datetime
    created_time: datetime
    web_view_link: str | None = None
    parent: str | None


class DriveFile(DriveItem):
    mime_type: str
    size: int | None

    @field_validator("mime_type")
    def mime_type_cannot_be_folder(cls: "DriveFile", v: str) -> str:
        if v == DRIVE_FOLDER_MIME_TYPE:
            raise ValueError("DriveFile cannot have folder MIME type")

        return v


class DriveFolder(DriveItem):
    mime_type: str = DRIVE_FOLDER_MIME_TYPE

    @field_validator("mime_type")
    def ensure_folder_mime_type(cls: "DriveFolder", v: str) -> str:
        if v != DRIVE_FOLDER_MIME_TYPE:
            raise ValueError(
                f"DriveFolder must have mime_type={DRIVE_FOLDER_MIME_TYPE}"
            )

        return v


class DriveFileListResponse(BaseModel):
    files: list[DriveFile]

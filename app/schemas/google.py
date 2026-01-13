from datetime import datetime
from pydantic import BaseModel


class DriveItem(BaseModel):
    id: str
    name: str
    modified_time: datetime
    created_time: datetime
    web_view_link: str | None = None


class DriveFile(DriveItem):
    mime_type: str
    size: int | None


class DriveFolder(DriveItem):
    is_pinned: bool


class FolderContents(BaseModel):
    folders: list[DriveFolder]
    documents: list[DriveFile]
    current_folder: DriveFolder


class FolderTree(BaseModel):
    folders: list["FolderTree"]
    documents: list[DriveFile]
    current_folder: DriveFolder


FolderTree.model_rebuild()


class FolderTreeResponse(BaseModel):
    tree: list[FolderTree]


class DriveFileListResponse(BaseModel):
    files: list[DriveFile]


class FolderListResponse(BaseModel):
    folders: list[DriveFolder]

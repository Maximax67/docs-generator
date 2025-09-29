from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class DriveFile(BaseModel):
    id: str
    name: str
    modified_time: datetime
    created_time: datetime
    web_view_link: Optional[str] = None
    mime_type: str


class DriveFolder(DriveFile):
    is_trusted: bool


class FolderContents(BaseModel):
    folders: List[DriveFolder]
    documents: List[DriveFile]
    current_folder: DriveFolder


class DriveFileListResponse(BaseModel):
    files: List[DriveFile]


class FolderListResponse(BaseModel):
    folders: List[DriveFolder]

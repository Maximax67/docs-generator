from typing import Annotated
from beanie import Document, Indexed

from .timestamps import TimestampMixin


class PinnedFolder(Document, TimestampMixin):
    folder_id: Annotated[str, Indexed(unique=True)]

    class Settings:
        name = "pinned_folders"
        use_state_management = True

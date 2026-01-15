from typing import Annotated, Any
from beanie import Indexed, Link

from app.enums import DocumentResponseFormat
from .timestamps import TimestampMixin
from .user import User


class Result(TimestampMixin):
    user: Annotated[Link[User] | None, Indexed(sparse=True)] = None
    template_id: str
    template_name: str
    variables: dict[str, Any] = {}
    format: DocumentResponseFormat = DocumentResponseFormat.PDF

    class Settings:
        name = "results"
        use_state_management = True
        keep_nulls = False

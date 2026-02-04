from datetime import datetime
from typing import Any
from beanie import PydanticObjectId
from pydantic import BaseModel

from app.schemas.users import UserResponse
from app.enums import DocumentResponseFormat


class GenerationResponse(BaseModel):
    id: PydanticObjectId
    user: UserResponse | None = None
    template_id: str
    template_name: str
    variables: dict[str, Any] = {}
    format: DocumentResponseFormat = DocumentResponseFormat.PDF
    created_at: datetime
    updated_at: datetime

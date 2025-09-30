from typing import Dict, List, Optional
from pydantic import BaseModel

from app.models.database import Result, User


class UserUpdateRequest(BaseModel):
    telegram_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    saved_variables: Optional[Dict[str, str]] = None
    is_banned: Optional[bool] = None


class AllUsersResponse(BaseModel):
    users: List[User]


class UserDocumentsResponse(BaseModel):
    documents: List[Result]

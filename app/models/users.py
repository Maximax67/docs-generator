from typing import Dict, List, Optional, Annotated
from pydantic import BaseModel, EmailStr, Field

from app.models.database import Result, User
from app.enums import UserRole


class UserUpdateRequest(BaseModel):
    telegram_id: Optional[int] = None
    email: Optional[EmailStr] = None
    first_name: Optional[Annotated[str, Field(min_length=1, max_length=32)]] = None
    last_name: Optional[Annotated[str, Field(min_length=1, max_length=32)]] = None
    telegram_username: Optional[
        Annotated[str, Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")]
    ] = None
    saved_variables: Optional[Dict[str, str]] = None
    is_banned: Optional[bool] = None
    role: Optional[UserRole] = None


class AllUsersResponse(BaseModel):
    users: List[User]


class UserDocumentsResponse(BaseModel):
    documents: List[Result]

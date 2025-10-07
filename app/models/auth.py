from typing import Optional, Annotated
from datetime import datetime
from beanie import PydanticObjectId
from pydantic import BaseModel, EmailStr, Field

from app.enums import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=32)]
    first_name: Annotated[str, Field(min_length=1, max_length=32)]
    last_name: Optional[Annotated[str, Field(min_length=1, max_length=32)]] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=64)]


class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordChangeRequest(BaseModel):
    email: EmailStr
    old_password: Annotated[str, Field(min_length=8, max_length=32)]
    new_password: Annotated[str, Field(min_length=8, max_length=32)]


class PasswordResetRequest(BaseModel):
    new_password: Annotated[str, Field(min_length=8, max_length=32)]


class EmailChangeRequest(BaseModel):
    new_email: EmailStr


class SessionInfo(BaseModel):
    id: PydanticObjectId
    name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    current: bool


class AuthorizedUser(BaseModel):
    user_id: PydanticObjectId
    role: UserRole
    is_email_verified: bool

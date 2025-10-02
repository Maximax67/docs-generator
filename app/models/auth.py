from typing import Optional, Annotated
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=32)]
    first_name: Annotated[str, Field(min_length=1, max_length=32)]
    last_name: Optional[Annotated[str, Field(min_length=1, max_length=32)]] = None
    session_name: Optional[
        Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[\w\- ]+$")]
    ] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=64)]
    session_name: Optional[
        Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[\w\- ]+$")]
    ] = None


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

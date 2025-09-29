from typing import Optional
from pydantic import BaseModel


class ValidationRule(BaseModel):
    name: str
    regex: str
    error_message: Optional[str] = None
    is_valid: bool


class ValidationRequest(BaseModel):
    value: str


class ValidationResult(BaseModel):
    is_valid: bool
    error: Optional[str]

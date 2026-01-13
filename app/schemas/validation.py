from pydantic import BaseModel


class ValidationRule(BaseModel):
    name: str
    regex: str
    error_message: str | None = None
    is_valid: bool


class ValidationRequest(BaseModel):
    value: str


class ValidationResult(BaseModel):
    is_valid: bool
    error: str | None

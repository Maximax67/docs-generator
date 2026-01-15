from typing import Any
from beanie import PydanticObjectId
from pydantic import BaseModel, Field

from app.schemas.google import DriveFile


class DocumentVariable:
    id: PydanticObjectId
    variable: str
    allow_save: bool
    scope: str | None
    required: bool
    schema: dict[str, Any] | None
    value: Any
    saved_value: Any


class DocumentVariables(BaseModel):
    template_variables: list[str]
    variables: list[DocumentVariable]


class GenerateDocumentRequest(BaseModel):
    variables: dict[str, Any] = Field(
        default_factory=dict, description="Variable values for document generation"
    )
    bypass_validation: bool = False


class ValidationErrorsResponse(BaseModel):
    is_valid: bool
    errors: dict[str, str] = Field(default_factory=dict)


class DocumentDetails(BaseModel):
    file: DriveFile
    variables: DocumentVariables

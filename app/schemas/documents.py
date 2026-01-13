from typing import Any
from pydantic import BaseModel
from app.schemas.google import DriveFile
from app.schemas.variables import Variable


class DocumentVariables(BaseModel):
    variables: list[Variable]
    unknown_variables: list[str]
    is_valid: bool


class DocumentDetails(DocumentVariables):
    file: DriveFile


class GenerateDocumentRequest(BaseModel):
    variables: dict[str, Any]


class ValidationErrors(BaseModel):
    errors: dict[str, Any]


class ValidationErrorsResponse(BaseModel):
    errors: dict[str, Any]
    is_valid: bool

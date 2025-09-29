from typing import List, Dict
from pydantic import BaseModel
from app.models.google import DriveFile
from app.models.variables import Variable


class DocumentVariables(BaseModel):
    variables: List[Variable]
    is_valid: bool


class DocumentDetails(BaseModel):
    file: DriveFile
    variables: List[Variable]
    is_valid: bool


class GenerateDocumentRequest(BaseModel):
    variables: Dict[str, str]


class GenerateDocumentForUserRequest(GenerateDocumentRequest):
    user_id: int


class ValidationErrors(BaseModel):
    errors: Dict[str, str]


class ValidationErrorsResponse(BaseModel):
    errors: Dict[str, str]
    is_valid: bool

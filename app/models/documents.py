from typing import List, Dict, Union
from pydantic import BaseModel
from app.models.google import DriveFile
from app.models.variables import ConstantVariable, MultichoiceVariable, PlainVariable


class DocumentVariables(BaseModel):
    variables: List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]
    unknown_variables: List[str]
    is_valid: bool


class DocumentDetails(DocumentVariables):
    file: DriveFile


class GenerateDocumentRequest(BaseModel):
    variables: Dict[str, str]


class GenerateDocumentForUserRequest(GenerateDocumentRequest):
    user_id: int


class ValidationErrors(BaseModel):
    errors: Dict[str, str]


class ValidationErrorsResponse(BaseModel):
    errors: Dict[str, str]
    is_valid: bool

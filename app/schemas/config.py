from pydantic import BaseModel

from app.schemas.google import DriveFile
from app.schemas.validation import ValidationRule
from app.schemas.variables import Variable


class ConfigResponse(BaseModel):
    validation_rules: list[ValidationRule]
    variables: list[Variable]
    file: DriveFile

from typing import List
from pydantic import BaseModel

from app.models.google import DriveFile
from app.models.validation import ValidationRule
from app.models.variables import Variable


class ConfigResponse(BaseModel):
    validation_rules: List[ValidationRule]
    variables: List[Variable]
    file: DriveFile

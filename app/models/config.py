from typing import List, Union
from pydantic import BaseModel

from app.models.google import DriveFile
from app.models.validation import ValidationRule
from app.models.variables import ConstantVariable, MultichoiceVariable, PlainVariable


class ConfigResponse(BaseModel):
    validation_rules: List[ValidationRule]
    variables: List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]
    file: DriveFile

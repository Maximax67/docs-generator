from typing import List, Literal, Optional, Union
from pydantic import BaseModel

from app.enums import VariableType
from app.models.validation import ValidationRule


class BaseVariable(BaseModel):
    variable: str
    name: str
    allow_skip: bool
    allow_save: bool
    type: VariableType


class PlainVariable(BaseVariable):
    type: Literal[VariableType.PLAIN] = VariableType.PLAIN
    validation_rules: List[ValidationRule] = []
    example: Optional[str] = None


class MultichoiceVariable(BaseVariable):
    type: Literal[VariableType.MULTICHOICE] = VariableType.MULTICHOICE
    choices: List[str]


class ConstantVariable(BaseVariable):
    type: Literal[VariableType.CONSTANT] = VariableType.CONSTANT
    value: str


class VariablesResponse(BaseModel):
    variables: List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]

from typing import List, Optional, Union
from pydantic import BaseModel, RootModel

from app.models.validation import ValidationRule


class BaseVariable(BaseModel):
    variable: str
    name: str
    allow_skip: bool
    allow_save: bool
    type: str


class PlainVariable(BaseVariable):
    validation_rules: List[ValidationRule] = []
    example: Optional[str] = None


class MultichoiceVariable(BaseVariable):
    choices: List[str]


class ConstantVariable(BaseVariable):
    value: str


class Variable(RootModel[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]):
    pass


class VariablesResponse(BaseModel):
    variables: List[Variable]

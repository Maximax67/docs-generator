from abc import ABC, abstractmethod
from typing import Any, Literal
from pydantic import BaseModel

from app.enums import ValidationType
from app.schemas.validation import ValidationRule
from app.settings import settings


class BaseVariable(BaseModel, ABC):
    variable: str
    name: str
    nullable: bool
    allow_save: bool
    type: ValidationType

    @abstractmethod
    def get_preivew(self) -> str | list[Any]:
        pass


class PlainVariable(BaseVariable):
    type: Literal[ValidationType.PLAIN] = ValidationType.PLAIN
    validation_rules: list[ValidationRule] = []
    example: str | None = None

    def get_preivew(self) -> str:
        return self.example or settings.DEFAULT_VARIABLE_VALUE


class MultichoiceVariable(BaseVariable):
    type: Literal[ValidationType.MULTICHOICE] = ValidationType.MULTICHOICE
    choices: list[str]

    def get_preivew(self) -> str:
        return self.choices[0] if self.choices else settings.DEFAULT_VARIABLE_VALUE


class ConstantVariable(BaseVariable):
    type: Literal[ValidationType.CONSTANT] = ValidationType.CONSTANT
    value: str

    def get_preivew(self) -> str:
        return self.value


class RowVariable(BaseVariable):
    type: Literal[ValidationType.ROW] = ValidationType.ROW
    variable_names: list[str]
    variables: list["Variable"]
    allow_save: Literal[False] = False

    def get_preivew(self) -> list[Any]:
        return [var.get_preivew() for var in self.variables]


class LoopVariable(BaseVariable):
    type: Literal[ValidationType.LOOP] = ValidationType.LOOP
    variable_names: list[str]
    variables: list["Variable"]
    allow_save: Literal[False] = False

    def get_preivew(self) -> list[Any]:
        return [var.get_preivew() for var in self.variables]


type Variable = PlainVariable | MultichoiceVariable | ConstantVariable | RowVariable | LoopVariable


class VariablesResponse(BaseModel):
    variables: list[Variable]

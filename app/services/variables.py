import re
from typing import List, Optional, Union

from app.settings import settings
from app.models.variables import (
    PlainVariable,
    MultichoiceVariable,
    ConstantVariable,
)
from app.services.config import get_variables_dict
from app.services.rules import validate_value


def is_variable_name_valid(variable: str) -> bool:
    pattern = rf"^\w{{1,{settings.MAX_VARIABLE_NAME}}}$"
    return bool(re.fullmatch(pattern, variable))


def is_variable_value_valid(value: str) -> bool:
    return bool(value) and len(value) < settings.MAX_VARIABLE_VALUE


def get_variables() -> (
    List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]
):
    return list(get_variables_dict().values())


def get_variable(
    name: str,
) -> Optional[Union[PlainVariable, MultichoiceVariable, ConstantVariable]]:
    return get_variables_dict().get(name)


def validate_variable(
    variable: Union[PlainVariable, MultichoiceVariable, ConstantVariable], value: str
) -> Optional[str]:
    if isinstance(variable, ConstantVariable):
        return "Cannot validate constant variable"

    if isinstance(variable, MultichoiceVariable):
        return (
            None
            if value in variable.choices
            else "Value must be one of the allowed choices"
        )

    if isinstance(variable, PlainVariable):
        for rule in variable.validation_rules:
            error = validate_value(rule, value)
            if error:
                return error

        return None

    return "Unknown variable type"

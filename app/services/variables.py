import re
from typing import Any

from app.settings import settings
from app.schemas.variables import (
    LoopVariable,
    PlainVariable,
    MultichoiceVariable,
    ConstantVariable,
    RowVariable,
    Variable,
)
from app.services.config import get_variables_dict
from app.services.rules import validate_value
from app.enums import ValidationType


def is_variable_name_valid(variable: str) -> bool:
    pattern = rf"^\w{{1,{settings.MAX_VARIABLE_NAME}}}$"
    return bool(re.fullmatch(pattern, variable))


def is_variable_value_valid(value: str) -> bool:
    return bool(value) and len(value) < settings.MAX_VARIABLE_VALUE


def get_variables() -> list[Variable]:
    return list(get_variables_dict().values())


def get_variable(name: str) -> Variable | None:
    return get_variables_dict().get(name)


def validate_variable(
    variable: Variable,
    value: str | list[Any] | list[list[Any]],
) -> str | dict[str, Any] | None:
    if isinstance(variable, RowVariable):
        if isinstance(value, str):
            return "Row variables must be a list of values"

        row_errors: dict[str, str | dict[str, Any]] = {}
        for i, item in enumerate(value):
            if len(item) != len(variable.variables):
                row_errors[str(i)] = (
                    f"Not enough row values: {len(item)} provided, {len(variable.variables)} required"
                )
                continue

            item_erorrs: dict[str, Any] = {}
            for j, var in enumerate(variable.variables):
                var_value = item[j]
                if var_value is None:
                    if not var.nullable:
                        item_erorrs[str(j)] = "Skip not allowed"

                    continue

                var_error = validate_variable(var, var_value)
                if var_error:
                    item_erorrs[str(j)] = var_error

            if item_erorrs:
                row_errors[str(i)] = item_erorrs

        if row_errors:
            return row_errors

        return None

    if isinstance(variable, LoopVariable):
        if not isinstance(value, list):
            return "Loop variable must be a list of values"

        temp_row = RowVariable(
            variable="temp",
            name="temp",
            nullable=False,
            allow_save=False,
            type=ValidationType.ROW,
            variable_names=[],
            variables=variable.variables,
        )

        loop_errors: dict[str, Any] = {}
        for i, item in enumerate(value):
            iter_error = validate_variable(temp_row, item)
            if iter_error:
                loop_errors[str(i)] = iter_error

        if loop_errors:
            return loop_errors

        return None

    if not isinstance(value, str):
        return "Variable should be a string"

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


def validate_user_variable(name: str, value: str) -> str | dict[str, Any] | None:
    variable = get_variable(name)
    if not variable:
        return "Unknown variable"

    if variable.type == ValidationType.CONSTANT:
        return "Can not save constant variable"

    if not variable.allow_save:
        return "Saving not allowed"

    if not value:
        return "Value not provided"

    return validate_variable(variable, value)


def validate_user_variables(user_input: dict[str, str]) -> dict[str, Any]:
    errors: dict[str, Any] = {}
    for name, value in user_input.items():
        error = validate_user_variable(name, value)
        if error:
            errors[name] = error

    return errors

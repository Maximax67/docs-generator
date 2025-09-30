from io import BytesIO
from typing import Dict, Optional, Union
from datetime import datetime, timedelta
import re
import pandas as pd

from app.enums import ConfigSheetName, VariableType
from app.services.google_drive import download_file
from app.settings import settings
from app.models.validation import ValidationRule
from app.models.variables import (
    PlainVariable,
    MultichoiceVariable,
    ConstantVariable,
)

_validation_rules: Dict[str, ValidationRule] = {}
_variables: Dict[str, Union[PlainVariable, MultichoiceVariable, ConstantVariable]] = {}
_preview_variables: Dict[str, str] = {}
_last_update_time: Optional[datetime] = None


def _is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def _parse_bool_emoji(value: str) -> bool:
    return value.strip() == "✔️"


def _det_config_dfs() -> Dict[ConfigSheetName, pd.DataFrame]:
    config_content = BytesIO()

    download_file(
        settings.CONFIG_SPREADSHEET_ID,
        config_content,
        export_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    config_content.seek(0)
    file = pd.ExcelFile(config_content)
    config_dfs: Dict[ConfigSheetName, pd.DataFrame] = {}

    for sheet_name in ConfigSheetName:
        df = pd.read_excel(file, sheet_name.value)
        config_dfs[sheet_name] = df

    file.close()

    return config_dfs


def update_cache() -> None:
    global _last_update_time
    global _variables
    global _preview_variables
    global _validation_rules

    now = datetime.now()
    config_dfs = _det_config_dfs()

    validation_df = config_dfs[ConfigSheetName.VALIDATION]
    rules: Dict[str, ValidationRule] = {}

    for _, row in validation_df.iterrows():
        if pd.isna(row["Name"]) or pd.isna(row["Name"]):
            continue

        name = str(row["Name"])
        regex = str(row["Regex"])
        error_message = (
            str(row["Error message"])
            if len(row) > 4 and not pd.isna(row["Error message"])
            else None
        )

        rules[name] = ValidationRule(
            name=name,
            regex=regex,
            error_message=error_message,
            is_valid=_is_valid_regex(regex),
        )

    variables: Dict[
        str, Union[PlainVariable, MultichoiceVariable, ConstantVariable]
    ] = {}

    variables_df = config_dfs[ConfigSheetName.VARIABLES]
    for _, row in variables_df.iterrows():
        variable_name = row["Variable"]
        if pd.isna(variable_name):
            continue

        variable_name = str(variable_name)
        validation_rules = [
            r.strip() for r in str(row["Validation rules"]).split(",") if r.strip()
        ]
        populated_rules = [rules[rule] for rule in validation_rules if rule in rules]

        example = str(row["Preview example"]).strip()
        variables[variable_name] = PlainVariable(
            variable=variable_name,
            name=str(row["Name"]),
            example=example if example else None,
            validation_rules=populated_rules,
            allow_skip=_parse_bool_emoji(str(row["Allow skip"])),
            allow_save=_parse_bool_emoji(str(row["Allow save"])),
            type=VariableType.PLAIN,
        )

    multichoice_df = config_dfs[ConfigSheetName.MULTICHOICE_VARIABLES]
    current_var = None

    for _, row in multichoice_df.iterrows():
        choice = row["Choices"]
        if pd.isna(choice):
            continue

        choice = str(choice).strip()
        variable = row["Variable"]

        if not pd.isna(variable):
            variable = str(variable)
            current_var = variable
            variables[variable] = MultichoiceVariable(
                variable=variable,
                name=str(row["Name"]),
                allow_skip=_parse_bool_emoji(str(row["Allow skip"])),
                allow_save=_parse_bool_emoji(str(row["Allow save"])),
                choices=[choice] if choice else [],
                type=VariableType.MULTICHOICE,
            )
        elif current_var and choice:
            mult_var = variables[current_var]
            if not isinstance(mult_var, MultichoiceVariable):
                raise Exception("Not a Multichoice variable")

            mult_var.choices.append(choice)

    constants_df = config_dfs[ConfigSheetName.CONSTANTS]
    for _, row in constants_df.iterrows():
        name = row["Variable"]
        if pd.isna(name):
            continue

        name = str(name)
        value = str(row["Value"])
        variables[name] = ConstantVariable(
            variable=name,
            name=name,
            value=value,
            allow_skip=False,
            allow_save=False,
            type=VariableType.CONSTANT,
        )

    _validation_rules = rules
    _variables = variables

    _preview_variables = {}
    for key, var in variables.items():
        value = settings.DEFAULT_VARIABLE_VALUE

        if var.type == VariableType.CONSTANT:
            value = var.value
        elif var.type == VariableType.PLAIN:
            if var.example:
                value = var.example
        elif var.type == VariableType.MULTICHOICE:
            if var.choices:
                value = var.choices[0]

        _preview_variables[key] = value

    _last_update_time = now


def update_cache_if_required() -> None:
    now = datetime.now()
    if _last_update_time is None or now - _last_update_time >= timedelta(
        seconds=settings.CONFIG_CACHE_DURATION
    ):
        update_cache()


def get_validation_rules_dict() -> Dict[str, ValidationRule]:
    update_cache_if_required()

    return _validation_rules


def get_variables_dict() -> (
    Dict[str, Union[PlainVariable, MultichoiceVariable, ConstantVariable]]
):
    update_cache_if_required()

    return _variables


def get_preview_variables() -> Dict[str, str]:
    update_cache_if_required()

    return _preview_variables

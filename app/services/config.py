from io import BytesIO
from typing import (
    Any,
    Hashable,
    Iterable,
    Mapping,
    TypeVar,
)
from datetime import datetime, timedelta
import re
import pandas as pd

from app.enums import ConfigSheetName, ValidationType
from app.services.google_drive import download_file
from app.settings import settings
from app.schemas.validation import ValidationRule
from app.schemas.variables import (
    LoopVariable,
    PlainVariable,
    MultichoiceVariable,
    ConstantVariable,
    RowVariable,
    Variable,
)

_validation_rules: dict[str, ValidationRule] = {}
_variables: dict[str, Variable] = {}
_preview_variables: dict[str, Any] = {}
_last_update_time: datetime | None = None


def _is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def _parse_bool_emoji(value: str) -> bool:
    return value.strip() == "✔️"


def _det_config_dfs() -> dict[ConfigSheetName, pd.DataFrame]:
    config_content = BytesIO()

    download_file(
        settings.CONFIG_SPREADSHEET_ID,
        config_content,
        export_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    config_content.seek(0)
    file = pd.ExcelFile(config_content)
    config_dfs: dict[ConfigSheetName, pd.DataFrame] = {}

    for sheet_name in ConfigSheetName:
        df = pd.read_excel(file, sheet_name.value, engine="openpyxl")
        config_dfs[sheet_name] = df

    file.close()

    return config_dfs


T = TypeVar("T", bound=Hashable)


def detect_cycles(graph: Mapping[T, Iterable[T]]) -> None:
    visited = set()
    stack = set()

    def visit(node: T) -> None:
        if node in stack:
            raise Exception(f"Cycle detected in variables: {node}")
        if node in visited:
            return

        stack.add(node)
        for child in graph.get(node, []):
            visit(child)

        stack.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def update_cache() -> None:
    global _last_update_time
    global _variables
    global _preview_variables
    global _validation_rules

    now = datetime.now()
    config_dfs = _det_config_dfs()

    validation_df = config_dfs[ConfigSheetName.VALIDATION]
    rules: dict[str, ValidationRule] = {}

    for _, row in validation_df.iterrows():
        if pd.isna(row["Name"]) or pd.isna(row["Regex"]):
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

    variables: dict[str, Variable] = {}

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
            nullable=_parse_bool_emoji(str(row["Allow skip"])),
            allow_save=_parse_bool_emoji(str(row["Allow save"])),
            type=ValidationType.PLAIN,
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
                nullable=_parse_bool_emoji(str(row["Allow skip"])),
                allow_save=_parse_bool_emoji(str(row["Allow save"])),
                choices=[choice] if choice else [],
                type=ValidationType.MULTICHOICE,
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
            nullable=False,
            allow_save=False,
            type=ValidationType.CONSTANT,
        )

    rows_df = config_dfs[ConfigSheetName.ROW]
    for _, row in rows_df.iterrows():
        variable_name = row["Variable"]
        if pd.isna(variable_name):
            continue

        variable_name = str(variable_name)
        row_variables = [
            r.strip() for r in str(row["Variables"]).split(",") if r.strip()
        ]

        variables[variable_name] = RowVariable(
            variable=variable_name,
            name=str(row["Name"]),
            variable_names=row_variables,
            variables=[],
            nullable=_parse_bool_emoji(str(row["Allow skip"])),
            allow_save=False,
            type=ValidationType.ROW,
        )

    loops_df = config_dfs[ConfigSheetName.LOOPS]
    for _, row in loops_df.iterrows():
        variable_name = row["Variable"]
        if pd.isna(variable_name):
            continue

        variable_name = str(variable_name)
        loop_variables = [
            r.strip() for r in str(row["Variables"]).split(",") if r.strip()
        ]

        variables[variable_name] = LoopVariable(
            variable=variable_name,
            name=str(row["Name"]),
            variable_names=loop_variables,
            variables=[],
            nullable=_parse_bool_emoji(str(row["Allow skip"])),
            allow_save=False,
            type=ValidationType.LOOP,
        )

    graph: dict[str, list[str]] = {}
    for name, var in variables.items():
        if var.type in (ValidationType.ROW, ValidationType.LOOP):
            graph[name] = list(var.variable_names)  # type: ignore
        else:
            graph[name] = []

    detect_cycles(graph)

    for var in variables.values():
        if var.type in (ValidationType.ROW, ValidationType.LOOP):
            var.variables = [variables[name] for name in var.variable_names]  # type: ignore

    _validation_rules = rules
    _variables = variables

    for key, var in variables.items():
        _preview_variables[key] = var.get_preivew()

    _last_update_time = now


def update_cache_if_required() -> None:
    if _last_update_time is None or datetime.now() - _last_update_time >= timedelta(
        seconds=settings.CONFIG_CACHE_DURATION
    ):
        update_cache()


def get_validation_rules_dict() -> dict[str, ValidationRule]:
    update_cache_if_required()

    return _validation_rules


def get_variables_dict() -> dict[str, Variable]:
    update_cache_if_required()

    return _variables


def get_preview_variables() -> dict[str, Any]:
    update_cache_if_required()

    return _preview_variables

from typing import List, Optional, Union
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.enums import VariableType
from app.models.common_responses import DetailResponse
from app.models.config import ConfigResponse
from app.settings import settings
from app.models.google import DriveFile
from app.models.validation import (
    ValidationResult,
    ValidationRule,
    ValidationRequest,
)
from app.models.variables import (
    ConstantVariable,
    MultichoiceVariable,
    PlainVariable,
    VariablesResponse,
)
from app.services.google_drive import (
    format_drive_file_metadata,
    get_drive_item_metadata,
)
from app.services.config import update_cache
from app.services.rules import (
    get_validation_rules,
    get_validation_rule,
    validate_value,
)
from app.services.variables import get_variables, get_variable, validate_variable
from app.utils import (
    validate_rule_name,
    validate_variable_name,
    validate_variable_value as validate_variable_val,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
async def get_all_config_data() -> ConfigResponse:
    validation_rules = get_validation_rules()
    variables = get_variables()
    file = format_drive_file_metadata(
        get_drive_item_metadata(settings.CONFIG_SPREADSHEET_ID)
    )

    return ConfigResponse(
        validation_rules=validation_rules, variables=variables, file=file
    )


@router.post("/refresh", response_model=DetailResponse)
async def refresh_config_cache() -> DetailResponse:
    update_cache()
    return DetailResponse(detail="Refreshed successfully")


@router.get("/file", response_model=DriveFile)
async def get_config_file() -> DriveFile:
    return format_drive_file_metadata(
        get_drive_item_metadata(settings.CONFIG_SPREADSHEET_ID)
    )


@router.get("/validation_rules", response_model=List[ValidationRule])
async def get_rules() -> List[ValidationRule]:
    return get_validation_rules()


@router.get(
    "/validation_rules/{rule}",
    response_model=ValidationRule,
    responses={
        404: {
            "description": "Rule not found",
            "content": {"application/json": {"example": {"detail": "Rule not found"}}},
        },
    },
)
async def get_rule(rule: str) -> ValidationRule:
    validate_rule_name(rule)

    validation_rule = get_validation_rule(rule)
    if not validation_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return validation_rule


@router.post(
    "/validation_rules/{rule}/validate",
    response_model=ValidationResult,
    responses={
        200: {
            "description": "Validation successful",
            "content": {
                "application/json": {
                    "example": {
                        "error": None,
                        "is_valid": True,
                    }
                }
            },
        },
        404: {
            "description": "Rule not found",
            "content": {"application/json": {"example": {"detail": "Rule not found"}}},
        },
        400: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid value for rule 'number'",
                        "is_valid": False,
                    }
                }
            },
        },
    },
)
async def validate_rule(
    rule: str, request: ValidationRequest
) -> Union[ValidationResult, JSONResponse]:
    validate_rule_name(rule)
    validate_variable_val(request.value)

    validation_rule = get_validation_rule(rule)
    if not validation_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    error = validate_value(validation_rule, request.value)
    if error:
        return JSONResponse(
            status_code=400, content={"is_valid": False, "error": error}
        )

    return ValidationResult(is_valid=True, error=None)


@router.get(
    "/variables",
    response_model=VariablesResponse,
)
async def get_all_variables(
    type: Optional[VariableType] = Query(None, description="Filter variables by type")
) -> VariablesResponse:
    variables = get_variables()
    if type:
        variables = [v for v in variables if v.type == type]

    return VariablesResponse(variables=variables)


@router.get(
    "/variables/{variable}",
    response_model=Union[PlainVariable, MultichoiceVariable, ConstantVariable],
    responses={
        404: {
            "description": "Variable not found",
            "content": {
                "application/json": {"example": {"detail": "Variable not found"}}
            },
        },
    },
)
async def get_variable_config(
    variable: str,
) -> Union[PlainVariable, MultichoiceVariable, ConstantVariable]:
    validate_variable_name(variable)

    var = get_variable(variable)
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")

    return var


@router.post(
    "/variables/{variable}/validate",
    response_model=ValidationResult,
    responses={
        200: {
            "description": "Validation successful",
            "content": {
                "application/json": {
                    "example": {
                        "error": None,
                        "is_valid": True,
                    }
                }
            },
        },
        404: {
            "description": "Variable not found",
            "content": {
                "application/json": {"example": {"detail": "Variable not found"}}
            },
        },
        400: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid value for rule 'number'",
                        "is_valid": False,
                    }
                }
            },
        },
    },
)
async def validate_variable_value(
    variable: str, request: ValidationRequest
) -> Union[ValidationResult, JSONResponse]:
    validate_variable_name(variable)
    validate_variable_val(request.value)

    var = get_variable(variable)
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")

    if isinstance(var, ConstantVariable):
        return JSONResponse(
            status_code=400,
            content={"error": "Cannot validate constant variable", "is_valid": False},
        )

    error = validate_variable(var, request.value)
    if error:
        return JSONResponse(
            status_code=400, content={"is_valid": False, "error": error}
        )

    return ValidationResult(is_valid=True, error=None)

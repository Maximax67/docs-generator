from typing import Any
from datetime import datetime
import jsonschema
from pydantic import BaseModel, Field, field_validator
from beanie import PydanticObjectId

from app.settings import settings
from app.schemas.users import UserPublicResponse
from app.constants import DEFAULT_VARIABLE_ORDER


class VariableCreate(BaseModel):
    variable: str = Field(..., description="Variable name")
    allow_save: bool = Field(
        default=False, description="Allow users to save this variable"
    )
    scope: str | None = Field(
        None, description="Scope (folder/document ID) or None for global"
    )
    required: bool = Field(default=True, description="Is this variable required")
    validation_schema: dict[str, Any] | None = Field(
        None, description="JSON Schema for validation"
    )
    value: Any | None = Field(None, description="Constant value (if not user input)")
    order: int = Field(DEFAULT_VARIABLE_ORDER, ge=0, description="Variable order")

    @field_validator("variable")
    def validate_variable_name(cls: "VariableCreate", v: str) -> str:
        if not v:
            raise ValueError("Variable name cannot be empty")

        if len(v) > settings.MAX_VARIABLE_NAME:
            raise ValueError(
                f"Variable name cannot exceed {settings.MAX_VARIABLE_NAME} characters"
            )

        stripped = v.strip()
        if not stripped:
            raise ValueError("Variable name cannot be empty")

        return stripped

    @field_validator("validation_schema")
    def validate_variable_schema(
        cls: "VariableCreate", v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not v:
            return None

        try:
            jsonschema.Draft202012Validator.check_schema(v)
        except jsonschema.SchemaError as e:
            raise ValueError(f"Variable schema error: {e}")

        return v


class VariableUpdate(BaseModel):
    variable: str | None = None
    allow_save: bool | None = None
    scope: str | None = None
    required: bool | None = None
    validation_schema: dict[str, Any] | None = None
    value: Any | None = None
    order: int | None = None

    @field_validator("variable")
    def validate_variable_name(cls: "VariableUpdate", v: str | None) -> str | None:
        if v is None:
            return v

        if not v.strip():
            raise ValueError("Variable name cannot be empty")

        if len(v) > settings.MAX_VARIABLE_NAME:
            raise ValueError(
                f"Variable name cannot exceed {settings.MAX_VARIABLE_NAME} characters"
            )

        return v.strip()

    @field_validator("validation_schema")
    def validate_variable_schema(
        cls: "VariableUpdate", v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not v:
            return None

        try:
            jsonschema.Draft202012Validator.check_schema(v)
        except jsonschema.SchemaError as e:
            raise ValueError(f"Variable schema error: {e}")

        return v


class VariableSchemaUpdate(BaseModel):
    scope: str | None = Field(
        default=None, description="Scope (folder/document ID) or None for global"
    )
    validation_schema: dict[str, Any] = Field(
        ..., description="JSON Schema object with variable definitions"
    )

    @field_validator("validation_schema")
    def validate_schema(
        cls: "VariableSchemaUpdate", v: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            jsonschema.Draft202012Validator.check_schema(v)
        except jsonschema.SchemaError as e:
            raise ValueError(f"Invalid JSON schema: {e}")

        if v.get("type") != "object":
            raise ValueError("Root schema must be of type 'object'")

        if v.get("properties") is None:
            raise ValueError("Schema must define 'properties'")

        return v


class VariableOverride(BaseModel):
    id: PydanticObjectId
    scope: str | None


class VariableResponse(BaseModel):
    id: PydanticObjectId
    variable: str
    allow_save: bool
    scope: str | None
    required: bool
    created_by: UserPublicResponse | None
    updated_by: UserPublicResponse | None
    validation_schema: dict[str, Any] | None
    value: Any
    created_at: datetime
    updated_at: datetime
    overrides: list[VariableOverride] = Field(
        default_factory=list, description="List of variables overridden by this one"
    )
    order: int

    class Config:
        from_attributes = True


class VariableSchemaResponse(BaseModel):
    validation_schema: dict[str, Any]
    variables: list[VariableResponse]


class VariableValidateRequest(BaseModel):
    value: Any = Field(
        ..., description="Value to validate against variable validation schema"
    )


class VariableSaveRequest(BaseModel):
    value: Any = Field(..., description="Value to save for this variable")


class SavedVariableResponse(BaseModel):
    user: PydanticObjectId
    variable: VariableResponse
    value: Any
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VariableBatchSaveItem(BaseModel):
    id: PydanticObjectId = Field(..., description="Variable ID")
    value: Any = Field(..., description="Value to save for this variable")


class VariableBatchSaveRequest(BaseModel):
    variables: list[VariableBatchSaveItem] = Field(
        ..., min_length=1, max_length=100, description="List of variables to save"
    )


class VariableBatchSaveResponse(BaseModel):
    variables: list[SavedVariableResponse]


class VariableBatchReorderItem(BaseModel):
    id: PydanticObjectId = Field(..., description="Variable ID")
    order: int = Field(..., ge=0, description="Variable order")


class VariableBatchReorderRequest(BaseModel):
    variables: list[VariableBatchReorderItem] = Field(
        ..., min_length=1, max_length=100, description="List of variables to reorder"
    )

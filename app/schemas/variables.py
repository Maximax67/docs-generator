from typing import Any
from datetime import datetime
import jsonschema
from pydantic import BaseModel, Field, field_validator
from beanie import PydanticObjectId

from app.settings import settings


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
    value: dict[str, Any] | None = Field(
        None, description="Constant value (if not user input)"
    )

    @field_validator("variable")
    def validate_variable_name(cls: "VariableCreate", v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Variable name cannot be empty")

        if len(v) > settings.MAX_VARIABLE_NAME:
            raise ValueError(
                f"Variable name cannot exceed {settings.MAX_VARIABLE_NAME} characters"
            )

        return v.strip()

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

        if not v.get("properties"):
            raise ValueError("Schema must have at least one property")

        return v


class VariableResponse(BaseModel):
    id: PydanticObjectId
    variable: str
    allow_save: bool
    scope: str | None
    required: bool
    created_by: PydanticObjectId | None
    updated_by: PydanticObjectId | None
    validation_schema: dict[str, Any] | None
    value: Any
    created_at: datetime
    updated_at: datetime
    overrides: list[dict[str, Any]] = Field(
        default_factory=list, description="List of variables overridden by this one"
    )

    class Config:
        from_attributes = True


class VariableValidateRequest(BaseModel):
    value: Any = Field(
        ..., description="Value to validate against variable validation schema"
    )


class VariableSaveRequest(BaseModel):
    value: Any = Field(..., description="Value to save for this variable")


class SavedVariableResponse(BaseModel):
    id: PydanticObjectId
    user: PydanticObjectId
    variable: PydanticObjectId
    value: Any
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

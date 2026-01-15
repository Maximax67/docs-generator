from typing import Any
from pydantic import BaseModel, Field

from app.schemas.google import DriveFile


class DocumentVariable(BaseModel):
    """Information about a single variable in a document template."""

    variable: str = Field(..., description="Variable name")
    in_database: bool = Field(
        ..., description="Whether this variable has configuration in database"
    )
    value: Any = Field(
        None, description="Constant value (if set), or None for user input"
    )
    validation_schema: dict[str, Any] | None = Field(
        None, description="JSON Schema for validation (if configured)"
    )
    required: bool = Field(False, description="Whether this variable is required")
    allow_save: bool = Field(
        False, description="Whether users can save this variable value"
    )
    scope: str | None = Field(None, description="Scope where this variable is defined")
    saved_value: Any = Field(
        None, description="User's previously saved value (if authenticated and saved)"
    )


class DocumentVariables(BaseModel):
    """All variables for a document template."""

    template_variables: list[str] = Field(
        ..., description="List of all variable names found in the template"
    )
    variables: list[DocumentVariable] = Field(
        ..., description="Detailed configuration for each variable"
    )


class GenerateDocumentRequest(BaseModel):
    """Request body for document generation."""

    variables: dict[str, Any] = Field(
        default_factory=dict, description="Variable values for document generation"
    )
    bypass_validation: bool = Field(
        default=False,
        description="If true, skip all validation and use user values as-is",
    )


class ValidationErrorsResponse(BaseModel):
    """Response for validation errors."""

    is_valid: bool = Field(..., description="Whether validation passed")
    errors: dict[str, str] = Field(
        default_factory=dict, description="Map of variable names to error messages"
    )


class DocumentDetails(BaseModel):
    """Complete document information."""

    file: DriveFile = Field(..., description="Document file metadata")
    variables: DocumentVariables = Field(..., description="Document variables")

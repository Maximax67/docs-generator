from typing import Any
from beanie import PydanticObjectId
from beanie.operators import In
import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError

from app.models import Variable
from app.services.google_drive import get_item_path
from app.exceptions import ValidationErrorsException


async def get_effective_variables(
    scope_id: str | None = None, user_id: PydanticObjectId | None = None
) -> dict[str, dict[str, Any]]:
    """
    Get all effective variables for a given scope, respecting hierarchy.

    Returns a dict where keys are variable names and values contain:
    - value: The actual value (constant or None)
    - schema: Validation schema (if applicable)
    - required: Whether the variable is required
    - allow_save: Whether users can save this variable
    - scope: The effective scope this variable comes from
    - saved_value: User's saved value (if user_id provided and variable has saved value)
    """
    # Get scope chain
    if scope_id:
        scope_chain = get_item_path(scope_id)
    else:
        scope_chain = None

    # Get all variables in the scope chain
    variables = await Variable.find(In(Variable.scope, scope_chain)).to_list()

    # Organize by name, keeping most specific scope
    effective_vars: dict[str, Variable] = {}

    for var in variables:
        if var.variable not in effective_vars:
            effective_vars[var.variable] = var
        else:
            # Check if this variable is more specific
            current_priority = get_scope_priority(
                effective_vars[var.variable].scope, scope_chain
            )
            new_priority = get_scope_priority(var.scope, scope_chain)

            if new_priority < current_priority:
                effective_vars[var.variable] = var

    # Build result
    result: dict[str, dict[str, Any]] = {}
    for name, var in effective_vars.items():
        var_id = str(var.id)
        result[name] = {
            "id": var_id,
            "value": var.value,
            "schema": var.schema,
            "required": var.required,
            "allow_save": var.allow_save,
            "scope": var.scope,
        }

    return result


def get_scope_priority(scope: str | None, scope_chain: list[str] | None) -> int:
    """
    Get priority of a scope in the chain.
    Lower number = more specific (higher priority).
    """
    if scope_chain is None:
        return 1

    if scope is None:
        return len(scope_chain)

    try:
        return scope_chain.index(scope)
    except ValueError:
        return len(scope_chain) + 1


async def resolve_document_variables(
    document_id: str,
    user_provided_values: dict[str, Any],
    user_id: PydanticObjectId | None = None,
) -> dict[str, Any]:
    """
    Resolve all variables for a document, combining:
    1. Constants (from Variable.value)
    2. User's saved values (from SavedVariable)
    3. User-provided values (from request)

    Validates all values and returns final context for document generation.

    Raises ValidationErrorsException if validation fails.
    """
    effective_vars = await get_effective_variables(document_id, user_id)

    # Build final context
    context: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for var_name, var_info in effective_vars.items():
        # Priority: constant > user_provided > saved > error if required

        if var_info["value"] is not None:
            # It's a constant
            context[var_name] = var_info["value"]

            # Check if user tried to override a constant
            if var_name in user_provided_values:
                errors[var_name] = "Cannot override constant variable"

        elif var_name in user_provided_values:
            # User provided a value
            value = user_provided_values[var_name]

            # Validate against schema if exists
            if var_info["schema"]:
                try:
                    jsonschema.validate(instance=value, schema=var_info["schema"])
                    context[var_name] = value
                except JsonSchemaValidationError as e:
                    errors[var_name] = f"Validation error: {e.message}"
            else:
                context[var_name] = value

        elif var_info["saved_value"] is not None:
            # Use saved value
            context[var_name] = var_info["saved_value"]

        elif var_info["required"]:
            # Required but not provided
            errors[var_name] = "Missing required variable"

    if errors:
        raise ValidationErrorsException(errors)

    return context


def validate_user_variable(variable_name: str, value: Any) -> str | None:
    """
    Validate a single user variable value.
    Returns error message if invalid, None if valid.
    """
    # Add any custom validation logic here
    return None


def validate_user_variables(variables: dict[str, Any]) -> dict[str, str]:
    """
    Validate multiple user variables.
    Returns dict of errors (empty if all valid).
    """
    errors: dict[str, str] = {}

    for name, value in variables.items():
        error = validate_user_variable(name, value)
        if error:
            errors[name] = error

    return errors


async def get_variable_overrides(
    variable_name: str, current_scope: str | None
) -> list[dict[str, Any]]:
    """
    Get list of variables that are overridden by the current variable.
    Returns list sorted from most specific to most global scope.
    """
    if current_scope is None:
        return []

    try:
        scope_chain = get_item_path(current_scope)
    except Exception:
        return []

    # Remove current scope from chain
    scope_chain = [s for s in scope_chain if s != current_scope]

    # Find all variables with same name in parent scopes
    overridden = await Variable.find(
        Variable.variable == variable_name, In(Variable.scope, scope_chain + [None])
    ).to_list()

    # Sort by scope specificity (more specific first)
    def scope_priority(var: Variable) -> int:
        if var.scope is None:
            return len(scope_chain) + 1
        try:
            return scope_chain.index(var.scope)
        except ValueError:
            return len(scope_chain)

    overridden.sort(key=scope_priority)

    return [
        {
            "id": str(var.id),
            "scope": var.scope,
            "value": var.value,
            "schema": var.schema,
        }
        for var in overridden
    ]

from typing import Any
from beanie import PydanticObjectId
from beanie.operators import In, Eq
import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError

from app.models import Variable, SavedVariable
from app.services.google_drive import get_item_path
from app.exceptions import ValidationErrorsException
from app.constants import DEFAULT_VARIABLE_ORDER


async def get_effective_variables_for_document(
    document_id: str,
    template_variables: set[str],
    user_id: PydanticObjectId | None = None,
    file_parent: str | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Get effective variables for a document based on template variables and database config.

    Returns dict where keys are variable names and values contain:
    - id: Variable id if it is configured in database
    - value: Constant value (if set) or None
    - validation_schema: Validation schema (if set) or None
    - required: Whether the variable is required
    - allow_save: Whether users can save this variable
    - scope: The effective scope this variable comes from
    - saved_value: User's saved value (if user_id provided)
    """
    # Get scope chain for the document
    try:
        scope_chain = get_item_path(document_id, file_parent)
    except Exception:
        scope_chain = []

    # Fetch all variables from database that might apply to this document
    if scope_chain:
        db_variables = await Variable.find(
            In(Variable.scope, scope_chain + [None])
        ).to_list()
    else:
        db_variables = await Variable.find(Eq(Variable.scope, None)).to_list()

    # Organize by name, keeping most specific scope
    effective_db_vars: dict[str, Variable] = {}

    for var in db_variables:
        if var.variable in template_variables:
            if var.variable not in effective_db_vars:
                effective_db_vars[var.variable] = var
            else:
                # Check if this variable is more specific
                current_priority = get_scope_priority(
                    effective_db_vars[var.variable].scope, scope_chain
                )
                new_priority = get_scope_priority(var.scope, scope_chain)

                if new_priority > current_priority:
                    effective_db_vars[var.variable] = var

    # Get user's saved variables if user_id provided
    saved_values: dict[str, Any] = {}
    if user_id:
        saved_vars = await SavedVariable.find(
            SavedVariable.user.id == user_id  # type: ignore[attr-defined]
        ).to_list()

        for saved in saved_vars:
            # Get the variable name from the linked Variable
            var_obj = await Variable.get(saved.variable.ref.id)
            if var_obj and var_obj.variable in template_variables:
                saved_values[var_obj.variable] = saved.value

    # Build result for all template variables
    result: dict[str, dict[str, Any]] = {}

    for var_name in template_variables:
        if var_name in effective_db_vars:
            var = effective_db_vars[var_name]
            result[var_name] = {
                "id": var.id,
                "value": var.value,
                "validation_schema": var.validation_schema,
                "required": var.required,
                "allow_save": var.allow_save,
                "scope": var.scope,
                "saved_value": saved_values.get(var_name),
                "order": var.order,
            }
        else:
            # Variable not in database, accept any user input
            result[var_name] = {
                "value": None,
                "validation_schema": None,
                "required": False,
                "allow_save": False,
                "scope": None,
                "saved_value": None,
                "order": DEFAULT_VARIABLE_ORDER,
            }

    return result


def get_scope_priority(scope: str | None, scope_chain: list[str]) -> int:
    """
    Get priority of a scope in the chain.
    Higher number = more specific (higher priority).
    """
    if not scope_chain:
        return 0

    if scope is None:
        return 0

    try:
        return scope_chain.index(scope)
    except ValueError:
        return 0


async def resolve_variables_for_generation(
    document_id: str,
    template_variables: set[str],
    user_provided_values: dict[str, Any],
    user_id: PydanticObjectId | None = None,
    bypass_validation: bool = False,
) -> dict[str, Any]:
    """
    Resolve all variables for document generation.

    Combines:
    1. Constants from database (Variable.value)
    2. User-provided values (from request)
    3. User's saved values (from SavedVariable)

    Validates according to rules:
    - If variable not in database: accept user input as-is
    - If variable in database with constant: use constant, reject user override
    - If variable in database, required, no user input: reject
    - If variable in database with schema: validate user input

    If bypass_validation=True, skip all validation and use user values as-is.

    Raises ValidationErrorsException if validation fails.
    """
    if bypass_validation:
        # Bypass all validation, return user values as-is
        return user_provided_values

    # Get effective variables configuration
    effective_vars = await get_effective_variables_for_document(
        document_id, template_variables, user_id
    )

    # Build final context
    context: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for var_name, var_info in effective_vars.items():
        if not var_info.get("id"):
            # Variable not in database, accept user input if provided
            if var_name in user_provided_values:
                context[var_name] = user_provided_values[var_name]
            # If not provided, it's optional - don't add to context
            continue

        # Variable is in database
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
            if var_info["validation_schema"]:
                try:
                    jsonschema.validate(
                        instance=value, schema=var_info["validation_schema"]
                    )
                    context[var_name] = value
                except JsonSchemaValidationError as e:
                    errors[var_name] = f"Validation error: {e.message}"
            else:
                context[var_name] = value

        elif var_info["saved_value"] is not None:
            # Use saved value
            value = var_info["saved_value"]

            # Validate saved value against schema if exists
            if var_info["validation_schema"]:
                try:
                    jsonschema.validate(
                        instance=value, schema=var_info["validation_schema"]
                    )
                    context[var_name] = value
                except JsonSchemaValidationError as e:
                    errors[var_name] = f"Saved value validation error: {e.message}"
            else:
                context[var_name] = value

        elif var_info["required"]:
            # Required but not provided
            errors[var_name] = "Missing required variable"

    if errors:
        raise ValidationErrorsException(errors)

    return context


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
        }
        for var in overridden
    ]


def build_overrides_map(
    all_vars: list[Variable],
    scope_chain: list[str] | None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Pre-compute overrides for every variable in a single pass.
    Returns {variable_id: [overrides]} sorted most specific → global.
    """
    if not scope_chain:
        return {}

    # Group variables by name
    by_name: dict[str, list[Variable]] = {}
    for var in all_vars:
        by_name.setdefault(var.variable, []).append(var)

    # Precompute scope priority once: lower index = more specific, None = last
    scope_order = {s: i for i, s in enumerate(scope_chain)}
    global_priority = len(scope_chain)

    def scope_priority(v: Variable) -> int:
        if v.scope is None:
            return global_priority

        return scope_order.get(v.scope, global_priority - 1)

    overrides_map: dict[str, list[dict[str, Any]]] = {}

    for group in by_name.values():
        group.sort(key=scope_priority)

        for var in group:
            # Overrides = everything in the group that is less specific than this var
            var_priority = scope_priority(var)
            overrides_map[str(var.id)] = [
                {
                    "id": str(v.id),
                    "scope": v.scope,
                }
                for v in group
                if scope_priority(v) > var_priority
            ]

    return overrides_map

from typing import Any, cast
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from beanie import Link, PydanticObjectId, SortDirection
from beanie.operators import In, RegEx, Eq
import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError

from app.dependencies import get_current_user, require_admin
from app.limiter import limiter
from app.models import Variable, User, SavedVariable
from app.schemas.common_responses import DetailResponse, Paginated
from app.schemas.variables import (
    VariableCompactResponse,
    VariableCreate,
    VariableResponse,
    VariableSchemaResponse,
    VariableSchemaUpdate,
    VariableValidateRequest,
    VariableSaveRequest,
    SavedVariableResponse,
)
from app.services.google_drive import get_drive_item_metadata, get_item_path
from app.services.variables import get_variable_overrides
from app.utils.paginate import paginate


router = APIRouter(prefix="/variables", tags=["variables"])

common_responses: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "Variable not found",
        "content": {"application/json": {"example": {"detail": "Variable not found"}}},
    },
    403: {
        "description": "Forbidden",
        "content": {"application/json": {"example": {"detail": "Forbidden"}}},
    },
    401: {
        "description": "Unauthorized",
        "content": {"application/json": {"example": {"detail": "Unauthorized"}}},
    },
}


@router.get(
    "",
    response_model=Paginated[VariableResponse],
    responses={403: common_responses[403]},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def get_variables(
    request: Request,
    response: Response,
    scope: str | None = Query(
        None, description="Filter by scope (use 'null' for None)"
    ),
    search: str | None = Query(None, description="Search by variable name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> Paginated[VariableResponse]:
    """
    Get all variables with optional filtering by scope and search.

    - **scope**: Filter by scope. Use 'null' string to filter variables with scope=None
    - **search**: Search by variable name (case-insensitive partial match)
    """
    query_filters: list[Any] = []

    if scope is not None:
        if scope.lower() == "null":
            query_filters.append(Eq(Variable.scope, None))
        else:
            # Get scope chain for hierarchical filtering
            try:
                scope_chain = get_item_path(scope)
                query_filters.append(In(Variable.scope, scope_chain))
            except Exception:
                # If scope is invalid, just filter by exact scope
                query_filters.append(Variable.scope == scope)

    if search:
        query_filters.append(RegEx(Variable.variable, f".*{search}.*", "i"))

    if query_filters:
        query = Variable.find(*query_filters, fetch_links=True)
    else:
        query = Variable.find_all(fetch_links=True)

    items, meta = await paginate(query, page, page_size)
    items_with_overrides = []

    for var in items:
        overrides = await get_variable_overrides(var.variable, var.scope)
        var_dict = var.model_dump()
        var_dict["overrides"] = overrides
        items_with_overrides.append(VariableResponse(**var_dict))

    return Paginated(
        data=items_with_overrides,
        meta=meta,
    )


@router.put(
    "",
    response_model=VariableResponse,
    responses={
        **common_responses,
        409: {
            "description": "Variable with this name and scope already exists",
            "content": {
                "application/json": {"example": {"detail": "Variable already exists"}}
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def create_or_update_variable(
    body: VariableCreate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> VariableResponse:
    """
    Create or update a variable.

    - If variable with same name and scope exists, it will be updated
    - If not, a new variable will be created
    """
    # Validate that either value or schema is provided, not both
    if body.value is not None and body.validation_schema is not None:
        raise HTTPException(
            status_code=400, detail="Variable cannot have both 'value' and 'schema'"
        )

    if body.value is None and body.validation_schema is None:
        raise HTTPException(
            status_code=400, detail="Variable must have either 'value' or 'schema'"
        )

    # Validate scope exists if provided
    if body.scope:
        try:
            get_drive_item_metadata(body.scope)
        except Exception:
            raise HTTPException(
                status_code=404, detail="Scope does not exist in Google Drive"
            )

    # Find existing variable
    existing = await Variable.find_one(
        Variable.variable == body.variable,
        Variable.scope == body.scope,
        fetch_links=True,
    )

    if existing:
        # Update existing variable
        update_data = body.model_dump(exclude_unset=True)
        update_data["updated_by"] = current_user

        for key, value in update_data.items():
            setattr(existing, key, value)

        await existing.save()
        variable = existing
    else:
        # Create new variable
        variable = Variable(
            **body.model_dump(),
            created_by=cast(Link[User], current_user),
            updated_by=cast(Link[User], current_user),
        )
        await variable.insert()

    # Get overrides
    overrides = await get_variable_overrides(variable.variable, variable.scope)
    resp = VariableResponse.model_validate(variable)
    resp.overrides = overrides

    return resp


@router.get(
    "/schema",
    response_model=VariableSchemaResponse,
    responses={
        **common_responses,
        400: {
            "description": "Invalid schema or scope",
            "content": {
                "application/json": {"example": {"detail": "Invalid JSON schema"}}
            },
        },
    },
)
@limiter.limit("10/minute")
async def get_variables_schema(
    request: Request,
    response: Response,
    scope: str | None = Query(None),
) -> VariableSchemaResponse:
    """
    Get variables schema for a scope.

    - **validation_schema**: JSON schema built from variables with exact scope match
    - **variables**: All variables for the scope and its parent scopes (hierarchical)

    Returns variables with only: id, scope, variable, value fields
    """

    if scope:
        try:
            scope_chain = get_item_path(scope)
        except Exception:
            scope_chain = [scope]
    else:
        scope_chain = [None]

    all_vars = await Variable.find(In(Variable.scope, scope_chain)).to_list()

    properties: dict[str, Any] = {}
    required: list[str] = []
    variables_list: list[VariableCompactResponse] = []

    for var in all_vars:
        if var.scope == scope and var.validation_schema:
            properties[var.variable] = var.validation_schema
            if var.required:
                required.append(var.variable)

        variables_list.append(
            VariableCompactResponse(
                id=var.id,  # type: ignore
                scope=var.scope,
                variable=var.variable,
                value=var.value,
            )
        )

    validation_schema = (
        {
            "type": "object",
            "properties": properties,
            "required": required,
        }
        if properties
        else {}
    )

    return VariableSchemaResponse(
        validation_schema=validation_schema, variables=variables_list
    )


@router.put(
    "/schema",
    response_model=DetailResponse,
    responses={
        **common_responses,
        400: {
            "description": "Invalid schema or scope",
            "content": {
                "application/json": {"example": {"detail": "Invalid JSON schema"}}
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def update_variables_schema(
    body: VariableSchemaUpdate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    """
    Update all variables for a scope based on a JSON schema.

    - Extracts properties from schema as individual variables
    - Updates existing variables, creates new ones, deletes unused ones
    - Uses 'required' array to mark required variables
    """

    if body.scope:
        try:
            get_drive_item_metadata(body.scope)
        except Exception:
            raise HTTPException(
                status_code=404, detail="Scope does not exist in Google Drive"
            )

    try:
        jsonschema.Draft202012Validator.check_schema(body.validation_schema)
    except jsonschema.SchemaError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON schema: {e}")

    if body.validation_schema.get("type") != "object":
        raise HTTPException(
            status_code=400, detail="Root schema must be of type 'object'"
        )

    properties = body.validation_schema.get("properties", {})
    required_fields = set(body.validation_schema.get("required", []))

    if not properties:
        raise HTTPException(
            status_code=400, detail="Schema must have at least one property"
        )

    existing_vars = await Variable.find(Variable.scope == body.scope).to_list()

    existing_by_name = {v.variable: v for v in existing_vars}
    variable_names_in_schema = set(properties.keys())

    created_count = 0
    updated_count = 0
    deleted_count = 0

    for var_name, var_schema in properties.items():
        is_required = var_name in required_fields

        if var_name in existing_by_name:
            existing = existing_by_name[var_name]
            existing.validation_schema = var_schema
            existing.required = is_required
            existing.updated_by = cast(Link[User], current_user)
            await existing.save()
            updated_count += 1
        else:
            new_var = Variable(
                variable=var_name,
                scope=body.scope,
                validation_schema=var_schema,
                required=is_required,
                allow_save=False,
                created_by=cast(Link[User], current_user.id),
                updated_by=cast(Link[User], current_user.id),
            )
            await new_var.insert()
            created_count += 1

    for var_name, existing_var in existing_by_name.items():
        if var_name not in variable_names_in_schema:
            await SavedVariable.find(
                SavedVariable.variable.id  # type: ignore[attr-defined]
                == existing_var.id
            ).delete()

            await existing_var.delete()
            deleted_count += 1

    return DetailResponse(
        detail=f"Schema updated: {created_count} created, {updated_count} updated, {deleted_count} deleted"
    )


@router.get(
    "/saved",
    response_model=Paginated[SavedVariableResponse],
    responses={401: common_responses[401]},
)
@limiter.limit("10/minute")
async def get_saved_variables(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Paginated[SavedVariableResponse]:
    query = SavedVariable.find(
        SavedVariable.user.id == current_user.id  # type: ignore[attr-defined]
    ).sort([("updated_at", SortDirection.DESCENDING)])

    items, meta = await paginate(query, page, page_size)

    return Paginated(
        data=items,
        meta=meta,
    )


@router.delete(
    "/saved",
    response_model=DetailResponse,
    responses={401: common_responses[401]},
)
@limiter.limit("5/minute")
async def delete_all_saved_variables(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    """Delete all saved variables for the current user."""
    result = await SavedVariable.find(
        SavedVariable.user.id == current_user.id  # type: ignore[attr-defined]
    ).delete()

    count = result.deleted_count if result else 0
    return DetailResponse(detail=f"Deleted {count} saved variables")


@router.get(
    "/{variable_id}",
    response_model=VariableResponse,
    responses={**common_responses},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def get_variable(
    variable_id: PydanticObjectId,
    request: Request,
    response: Response,
) -> VariableResponse:
    """Get a specific variable by ID."""
    variable = await Variable.get(variable_id, fetch_links=True)
    if not variable:
        raise HTTPException(status_code=404, detail="Variable not found")

    overrides = await get_variable_overrides(variable.variable, variable.scope)
    var_dict = variable.model_dump()
    var_dict["overrides"] = overrides

    return VariableResponse(**var_dict)


@router.delete(
    "/{variable_id}",
    response_model=DetailResponse,
    responses={**common_responses},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def delete_variable(
    variable_id: PydanticObjectId,
    request: Request,
    response: Response,
) -> DetailResponse:
    """Delete a variable by ID."""
    variable = await Variable.get(variable_id)
    if not variable:
        raise HTTPException(status_code=404, detail="Variable not found")

    # Delete all saved instances of this variable
    await SavedVariable.find(
        SavedVariable.variable.id == variable_id  # type: ignore[attr-defined]
    ).delete()

    await variable.delete()

    return DetailResponse(detail="Variable deleted")


@router.post(
    "/{variable_id}/validate",
    response_model=DetailResponse,
    responses={
        **common_responses,
        400: {
            "description": "Validation failed",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Validation error",
                        "errors": ["Value must be a string"],
                    }
                }
            },
        },
    },
)
@limiter.limit("10/minute")
async def validate_variable_value(
    variable_id: PydanticObjectId,
    body: VariableValidateRequest,
    request: Request,
    response: Response,
) -> DetailResponse | JSONResponse:
    """
    Validate a value against a variable's schema.

    - Only works for variables with a schema (not constants)
    - Returns validation errors if value doesn't match schema
    """
    variable = await Variable.get(variable_id)
    if not variable:
        raise HTTPException(status_code=404, detail="Variable not found")

    # Check if variable is a constant
    if variable.value is not None:
        raise HTTPException(status_code=400, detail="Cannot validate constant variable")

    if not variable.validation_schema:
        raise HTTPException(status_code=400, detail="Variable has no validation schema")

    # Validate value against schema
    try:
        jsonschema.validate(instance=body.value, schema=variable.validation_schema)
        return DetailResponse(detail="Validation successful")
    except JsonSchemaValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"detail": "Validation error", "errors": [e.message]},
        )


@router.post(
    "/{variable_id}/save",
    response_model=SavedVariableResponse,
    responses={
        **common_responses,
        400: {
            "description": "Cannot save constant variable or validation failed",
            "content": {
                "application/json": {
                    "example": {"detail": "Cannot save constant variable"}
                }
            },
        },
    },
)
@limiter.limit("10/minute")
async def save_variable_value(
    variable_id: PydanticObjectId,
    body: VariableSaveRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> SavedVariableResponse:
    """
    Save a variable value for the current user.

    - Only works for variables with allow_save=True
    - Validates value against schema before saving
    """
    variable = await Variable.get(variable_id)
    if not variable:
        raise HTTPException(status_code=404, detail="Variable not found")

    # Check if variable allows saving
    if not variable.allow_save:
        raise HTTPException(status_code=400, detail="Variable does not allow saving")

    # Check if variable is a constant
    if variable.value is not None:
        raise HTTPException(status_code=400, detail="Cannot save constant variable")

    # Validate value against schema if schema exists
    if variable.validation_schema:
        try:
            jsonschema.validate(instance=body.value, schema=variable.validation_schema)
        except JsonSchemaValidationError as e:
            raise HTTPException(
                status_code=400, detail=f"Validation error: {e.message}"
            )

    # Find or create saved variable
    existing = await SavedVariable.find_one(
        SavedVariable.user.id == current_user.id,  # type: ignore[attr-defined]
        SavedVariable.variable.id == variable_id,  # type: ignore[attr-defined]
    )

    if existing:
        existing.value = body.value
        await existing.save()
        return SavedVariableResponse(**existing.model_dump())
    else:
        saved = SavedVariable(
            user=cast(Link[User], current_user.id),
            variable=cast(Link[Variable], variable_id),
            value=body.value,
        )
        await saved.insert()
        return SavedVariableResponse(**saved.model_dump())


@router.post(
    "/{variable_id}/forget",
    response_model=DetailResponse,
    responses={
        **common_responses,
        404: {
            "description": "Saved variable not found",
            "content": {
                "application/json": {"example": {"detail": "Saved variable not found"}}
            },
        },
    },
)
@limiter.limit("10/minute")
async def forget_variable_value(
    variable_id: PydanticObjectId,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    """Remove a saved variable value for the current user."""
    saved = await SavedVariable.find_one(
        SavedVariable.user.id == current_user.id,  # type: ignore[attr-defined]
        SavedVariable.variable.id == variable_id,  # type: ignore[attr-defined]
    )

    if not saved:
        raise HTTPException(status_code=404, detail="Saved variable not found")

    await saved.delete()
    return DetailResponse(detail="Saved variable removed")

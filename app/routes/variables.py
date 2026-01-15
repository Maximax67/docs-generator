from typing import Any, cast
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from beanie import Link, PydanticObjectId, SortDirection
from beanie.operators import In, RegEx
import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError

from app.dependencies import get_current_user, require_admin
from app.limiter import limiter
from app.models import Variable, User, SavedVariable
from app.schemas.common_responses import DetailResponse, Paginated
from app.schemas.variables import (
    VariableCreate,
    VariableResponse,
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
            query_filters.append(Variable.scope == None)
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
        query = Variable.find(*query_filters)
    else:
        query = Variable.find_all()

    if query_filters:
        query = Variable.find(*query_filters)
    else:
        query = Variable.find_all()

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
    if body.value is not None and body.schema is not None:
        raise HTTPException(
            status_code=400, detail="Variable cannot have both 'value' and 'schema'"
        )

    if body.value is None and body.schema is None:
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
        Variable.variable == body.variable, Variable.scope == body.scope
    )

    if existing:
        # Update existing variable
        update_data = body.model_dump(exclude_unset=True)
        update_data["updated_by"] = current_user.id

        for key, value in update_data.items():
            setattr(existing, key, value)

        await existing.save()
        variable = existing
    else:
        # Create new variable
        variable = Variable(
            **body.model_dump(),
            created_by=cast(Link[User], current_user.id),
            updated_by=cast(Link[User], current_user.id),
        )
        await variable.insert()

    # Get overrides
    overrides = await get_variable_overrides(variable.variable, variable.scope)
    var_dict = variable.model_dump()
    var_dict["overrides"] = overrides

    return VariableResponse(**var_dict)


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
        SavedVariable.user.id  # pyright: ignore[reportAttributeAccessIssue]
        == current_user.id
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
        SavedVariable.user.id  # pyright: ignore[reportAttributeAccessIssue]
        == current_user.id
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
    variable = await Variable.get(variable_id)
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
        SavedVariable.variable.id  # pyright: ignore[reportAttributeAccessIssue]
        == variable_id
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

    if not variable.schema:
        raise HTTPException(status_code=400, detail="Variable has no validation schema")

    # Validate value against schema
    try:
        jsonschema.validate(instance=body.value, schema=variable.schema)
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
    if variable.schema:
        try:
            jsonschema.validate(instance=body.value, schema=variable.schema)
        except JsonSchemaValidationError as e:
            raise HTTPException(
                status_code=400, detail=f"Validation error: {e.message}"
            )

    # Find or create saved variable
    existing = await SavedVariable.find_one(
        SavedVariable.user.id  # pyright: ignore[reportAttributeAccessIssue]
        == current_user.id,
        SavedVariable.variable.id  # pyright: ignore[reportAttributeAccessIssue]
        == variable_id,
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
        SavedVariable.user.id  # pyright: ignore[reportAttributeAccessIssue]
        == current_user.id,
        SavedVariable.variable.id  # pyright: ignore[reportAttributeAccessIssue]
        == variable_id,
    )

    if not saved:
        raise HTTPException(status_code=404, detail="Saved variable not found")

    await saved.delete()
    return DetailResponse(detail="Saved variable removed")

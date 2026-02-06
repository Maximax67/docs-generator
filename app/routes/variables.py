from datetime import datetime, timezone
from typing import Any, cast
from bson import DBRef
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from beanie import Link, PydanticObjectId, SortDirection
from beanie.operators import In, RegEx, Eq
import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError
from pymongo import UpdateOne

from app.dependencies import get_current_user, require_admin
from app.limiter import limiter
from app.models import Variable, User, SavedVariable
from app.schemas.common_responses import DetailResponse, Paginated
from app.schemas.variables import (
    VariableBatchSaveResponse,
    VariableCreate,
    VariableResponse,
    VariableSchemaResponse,
    VariableSchemaUpdate,
    VariableUpdate,
    VariableValidateRequest,
    VariableSaveRequest,
    SavedVariableResponse,
    VariableBatchSaveRequest,
)
from app.services.google_drive import get_drive_item_metadata, get_item_path
from app.services.variables import build_overrides_map, get_variable_overrides
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


@router.post(
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
@limiter.limit("10/minute")
async def create_variable(
    body: VariableCreate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> VariableResponse:
    if body.value is not None and body.validation_schema is not None:
        raise HTTPException(
            status_code=400, detail="Variable cannot have both 'value' and 'schema'"
        )

    if body.scope:
        try:
            get_drive_item_metadata(body.scope)
        except Exception:
            raise HTTPException(
                status_code=404, detail="Scope does not exist in Google Drive"
            )

    existing = await Variable.find_one(
        Variable.variable == body.variable,
        Variable.scope == body.scope,
    )

    if existing:
        raise HTTPException(
            status_code=409, detail="Variable with this name and scope already exists"
        )

    variable = Variable(
        **body.model_dump(),
        created_by=cast(Link[User], current_user),
        updated_by=cast(Link[User], current_user),
    )
    await variable.insert()

    overrides = await get_variable_overrides(variable.variable, variable.scope)
    var_dict = variable.model_dump()
    var_dict["overrides"] = overrides

    return VariableResponse(**var_dict)


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
    """

    if scope:
        try:
            scope_chain = get_item_path(scope)
        except Exception:
            scope_chain = [scope]

        query: In | Eq = In(Variable.scope, scope_chain)
    else:
        query = Eq(Variable.scope, None)

    all_vars = await Variable.find(query, fetch_links=True).to_list()

    properties: dict[str, Any] = {}
    required: list[str] = []
    variables_list: list[VariableResponse] = []

    overrides_map = build_overrides_map(all_vars, scope_chain if scope else None)

    for var in all_vars:
        if var.scope == scope and var.validation_schema:
            properties[var.variable] = var.validation_schema
            if var.required:
                required.append(var.variable)

        var_dict = var.model_dump()
        var_dict["overrides"] = overrides_map.get(str(var.id), [])
        variables_list.append(VariableResponse(**var_dict))

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
@limiter.limit("10/minute")
async def update_variables_schema(
    body: VariableSchemaUpdate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> DetailResponse:
    """
    Update all variables for a scope based on a JSON schema.

    - Extracts properties from schema as individual variables
    - Updates existing variables, creates new ones
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

    to_insert: list[Variable] = []
    to_update: list[Variable] = []

    for var_name, var_schema in properties.items():
        is_required = var_name in required_fields
        dbref = cast(
            Link[User],
            DBRef(current_user.get_collection_name(), current_user.id),
        )

        if var_name in existing_by_name:
            existing = existing_by_name[var_name]
            existing.validation_schema = var_schema
            existing.required = is_required
            existing.updated_by = dbref
            existing.value = None
            to_update.append(existing)
        else:
            to_insert.append(
                Variable(
                    variable=var_name,
                    scope=body.scope,
                    validation_schema=var_schema,
                    required=is_required,
                    allow_save=False,
                    value=None,
                    created_by=dbref,
                    updated_by=dbref,
                )
            )

    removed_var_ids = [
        v.id
        for var_name, v in existing_by_name.items()
        if var_name not in variable_names_in_schema
    ]

    created_count = 0
    if to_insert:
        await Variable.insert_many(to_insert)
        created_count = len(to_insert)

    updated_count = 0
    if to_update:
        now = datetime.now(timezone.utc)
        operations = [
            UpdateOne(
                {"_id": doc.id},
                {
                    "$set": {
                        "validation_schema": doc.validation_schema,
                        "required": doc.required,
                        "updated_by": doc.updated_by,
                        "value": doc.value,
                        "updated_at": now,
                    }
                },
            )
            for doc in to_update
        ]
        await Variable.get_pymongo_collection().bulk_write(operations)
        updated_count += len(to_update)

    if removed_var_ids:
        now = datetime.now(timezone.utc)
        result = await Variable.get_pymongo_collection().update_many(
            {"_id": {"$in": removed_var_ids}},
            {
                "$set": {"required": False, "updated_at": now},
                "$unset": {"validation_schema": ""},
            },
        )
        updated_count += result.modified_count

    return DetailResponse(
        detail=f"Schema updated: {created_count} created, {updated_count} updated"
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
        SavedVariable.user.id == current_user.id,  # type: ignore[attr-defined]
        fetch_links=True,
    ).sort([("updated_at", SortDirection.DESCENDING)])

    items, meta = await paginate(query, page, page_size)
    items = cast(list[SavedVariable], items)

    saved_variables: list[SavedVariableResponse] = []
    for item in items:
        saved_variables.append(
            SavedVariableResponse(
                user=item.user.id,  # type: ignore[attr-defined]
                variable=VariableResponse(**cast(Variable, item.variable).model_dump()),
                value=item.value,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    return Paginated(
        data=saved_variables,
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


@router.post(
    "/save",
    response_model=VariableBatchSaveResponse,
    responses={
        401: common_responses[401],
        400: {
            "description": "One or more variables failed validation — nothing is saved",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Validation failed",
                        "errors": {
                            "507f1f77bcf86cd799439011": "Variable not found",
                            "507f1f77bcf86cd799439012": "Cannot save constant variable",
                        },
                    }
                }
            },
        },
    },
)
@limiter.limit("5/minute")
async def batch_save_variables(
    body: VariableBatchSaveRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> VariableBatchSaveResponse | JSONResponse:
    requested_ids = [item.id for item in body.variables]
    variables_map: dict[PydanticObjectId, Variable] = {
        v.id: v  # type: ignore[misc]
        for v in await Variable.find(
            In(Variable.id, requested_ids), fetch_links=True
        ).to_list()
    }

    errors: dict[str, str] = {}

    for item in body.variables:
        variable = variables_map.get(item.id)

        if not variable:
            errors[str(item.id)] = "Variable not found"
            continue

        if not variable.allow_save:
            errors[str(item.id)] = "Variable does not allow saving"
            continue

        if variable.value is not None:
            errors[str(item.id)] = "Cannot save constant variable"
            continue

        if variable.validation_schema:
            try:
                jsonschema.validate(
                    instance=item.value, schema=variable.validation_schema
                )
            except JsonSchemaValidationError as e:
                errors[str(item.id)] = f"Validation error: {e.message}"

    if errors:
        return JSONResponse(
            status_code=400,
            content={"detail": "Validation failed", "errors": errors},
        )

    existing_docs = await SavedVariable.find(
        SavedVariable.user.id == current_user.id,  # type: ignore[attr-defined]
        In(SavedVariable.variable.id, requested_ids),  # type: ignore[attr-defined]
        fetch_links=True,
    ).to_list()

    existing_map: dict[PydanticObjectId, SavedVariable] = {
        doc.variable.id: doc for doc in existing_docs  # type: ignore[attr-defined]
    }

    to_insert: list[SavedVariable] = []
    to_update: list[SavedVariable] = []

    for item in body.variables:
        existing = existing_map.get(item.id)

        if existing:
            existing.value = item.value
            to_update.append(existing)
        else:
            to_insert.append(
                SavedVariable(
                    user=cast(Link[User], current_user.id),
                    variable=cast(Link[Variable], item.id),
                    value=item.value,
                )
            )

    if to_insert:
        await SavedVariable.insert_many(to_insert)

    if to_update:
        now = datetime.now(timezone.utc)
        operations = [
            UpdateOne(
                {"_id": doc.id},
                {"$set": {"value": doc.value, "updated_at": now}},
            )
            for doc in to_update
        ]
        await SavedVariable.get_pymongo_collection().bulk_write(operations)

    saved_map: dict[PydanticObjectId, SavedVariable] = {}

    for doc in to_insert:
        saved_map[doc.variable.ref.id] = doc

    for doc in to_update:
        doc.updated_at = now
        saved_map[doc.variable.id] = doc  # type: ignore[attr-defined]

    saved: list[SavedVariableResponse] = []

    for sv in saved_map.values():
        if isinstance(sv.variable, Variable):
            var_id = cast(PydanticObjectId, sv.variable.id)
            user_id = sv.user.id  # type: ignore[attr-defined]
        else:
            var_id = sv.variable.ref.id
            user_id = sv.user.ref.id

        var_response = VariableResponse(**variables_map[var_id].model_dump())
        saved_var_response = SavedVariableResponse(
            user=user_id,
            variable=var_response,
            value=sv.value,
            created_at=sv.created_at,
            updated_at=sv.updated_at,
        )
        saved.append(saved_var_response)

    return VariableBatchSaveResponse(variables=saved)


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


@router.patch(
    "/{variable_id}",
    response_model=VariableResponse,
    responses=common_responses,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("15/minute")
async def update_variable(
    variable_id: PydanticObjectId,
    body: VariableUpdate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> VariableResponse:
    existing = await Variable.find_one(
        Variable.id == variable_id,
        fetch_links=True,
    )

    if not existing:
        raise HTTPException(status_code=404, detail="Variable not exists")

    update_data = body.model_dump(exclude_unset=True)

    final_value = update_data.get("value", existing.value)
    final_schema = update_data.get("validation_schema", existing.validation_schema)

    if final_value is not None and final_schema is not None:
        raise HTTPException(
            status_code=400,
            detail="Variable cannot have both 'value' and 'schema'",
        )

    scope = update_data.get("scope", existing.scope)
    if scope is not None:
        try:
            get_drive_item_metadata(scope)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail="Scope does not exist in Google Drive",
            )

    update_data["updated_by"] = current_user

    for key, value in update_data.items():
        setattr(existing, key, value)

    await existing.save_changes()

    overrides = await get_variable_overrides(existing.variable, existing.scope)
    var_dict = existing.model_dump()
    var_dict["overrides"] = overrides

    return VariableResponse(**var_dict)


@router.delete(
    "/{variable_id}",
    response_model=DetailResponse,
    responses={**common_responses},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("15/minute")
async def delete_variable(
    variable_id: PydanticObjectId,
    request: Request,
    response: Response,
) -> DetailResponse:
    """Delete a variable by ID."""
    variable = await Variable.get(variable_id)
    if not variable:
        raise HTTPException(status_code=404, detail="Variable not found")

    await SavedVariable.find(
        SavedVariable.variable.id == variable_id  # type: ignore[attr-defined]
    ).delete()

    await variable.delete()

    return DetailResponse(detail="Variable deleted")


@router.post(
    "/{variable_id}/validation",
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
    variable = await Variable.get(variable_id, fetch_links=True)
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
        fetch_links=True,
    )

    if existing:
        existing.value = body.value
        await existing.save_changes()
        return SavedVariableResponse(
            user=existing.user.id,  # type: ignore[attr-defined]
            variable=VariableResponse(**existing.variable.model_dump()),  # type: ignore[attr-defined]
            value=existing.value,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
    else:
        saved = SavedVariable(
            user=cast(Link[User], current_user.id),
            variable=cast(Link[Variable], variable_id),
            value=body.value,
        )
        await saved.insert()
        return SavedVariableResponse(
            user=saved.user.ref.id,
            variable=VariableResponse(**variable.model_dump()),
            value=saved.value,
            created_at=saved.created_at,
            updated_at=saved.updated_at,
        )


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

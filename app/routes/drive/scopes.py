from typing import Any, cast
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from beanie import Link

from app.constants import DRIVE_FOLDER_MIME_TYPE
from app.dependencies import get_current_user, require_admin
from app.limiter import limiter
from app.models import Scope, ScopeRestrictions, User
from app.schemas.common_responses import DetailResponse, Paginated
from app.schemas.scopes import ScopeCreate, ScopeResponse, ScopeUpdate
from app.services.google_drive import get_drive_item_metadata
from app.services.scopes import get_scope_by_drive_id
from app.utils.paginate import paginate


router = APIRouter(prefix="/scopes", tags=["scopes"])


common_responses: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "Scope or item not found",
        "content": {"application/json": {"example": {"detail": "Scope not found"}}},
    },
    403: {
        "description": "Access denied",
        "content": {"application/json": {"example": {"detail": "Access denied"}}},
    },
    400: {
        "description": "Bad request",
        "content": {
            "application/json": {
                "example": {"detail": "The requested resource is not a folder"}
            }
        },
    },
}


@router.get(
    "",
    response_model=Paginated[ScopeResponse],
    responses={403: common_responses[403]},
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def get_scopes(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    pinned: bool | None = Query(None, description="Filter by pinned status"),
) -> Paginated[ScopeResponse]:
    """Get all scopes with pagination (admin only)."""
    query = Scope.find_all(fetch_links=True)

    if pinned is not None:
        query = query.find(Scope.is_pinned == pinned)

    items, meta = await paginate(query, page, page_size)

    return Paginated(data=items, meta=meta)


@router.post(
    "",
    response_model=ScopeResponse,
    responses={
        **common_responses,
        409: {
            "description": "Scope already exists",
            "content": {
                "application/json": {"example": {"detail": "Scope already exists"}}
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def create_scope(
    body: ScopeCreate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> ScopeResponse:
    """Create a new scope (admin only)."""
    try:
        metadata = get_drive_item_metadata(body.drive_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Drive item not found")

    is_folder = metadata["mimeType"] == DRIVE_FOLDER_MIME_TYPE

    existing = await get_scope_by_drive_id(body.drive_id)
    if existing:
        raise HTTPException(status_code=409, detail="Scope already exists")

    scope = Scope(
        drive_id=body.drive_id,
        is_folder=is_folder,
        is_pinned=body.is_pinned,
        restrictions=ScopeRestrictions(**body.restrictions.model_dump()),
        created_by=cast(Link[User], current_user),
        updated_by=cast(Link[User], current_user),
    )
    await scope.insert()

    return ScopeResponse(**scope.model_dump())


@router.get(
    "/{drive_id}",
    response_model=ScopeResponse,
    responses=common_responses,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def get_scope(
    drive_id: str,
    request: Request,
    response: Response,
) -> ScopeResponse:
    """Get a specific scope by drive_id (admin only)."""
    scope = await get_scope_by_drive_id(drive_id)
    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    return ScopeResponse(**scope.model_dump())


@router.put(
    "/{drive_id}/restrictions",
    response_model=ScopeResponse,
    responses=common_responses,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def update_scope_restrictions(
    drive_id: str,
    body: ScopeUpdate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> ScopeResponse:
    """Update scope restrictions (admin only)."""
    scope = await get_scope_by_drive_id(drive_id)
    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    scope.restrictions = ScopeRestrictions(**body.restrictions.model_dump())
    scope.updated_by = cast(Link[User], current_user)
    await scope.save_changes()

    return ScopeResponse(**scope.model_dump())


@router.post(
    "/{drive_id}/pin",
    response_model=ScopeResponse,
    responses={
        **common_responses,
        409: {
            "description": "Scope already pinned",
            "content": {
                "application/json": {"example": {"detail": "Scope already pinned"}}
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def pin_scope(
    drive_id: str,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> ScopeResponse:
    """Pin a scope (admin only)."""
    scope = await get_scope_by_drive_id(drive_id)
    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    if scope.is_pinned:
        raise HTTPException(status_code=409, detail="Scope already pinned")

    scope.is_pinned = True
    scope.updated_by = cast(Link[User], current_user)
    await scope.save_changes()

    return ScopeResponse(**scope.model_dump())


@router.post(
    "/{drive_id}/unpin",
    response_model=ScopeResponse,
    responses={
        **common_responses,
        409: {
            "description": "Scope not pinned",
            "content": {
                "application/json": {"example": {"detail": "Scope not pinned"}}
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def unpin_scope(
    drive_id: str,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> ScopeResponse:
    """Unpin a scope (admin only)."""
    scope = await get_scope_by_drive_id(drive_id)
    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    if not scope.is_pinned:
        raise HTTPException(status_code=409, detail="Scope not pinned")

    scope.is_pinned = False
    scope.updated_by = cast(Link[User], current_user)
    await scope.save_changes()

    return ScopeResponse(**scope.model_dump())


@router.delete(
    "/{drive_id}",
    response_model=DetailResponse,
    responses=common_responses,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def delete_scope(
    drive_id: str,
    request: Request,
    response: Response,
) -> DetailResponse:
    """Delete a scope (admin only)."""
    scope = await get_scope_by_drive_id(drive_id)
    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    await scope.delete()

    return DetailResponse(detail="Scope deleted successfully")

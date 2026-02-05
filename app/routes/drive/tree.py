from fastapi import APIRouter, Depends, Query, Request, Response

from app.dependencies import get_authorized_user_optional
from app.limiter import limiter
from app.schemas.auth import AuthorizedUser
from app.schemas.scopes import ScopeTreeGlobal, ScopeTree
from app.services.google_drive import get_accessible_files_and_folders
from app.services.tree import (
    build_children_map,
    get_all_pinned_scopes_tree,
    get_single_folder_tree,
)


router = APIRouter(prefix="/tree", tags=["tree"])


@router.get(
    "",
    response_model=ScopeTreeGlobal | ScopeTree,
    responses={
        404: {
            "description": "Folder not found",
            "content": {
                "application/json": {"example": {"detail": "Drive item not found"}}
            },
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
    },
)
@limiter.limit("5/minute")
async def get_tree(
    request: Request,
    response: Response,
    folder_id: str | None = Query(
        None, description="Optional folder ID to get tree for a specific folder"
    ),
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> ScopeTreeGlobal | ScopeTree:
    """
    Get tree structure for scopes.

    - If folder_id is provided: Returns tree for that specific folder (must be accessible)
    - If folder_id is None: Returns tree of all pinned scopes

    Only shows items the user has access to based on scope restrictions.
    """
    drive_items = get_accessible_files_and_folders()
    children_map = build_children_map(drive_items)

    if folder_id is not None:
        return await get_single_folder_tree(folder_id, children_map, authorized_user)

    return await get_all_pinned_scopes_tree(children_map, authorized_user)

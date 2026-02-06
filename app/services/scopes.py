from fastapi import HTTPException

from app.enums import AccessLevel, UserRole
from app.models import Scope
from app.schemas.auth import AuthorizedUser
from app.services.google_drive import (
    get_drive_item_metadata,
    get_item_path,
)
from app.constants import DRIVE_FOLDER_MIME_TYPE


async def get_all_scopes() -> list[Scope]:
    """Get all scopes from database."""
    return await Scope.find_all().to_list()


async def get_scope_by_drive_id(drive_id: str) -> Scope | None:
    """Get scope by Google Drive ID."""
    return await Scope.find_one(Scope.drive_id == drive_id, fetch_links=True)


def build_scope_map(scopes: list[Scope]) -> dict[str, Scope]:
    """Build a map of drive_id -> Scope for O(1) lookups."""
    return {scope.drive_id: scope for scope in scopes}


def check_user_has_access(
    scope: Scope,
    authorized_user: AuthorizedUser | None,
) -> bool:
    """
    Check if user has access based on scope restrictions.

    Args:
        scope: The scope to check access for
        authorized_user: The current user (None if unauthenticated)

    Returns:
        True if user has access, False otherwise
    """
    access_level = scope.restrictions.access_level

    # ANY - everyone has access
    if access_level == AccessLevel.ANY:
        return True

    # All other levels require authentication
    if not authorized_user:
        return False

    # ADMIN - only admins and gods
    if access_level == AccessLevel.ADMIN:
        return authorized_user.role in [UserRole.ADMIN, UserRole.GOD]

    # EMAIL_VERIFIED - only users with verified email
    if access_level == AccessLevel.EMAIL_VERIFIED:
        return authorized_user.is_email_verified

    # AUTHORIZED - any authenticated user
    if access_level == AccessLevel.AUTHORIZED:
        return True

    return False


def find_effective_scope_from_path(
    item_path: list[str],
    scope_map: dict[str, Scope],
    authorized_user: AuthorizedUser | None,
) -> tuple[Scope | None, int]:
    """
    Find the most specific (narrowest) scope that applies to an item and check access.

    Args:
        item_path: Path from root to item [root, ..., item]
        scope_map: Map of drive_id -> Scope
        authorized_user: Current user (None if unauthenticated)

    Returns:
        Tuple of (scope, depth_from_scope)
        - scope: The most specific scope, or None if no access
        - depth_from_scope: How deep the item is from the scope (0 = scope itself)
    """
    # Find the most specific scope in the path (rightmost/deepest)
    most_specific_scope = None
    scope_index = -1

    for i, drive_id in enumerate(item_path):
        if drive_id in scope_map:
            most_specific_scope = scope_map[drive_id]
            scope_index = i

    if most_specific_scope is None:
        return None, -1

    if not check_user_has_access(most_specific_scope, authorized_user):
        return None, -1

    # Calculate depth from scope to item
    depth_from_scope = len(item_path) - scope_index - 1

    return most_specific_scope, depth_from_scope


def is_item_accessible(
    depth_from_scope: int,
    max_depth: int | None,
) -> bool:
    """
    Check if an item is accessible based on depth constraints.

    Args:
        depth_from_scope: How deep the item is from its scope (0 = scope itself)
        max_depth: Maximum allowed depth (None = infinite)

    Returns:
        True if accessible, False otherwise
    """
    if max_depth is None:
        return True

    return depth_from_scope <= max_depth


async def check_document_access(
    document_id: str,
    authorized_user: AuthorizedUser | None,
) -> tuple[bool, str]:
    """
    Check if user has access to a document based on scope restrictions.

    Args:
        document_id: Google Drive document ID
        authorized_user: Current user (None if unauthenticated)

    Returns:
        Tuple of (has_access: bool, reason: str)
    """
    # Get all scopes once
    all_scopes = await get_all_scopes()

    if not all_scopes:
        return False, "No scope restrictions configured"

    scope_map = build_scope_map(all_scopes)

    # Get document metadata to check if it's a folder
    try:
        doc_metadata = get_drive_item_metadata(document_id)
        is_folder = doc_metadata.get("mimeType") == DRIVE_FOLDER_MIME_TYPE
    except Exception:
        return False, "Document not found in Google Drive"

    # Get document's path in the drive hierarchy
    try:
        item_path = get_item_path(document_id)
    except Exception:
        return False, "Cannot determine document location"

    # Find effective scope
    scope, depth_from_scope = find_effective_scope_from_path(
        item_path,
        scope_map,
        authorized_user,
    )

    if scope is None:
        return False, "Forbidden"

    # Check depth restrictions
    max_depth = scope.restrictions.max_depth

    if not is_item_accessible(depth_from_scope, max_depth):
        return (
            False,
            f"{'Folder' if is_folder else 'Document'} exceeds maximum depth "
            f"({depth_from_scope} > {max_depth})",
        )

    # Access granted
    access_level = scope.restrictions.access_level

    print(f"Access granted via {access_level.value} scope")

    return True, f"Access granted via {access_level.value} scope"


async def require_document_access(
    document_id: str,
    authorized_user: AuthorizedUser | None,
) -> None:
    """
    Enforce document access or raise HTTPException.

    Raises:
        HTTPException: 403 if access denied, 404 if document not found
    """
    # GOD users bypass all checks
    if authorized_user and authorized_user.role == UserRole.GOD:
        return

    has_access, reason = await check_document_access(document_id, authorized_user)

    if not has_access:
        if "not found" in reason.lower():
            raise HTTPException(
                status_code=404,
                detail="Document not found or access denied",
            )
        raise HTTPException(status_code=403, detail=reason)


def calculate_remaining_depth(
    depth_from_scope: int,
    max_depth: int | None,
) -> int | None:
    """
    Calculate how many more levels down are accessible.

    Args:
        depth_from_scope: Current depth from scope
        max_depth: Maximum allowed depth (None = infinite)

    Returns:
        Remaining depth, or None for infinite
    """
    if max_depth is None:
        return None

    return max_depth - depth_from_scope

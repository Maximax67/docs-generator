from typing import Any

from app.enums import AccessLevel, UserRole
from app.models import Scope
from app.schemas.auth import AuthorizedUser
from app.services.google_drive import get_folder_path, get_drive_item_metadata
from app.constants import DRIVE_FOLDER_MIME_TYPE


async def get_all_scopes() -> list[Scope]:
    """Get all scopes from database."""
    return await Scope.find_all(fetch_links=True).to_list()


async def get_scope_by_drive_id(drive_id: str) -> Scope | None:
    """Get scope by Google Drive ID."""
    return await Scope.find_one(Scope.drive_id == drive_id, fetch_links=True)


async def check_user_has_access(
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


def calculate_accessible_depth(
    item_path: list[str],
    scope_drive_id: str,
    max_depth: int | None,
) -> int | None:
    """
    Calculate how many more levels down from current item are accessible.

    Args:
        item_path: Path from root to current item [root, ..., current_item]
        scope_drive_id: The scope's drive_id
        max_depth: Maximum depth from scope (None = infinite)

    Returns:
        Remaining depth from current position, or None for infinite
    """
    if max_depth is None:
        return None

    try:
        scope_index = item_path.index(scope_drive_id)
    except ValueError:
        # Item is not in scope path - no access
        return -1

    # Calculate how far we are from scope
    current_depth = len(item_path) - scope_index - 1

    # Calculate remaining depth
    remaining = max_depth - current_depth

    return remaining


async def get_effective_scope_for_item(
    drive_id: str,
    authorized_user: AuthorizedUser | None,
) -> tuple[Scope | None, int | None]:
    """
    Get the effective scope for a Google Drive item.

    Finds the most specific scope that applies to this item and checks access.

    Args:
        drive_id: Google Drive item ID
        authorized_user: Current user (None if unauthenticated)

    Returns:
        Tuple of (scope, remaining_depth) or (None, None) if no access
        remaining_depth is how many levels down are accessible (None = infinite)
    """
    # Get item's path in drive hierarchy
    try:
        item_path = get_folder_path(drive_id)
    except Exception:
        # Item might be a file, try getting its metadata to find parent
        try:
            metadata = get_drive_item_metadata(drive_id)
            parents = metadata.get("parents", [])
            if parents:
                item_path = get_folder_path(parents[0]) + [drive_id]
            else:
                item_path = [drive_id]
        except Exception:
            return None, None

    all_scopes = await get_all_scopes()
    path_index = {drive_id: i for i, drive_id in enumerate(item_path)}

    most_specific_scope = None
    max_scope_index = -1

    for scope in all_scopes:
        idx = path_index.get(scope.drive_id)
        if idx is not None and idx > max_scope_index:
            max_scope_index = idx
            most_specific_scope = scope

    if most_specific_scope is None:
        return None, None

    # Check user has access to this most specific scope
    if not await check_user_has_access(most_specific_scope, authorized_user):
        return None, None

    # Calculate remaining depth
    remaining_depth = calculate_accessible_depth(
        item_path,
        most_specific_scope.drive_id,
        most_specific_scope.restrictions.max_depth,
    )

    if remaining_depth is not None and remaining_depth < 0:
        return None, None

    return most_specific_scope, remaining_depth


async def filter_items_by_access(
    items: list[dict[str, Any]],
    parent_drive_id: str,
    authorized_user: AuthorizedUser | None,
) -> list[dict[str, Any]]:
    """
    Filter Google Drive items based on scope access control.

    Args:
        items: List of Google Drive items
        parent_drive_id: Parent folder drive ID
        authorized_user: Current user (None if unauthenticated)

    Returns:
        Filtered list of items user has access to
    """
    # Get effective scope for parent
    scope, remaining_depth = await get_effective_scope_for_item(
        parent_drive_id,
        authorized_user,
    )

    # No access to parent = no access to children
    if scope is None:
        return []

    # Infinite depth = return all items
    if remaining_depth is None:
        return items

    accessible_items: list[dict[str, Any]] = []

    for item in items:
        mime_type = item.get("mimeType", "")
        is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

        if is_folder:
            # Folders are only accessible if we have depth > 0
            # (to hide folders with restricted content)
            if remaining_depth > 0:
                accessible_items.append(item)
        else:
            # Files are accessible at depth >= 0
            if remaining_depth >= 0:
                accessible_items.append(item)

    return accessible_items

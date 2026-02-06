from collections import defaultdict
from typing import Any
from fastapi import HTTPException

from app.constants import DOC_COMPATIBLE_MIME_TYPES, DRIVE_FOLDER_MIME_TYPE
from app.models import Scope
from app.schemas.auth import AuthorizedUser
from app.schemas.scopes import FolderTree
from app.schemas.google import DriveFile
from app.services.google_drive import (
    ensure_folder,
    format_drive_file_metadata,
    format_drive_folder_metadata,
    get_drive_item_metadata,
    get_item_path,
)
from app.services.scopes import (
    build_scope_map,
    check_user_has_scope_access,
    get_all_scopes,
    is_item_access_allowed,
)


def is_depth_accessible(
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


def build_children_map(
    drive_items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build a map of parent_id -> list of children."""
    children_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in drive_items:
        for parent_id in item.get("parents", []):
            children_map[parent_id].append(item)
    return children_map


def update_scope_for_item(
    item_id: str,
    parent_scope: Scope | None,
    parent_depth: int,
    parent_path: list[str],
    scope_map: dict[str, Scope],
    authorized_user: AuthorizedUser | None,
) -> tuple[Scope | None, int, list[str]]:
    """
    Update the effective scope for an item based on its ID.

    This function checks if the item has a scope defined on it,
    and if so, returns the new scope. Otherwise, it increments
    the depth from the parent scope.

    Args:
        item_id: The current item's drive ID
        parent_scope: The parent's effective scope
        parent_depth: Depth from parent's scope
        parent_path: Path to parent
        scope_map: Map of drive_id -> Scope
        authorized_user: Current user

    Returns:
        Tuple of (effective_scope, depth_from_scope, item_path)
    """
    # Build current path
    item_path = parent_path + [item_id]

    # Check if this item has a scope defined on it
    if item_id in scope_map:
        new_scope = scope_map[item_id]

        if check_user_has_scope_access(new_scope, authorized_user):
            return new_scope, 0, item_path
        else:
            return None, -1, item_path

    # No new scope, use parent's scope with incremented depth
    if parent_scope is None:
        return None, -1, item_path

    return parent_scope, parent_depth + 1, item_path


def build_folder_tree(
    item: dict[str, Any],
    parent_node: FolderTree,
    allowed_depth: int | None,
    scope_map: dict[str, Scope],
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
    visited: set[str],
) -> None:
    """
    Recursively build tree node with access control.

    Returns:
        FolderTree node or None if not accessible
    """
    item_id = item["id"]

    # Prevent infinite loops
    if item_id in visited:
        return

    visited.add(item_id)

    mime_type = item["mimeType"]
    is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

    if allowed_depth is not None:
        allowed_depth -= 1

    new_scope = scope_map.get(item_id)
    if new_scope:
        if not check_user_has_scope_access(new_scope, authorized_user):
            return

        if allowed_depth is not None:
            if new_scope.restrictions.max_depth is None:
                allowed_depth = None
            elif allowed_depth < new_scope.restrictions.max_depth:
                allowed_depth = new_scope.restrictions.max_depth

    if allowed_depth is not None and allowed_depth < 0:
        return

    if is_folder:
        folder = format_drive_folder_metadata(item)
        folder_tree = FolderTree(current_folder=folder, documents=[], folders=[])

        if parent_node is not None:
            parent_node.folders.append(folder_tree)
            children = children_map.get(folder.id, [])

            for child in children:
                build_folder_tree(
                    child,
                    folder_tree,
                    allowed_depth,
                    scope_map,
                    children_map,
                    authorized_user,
                    visited,
                )

        return

    if mime_type in DOC_COMPATIBLE_MIME_TYPES:
        if parent_node is None:
            return

        document = format_drive_file_metadata(item)
        parent_node.documents.append(document)


def get_max_allowed_item_scope_depth(
    item_path: list[str],
    scope_map: dict[str, Scope],
    authorized_user: AuthorizedUser | None,
) -> int | None:
    depth_from_root = len(item_path) - 1
    max_scope_depth: int | None = -1

    for i, drive_id in enumerate(item_path):
        scope = scope_map.get(drive_id)
        if scope and (
            scope.restrictions.max_depth is None
            or i + scope.restrictions.max_depth >= depth_from_root
        ):
            if max_scope_depth is not None:
                if scope.restrictions.max_depth is None:
                    max_scope_depth = None
                else:
                    scope_depth = i + scope.restrictions.max_depth
                    if max_scope_depth < scope_depth:
                        max_scope_depth = scope_depth

            if not check_user_has_scope_access(scope, authorized_user):
                return -1

    return max_scope_depth


async def get_single_folder_tree(
    folder_id: str,
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
) -> FolderTree:
    """
    Get tree for a single folder.

    Args:
        folder_id: The folder's drive ID
        children_map: Map of parent_id -> children
        authorized_user: Current user

    Returns:
        FolderTree with the folder and its accessible children
    """
    try:
        item_metadata = get_drive_item_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Drive item not found")

    ensure_folder(item_metadata["mimeType"])

    all_scopes = await get_all_scopes()
    scope_map = build_scope_map(all_scopes)

    try:
        folder_path = get_item_path(folder_id)
    except Exception:
        raise HTTPException(
            status_code=403, detail="Cannot determine document location"
        )

    allowed_depth = get_max_allowed_item_scope_depth(
        folder_path,
        scope_map,
        authorized_user,
    )

    if allowed_depth is not None:
        if allowed_depth < len(folder_path) - 1:
            raise HTTPException(status_code=403, detail="Access denied")

    folder = format_drive_folder_metadata(item_metadata)
    folder_tree = FolderTree(folders=[], documents=[], current_folder=folder)
    children = children_map.get(folder.id, [])

    visited: set[str] = set()
    visited.add(folder.id)

    for child in children:
        build_folder_tree(
            child,
            folder_tree,
            allowed_depth,
            scope_map,
            children_map,
            authorized_user,
            visited,
        )

    return folder_tree


async def get_all_pinned_scopes_tree(
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
) -> FolderTree:
    """
    Get tree of all pinned scopes.

    Args:
        children_map: Map of parent_id -> children
        authorized_user: Current user

    Returns:
        FolderTree containing all accessible pinned scopes as roots
    """
    all_scopes = await get_all_scopes()
    scope_map = build_scope_map(all_scopes)
    pinned_scopes = [scope for scope in all_scopes if scope.is_pinned]

    roots: list[FolderTree] = []
    root_documents: list[DriveFile] = []
    visited: set[str] = set()

    for scope in pinned_scopes:
        # Get the root item
        try:
            root_metadata = get_drive_item_metadata(scope.drive_id)
        except Exception:
            continue

        # Clear visited for each scope to allow same items in different scopes
        visited.clear()

        mime_type = root_metadata.get("mimeType", "")
        is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

        if is_folder:
            try:
                folder_path = get_item_path(scope.drive_id)
            except Exception:
                continue

            allowed_depth = get_max_allowed_item_scope_depth(
                folder_path,
                scope_map,
                authorized_user,
            )

            if allowed_depth is not None:
                if allowed_depth < len(folder_path) - 1:
                    continue

            folder = format_drive_folder_metadata(root_metadata)
            folder_tree = FolderTree(folders=[], documents=[], current_folder=folder)
            roots.append(folder_tree)

            children = children_map.get(folder.id, [])

            for child in children:
                build_folder_tree(
                    child,
                    folder_tree,
                    allowed_depth,
                    scope_map,
                    children_map,
                    authorized_user,
                    visited,
                )

        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            item_parents = root_metadata.get("parents")
            if item_parents:
                file_parent = item_parents[0]
                item_path = get_item_path(scope.drive_id, file_parent)
            else:
                item_path = [scope.drive_id]

            if is_item_access_allowed(item_path, scope_map, authorized_user):
                document = format_drive_file_metadata(root_metadata)
                root_documents.append(document)

    return FolderTree(folders=roots, documents=root_documents)

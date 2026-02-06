from collections import defaultdict
from typing import Any
from fastapi import HTTPException
from beanie.operators import Eq

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
    check_user_has_access,
    find_effective_scope_from_path,
    get_all_scopes,
    is_item_accessible,
    calculate_remaining_depth,
)


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

        if check_user_has_access(new_scope, authorized_user):
            return new_scope, 0, item_path
        else:
            return None, -1, item_path

    # No new scope, use parent's scope with incremented depth
    if parent_scope is None:
        return None, -1, item_path

    return parent_scope, parent_depth + 1, item_path


async def build_folder_tree(
    item: dict[str, Any],
    parent_node: FolderTree | None,
    parent_scope: Scope | None,
    parent_depth: int,
    parent_path: list[str],
    scope_map: dict[str, Scope],
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
    visited: set[str],
) -> FolderTree | None:
    """
    Recursively build tree node with access control.

    Args:
        item: Drive item metadata
        parent_node: Parent folder tree node (None for root)
        parent_scope: The effective scope from parent
        parent_depth: Depth from parent's scope
        parent_path: Path from root to parent
        scope_map: Map of drive_id -> Scope for O(1) lookups
        children_map: Map of parent_id -> children
        authorized_user: Current user
        visited: Set of visited item IDs to prevent loops

    Returns:
        FolderTree node or None if not accessible
    """
    item_id = item["id"]

    # Prevent infinite loops
    if item_id in visited:
        return None
    visited.add(item_id)

    mime_type = item["mimeType"]
    is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

    # Update scope for this item
    current_scope, depth_from_scope, item_path = update_scope_for_item(
        item_id,
        parent_scope,
        parent_depth,
        parent_path,
        scope_map,
        authorized_user,
    )

    # No scope means no access
    if current_scope is None:
        return None

    # Check if item is accessible based on depth
    max_depth = current_scope.restrictions.max_depth
    if not is_item_accessible(depth_from_scope, max_depth):
        return None

    # Calculate remaining depth for children
    remaining_depth = calculate_remaining_depth(depth_from_scope, max_depth)

    if is_folder:
        folder = format_drive_folder_metadata(item)
        folder_tree = FolderTree(current_folder=folder, documents=[], folders=[])

        if parent_node is not None:
            parent_node.folders.append(folder_tree)

        # Process children only if we have remaining depth
        # For folders: if remaining_depth is 0, we can't show any children
        # For files: if remaining_depth is 0, we can show files but not folders
        if remaining_depth is None or remaining_depth > 0:
            children = children_map.get(folder.id, [])

            # Build children nodes
            for child in children:
                await build_folder_tree(
                    child,
                    folder_tree,
                    current_scope,
                    depth_from_scope,
                    item_path,
                    scope_map,
                    children_map,
                    authorized_user,
                    visited,
                )
        elif remaining_depth == 0:
            # We're at max depth, can only show files (not folders)
            children = children_map.get(folder.id, [])
            for child in children:
                child_mime_type = child.get("mimeType", "")
                if child_mime_type != DRIVE_FOLDER_MIME_TYPE:
                    # Check if file is accessible
                    child_id = child["id"]
                    child_scope, child_depth, _ = update_scope_for_item(
                        child_id,
                        current_scope,
                        depth_from_scope,
                        item_path,
                        scope_map,
                        authorized_user,
                    )
                    if child_scope and is_item_accessible(
                        child_depth,
                        child_scope.restrictions.max_depth,
                    ):
                        if child_mime_type in DOC_COMPATIBLE_MIME_TYPES:
                            document = format_drive_file_metadata(child)
                            folder_tree.documents.append(document)

        return folder_tree

    elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
        if parent_node is None:
            return None

        document = format_drive_file_metadata(item)
        parent_node.documents.append(document)
        return None

    return None


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
    # Get the item metadata
    try:
        item_metadata = get_drive_item_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Drive item not found")

    # Ensure it's a folder
    ensure_folder(item_metadata["mimeType"])

    # Get all scopes once
    from app.services.scopes import get_all_scopes

    all_scopes = await get_all_scopes()
    scope_map = build_scope_map(all_scopes)

    try:
        folder_path = get_item_path(folder_id)
    except Exception:
        folder_path = [folder_id]

    # Find effective scope for this folder
    parent_path = folder_path[:-1]  # Path without the folder itself
    parent_scope, parent_depth = find_effective_scope_from_path(
        folder_path,
        scope_map,
        authorized_user,
    )

    if parent_scope is None:
        raise HTTPException(status_code=403, detail="Access denied")

    # Adjust depth - since find_effective_scope_from_path returns depth
    # for the item itself, we need to subtract 1 for the parent context
    if folder_id in scope_map:
        # This folder is a scope itself
        parent_depth = 0
        parent_path = folder_path[:-1]
    else:
        # Use the depth from the found scope
        # But we need to pass parent_depth as the depth before this item
        parent_depth = parent_depth - 1 if parent_depth > 0 else 0
        parent_path = folder_path[:-1]

    # Build tree
    visited: set[str] = set()
    root_tree = await build_folder_tree(
        item_metadata,
        None,
        parent_scope,
        parent_depth,
        parent_path,
        scope_map,
        children_map,
        authorized_user,
        visited,
    )

    if root_tree is None:
        # Folder exists but may be empty or inaccessible
        folder = format_drive_folder_metadata(item_metadata)
        return FolderTree(folders=[], documents=[], current_folder=folder)

    return root_tree


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

    # Get pinned scopes
    pinned_scopes = await Scope.find(
        Eq(Scope.is_pinned, True),
        fetch_links=True,
    ).to_list()

    # Filter scopes by user access
    accessible_scopes: list[Scope] = []
    for scope in pinned_scopes:
        if check_user_has_access(scope, authorized_user):
            accessible_scopes.append(scope)

    if not accessible_scopes:
        return FolderTree(folders=[], documents=[])

    # Build tree for each pinned scope
    roots: list[FolderTree] = []
    root_documents: list[DriveFile] = []
    visited: set[str] = set()

    for scope in accessible_scopes:
        visited.clear()  # Clear visited for each scope to allow same items in different scopes

        # Get the root item
        try:
            root_metadata = get_drive_item_metadata(scope.drive_id)
        except Exception:
            continue

        mime_type = root_metadata.get("mimeType", "")
        is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

        if is_folder:
            # Build tree starting from this scope (depth 0)
            root_tree = await build_folder_tree(
                root_metadata,
                None,
                scope,
                -1,  # -1 so when we add 1, we get 0 (scope itself)
                [],  # Empty parent path
                scope_map,
                children_map,
                authorized_user,
                visited,
            )

            if root_tree:
                roots.append(root_tree)

        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            # Scope is directly on a document
            # Check if accessible (depth 0 from itself)
            if is_item_accessible(0, scope.restrictions.max_depth):
                document = format_drive_file_metadata(root_metadata)
                root_documents.append(document)

    return FolderTree(folders=roots, documents=root_documents)

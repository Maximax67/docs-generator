from collections import defaultdict
from typing import Any
from fastapi import HTTPException
from beanie.operators import Eq

from app.constants import DOC_COMPATIBLE_MIME_TYPES, DRIVE_FOLDER_MIME_TYPE
from app.models import Scope
from app.schemas.auth import AuthorizedUser
from app.schemas.scopes import ScopeTreeGlobal, ScopeTree
from app.schemas.google import DriveFile
from app.services.google_drive import (
    ensure_folder,
    format_drive_file_metadata,
    format_drive_folder_metadata,
    get_drive_item_metadata,
)
from app.services.scopes import (
    check_user_has_access,
    filter_items_by_access,
    get_effective_scope_for_item,
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


async def build_folder_tree(
    item: dict[str, Any],
    parent_node: ScopeTree | None,
    depth_remaining: int | None,
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
    visited: set[str],
) -> ScopeTree | None:
    """Recursively build tree node with access control for a specific folder."""
    item_id = item["id"]

    # Prevent infinite loops
    if item_id in visited:
        return None
    visited.add(item_id)

    mime_type = item["mimeType"]
    is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

    # Check depth limits
    if depth_remaining is not None:
        if is_folder and depth_remaining <= 0:
            return None
        elif not is_folder and depth_remaining < 0:
            return None

    if is_folder:
        folder = format_drive_folder_metadata(item)
        folder_tree = ScopeTree(current_folder=folder, documents=[], folders=[])

        if parent_node is not None:
            parent_node.folders.append(folder_tree)

        # Get children and filter by access
        children = children_map.get(folder.id, [])
        filtered_children = await filter_items_by_access(
            children,
            folder.id,
            authorized_user,
        )

        # Calculate next depth
        next_depth = depth_remaining - 1 if depth_remaining is not None else None

        # Build children nodes
        for child in filtered_children:
            await build_folder_tree(
                child, folder_tree, next_depth, children_map, authorized_user, visited
            )

        return folder_tree

    elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
        if parent_node is None:
            return None

        document = format_drive_file_metadata(item)
        parent_node.documents.append(document)
        return None

    return None


async def build_pinned_scopes_tree(
    item: dict[str, Any],
    parent_node: ScopeTree | None,
    roots: list[ScopeTree],
    root_documents: list[DriveFile],
    current_scope: Scope,
    remaining_depth: int | None,
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
    visited: set[str],
) -> None:
    """Recursively build tree node with access control for pinned scopes."""
    item_id = item["id"]

    # Prevent infinite loops
    if item_id in visited:
        return
    visited.add(item_id)

    mime_type = item["mimeType"]
    is_folder = mime_type == DRIVE_FOLDER_MIME_TYPE

    # Check depth limits
    if remaining_depth is not None:
        if is_folder and remaining_depth <= 0:
            # No access to this folder
            return
        elif not is_folder and remaining_depth < 0:
            # No access to this file
            return

    if is_folder:
        folder = format_drive_folder_metadata(item)
        folder_tree = ScopeTree(current_folder=folder, documents=[], folders=[])

        if parent_node is not None:
            parent_node.folders.append(folder_tree)
        else:
            roots.append(folder_tree)

        # Get children and filter by access
        children = children_map.get(folder.id, [])
        filtered_children = await filter_items_by_access(
            children,
            folder.id,
            authorized_user,
        )

        # Calculate next depth
        next_depth = remaining_depth - 1 if remaining_depth is not None else None

        # Build children nodes
        for child in filtered_children:
            await build_pinned_scopes_tree(
                child,
                folder_tree,
                roots,
                root_documents,
                current_scope,
                next_depth,
                children_map,
                authorized_user,
                visited,
            )

    elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
        document = format_drive_file_metadata(item)

        if parent_node is None:
            root_documents.append(document)
            return

        parent_node.documents.append(document)


async def get_single_folder_tree(
    folder_id: str,
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
) -> ScopeTree:
    """Get tree for a single folder."""
    # Get the item metadata
    try:
        item_metadata = get_drive_item_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Drive item not found")

    # Ensure it's a folder
    ensure_folder(item_metadata["mimeType"])

    # Check access
    scope, remaining_depth = await get_effective_scope_for_item(
        folder_id,
        authorized_user,
    )

    if scope is None:
        raise HTTPException(status_code=403, detail="Access denied")

    # Build tree
    visited: set[str] = set()
    root_tree = await build_folder_tree(
        item_metadata, None, remaining_depth, children_map, authorized_user, visited
    )

    if root_tree is None:
        folder = format_drive_folder_metadata(item_metadata)
        return ScopeTree(folders=[], documents=[], current_folder=folder)

    return root_tree


async def get_all_pinned_scopes_tree(
    children_map: dict[str, list[dict[str, Any]]],
    authorized_user: AuthorizedUser | None,
) -> ScopeTreeGlobal:
    """Get tree of all pinned scopes."""
    # Get all pinned scopes
    pinned_scopes = await Scope.find(
        Eq(Scope.is_pinned, True), fetch_links=True
    ).to_list()

    # Filter scopes by user access
    accessible_scopes: list[Scope] = []
    for scope in pinned_scopes:
        if await check_user_has_access(scope, authorized_user):
            accessible_scopes.append(scope)

    if not accessible_scopes:
        return ScopeTreeGlobal(folders=[], documents=[])

    # Build tree for each pinned scope
    roots: list[ScopeTree] = []
    root_documents: list[DriveFile] = []
    visited: set[str] = set()  # Prevent infinite loops

    # Build tree for each pinned scope
    for scope in accessible_scopes:
        visited.clear()  # Clear visited for each scope

        # Get the root item
        try:
            root_metadata = get_drive_item_metadata(scope.drive_id)
        except Exception:
            continue

        # Get remaining depth for this scope
        _, remaining_depth = await get_effective_scope_for_item(
            scope.drive_id,
            authorized_user,
        )

        await build_pinned_scopes_tree(
            root_metadata,
            None,
            roots,
            root_documents,
            scope,
            remaining_depth,
            children_map,
            authorized_user,
            visited,
        )

    return ScopeTreeGlobal(folders=roots, documents=root_documents)

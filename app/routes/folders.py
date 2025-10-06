from collections import defaultdict
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.dependencies import require_admin
from app.models.common_responses import DetailResponse
from app.services.google_drive import (
    format_drive_file_metadata,
    format_drive_folder_metadata,
    get_accessible_files_and_folders,
    get_folder_contents,
    get_accessible_folders,
    get_drive_item_metadata,
)
from app.models.google import (
    FolderContents,
    FolderListResponse,
    FolderTree,
    FolderTreeResponse,
)
from app.models.database import PinnedFolder
from app.utils import ensure_folder
from app.limiter import limiter

router = APIRouter(prefix="/folders", tags=["folders"])


common_responses: Dict[Union[int, str], Dict[str, Any]] = {
    404: {
        "description": "Folder not found or access denied",
        "content": {
            "application/json": {
                "example": {"detail": "Folder not found or access denied"}
            }
        },
    },
    400: {
        "description": "The requested resource is not a folder",
        "content": {
            "application/json": {
                "example": {"detail": "The requested resource is not a folder"}
            }
        },
    },
}


@router.get("", response_model=FolderListResponse)
@limiter.limit("5/minute")
async def list_folders(
    request: Request, response: Response, pinned: Optional[bool] = Query(None)
) -> FolderListResponse:
    folders = get_accessible_folders()
    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    pinned_ids = {f.folder_id for f in pinned_folder_objs}
    result = []

    for f in folders:
        is_pinned = f["id"] in pinned_ids
        if pinned is None or pinned == is_pinned:
            folder = format_drive_folder_metadata(f)
            folder.is_pinned = is_pinned
            result.append(folder)

    return FolderListResponse(folders=result)


@router.get("/tree", response_model=FolderTreeResponse)
@limiter.limit("5/minute")
async def get_folders_tree(request: Request, response: Response) -> FolderTreeResponse:
    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    pinned_ids = {f.folder_id for f in pinned_folder_objs}

    drive_items = get_accessible_files_and_folders()
    children_map = defaultdict(list)

    pinned_items: List[Dict[str, Any]] = []
    roots: List[FolderTree] = []

    for item in drive_items:
        if item["id"] in pinned_ids:
            pinned_items.append(item)
            continue

        for parent_id in item.get("parents", []):
            children_map[parent_id].append(item)

    def build_node(item: Dict[str, Any], parent: Optional[FolderTree]) -> None:
        mime_type = item["mimeType"]

        if mime_type == "application/vnd.google-apps.folder":
            folder = format_drive_folder_metadata(item)
            folder.is_pinned = folder.id in pinned_ids

            folder_tree = FolderTree(current_folder=folder, documents=[], folders=[])
            if folder.is_pinned:
                if parent is not None:
                    raise ValueError("Children can not be pinned")

                roots.append(folder_tree)
            elif parent is not None:
                parent.folders.append(folder_tree)
            else:
                raise ValueError("Root folder should be pinned")

            for child in children_map.get(folder.id, []):
                build_node(child, folder_tree)
        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            if parent is None:
                raise ValueError("Parent can not be null for a file")

            document = format_drive_file_metadata(item)
            parent.documents.append(document)

    for item in pinned_items:
        build_node(item, None)

    return FolderTreeResponse(tree=roots)


@router.post(
    "/refresh_pinned",
    response_model=DetailResponse,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def refresh_pinned_folders(
    request: Request, response: Response
) -> DetailResponse:
    folders = get_accessible_folders()
    folder_ids = {f["id"] for f in folders}
    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    removed = 0

    for pinned in pinned_folder_objs:
        if pinned.folder_id not in folder_ids:
            await pinned.delete()
            removed += 1

    return DetailResponse(detail=f"Refreshed pinned list. Removed {removed} records")


@router.get("/{folder_id}", responses=common_responses)
@limiter.limit("5/minute")
async def get_folder(
    folder_id: str, request: Request, response: Response
) -> FolderContents:
    try:
        current_folder_metadata = get_drive_item_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    ensure_folder(current_folder_metadata["mimeType"])

    try:
        contents = get_folder_contents(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    pinned_ids = {f.folder_id for f in pinned_folder_objs}

    folders = []
    documents = []

    for item in contents:
        mime_type = item["mimeType"]

        if mime_type == "application/vnd.google-apps.folder":
            folder = format_drive_folder_metadata(item)
            folder.is_pinned = folder.id in pinned_ids
            folders.append(folder)
        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            documents.append(format_drive_file_metadata(item))

    current_folder = format_drive_folder_metadata(current_folder_metadata)
    current_folder.is_pinned = current_folder.id in pinned_ids

    return FolderContents(
        folders=folders,
        documents=documents,
        current_folder=current_folder,
    )


@router.post(
    "/{folder_id}/pin",
    response_model=DetailResponse,
    responses=common_responses,
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def pin_folder(
    folder_id: str, request: Request, response: Response
) -> DetailResponse:
    try:
        metadata = get_drive_item_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    ensure_folder(metadata["mimeType"])

    existing = await PinnedFolder.find_one(PinnedFolder.folder_id == folder_id)
    if existing:
        raise HTTPException(status_code=400, detail="Folder already pinned")

    folder = PinnedFolder(folder_id=folder_id)
    await folder.insert()

    return DetailResponse(detail="Folder pinned")


@router.post(
    "/{folder_id}/unpin",
    response_model=DetailResponse,
    responses={
        404: {
            "description": "Folder not found in pinned list",
            "content": {
                "application/json": {
                    "example": {"detail": "Folder not found in pinned list"}
                }
            },
        },
    },
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def unpin_folder(
    folder_id: str, request: Request, response: Response
) -> DetailResponse:
    to_unpin = await PinnedFolder.find_one(PinnedFolder.folder_id == folder_id)
    if not to_unpin:
        raise HTTPException(status_code=404, detail="Folder not found in pinned list")

    await to_unpin.delete()

    return DetailResponse(detail="Folder unpinned")

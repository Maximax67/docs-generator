from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.dependencies import verify_token
from app.models.common_responses import DetailResponse
from app.services.google_drive import (
    format_drive_file_metadata,
    get_folder_contents,
    get_accessible_folders,
    get_file_metadata,
)
from app.models.google import FolderContents, DriveFolder, FolderListResponse
from app.models.database import TrustedFolder
from app.utils import ensure_folder

router = APIRouter(prefix="/folders", tags=["folders"])


common_responses = {
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
async def list_folders(trusted: Optional[bool] = Query(None)) -> FolderListResponse:
    folders = get_accessible_folders()
    trusted_folder_objs = await TrustedFolder.find_all().to_list()
    trusted_ids = {f.folder_id for f in trusted_folder_objs}
    result = []

    for f in folders:
        is_trusted = f["id"] in trusted_ids
        if trusted is None or trusted == is_trusted:
            folder = format_drive_file_metadata(f)
            folder = DriveFolder(**folder.model_dump(), is_trusted=is_trusted)
            result.append(folder)

    return FolderListResponse(folders=result)


@router.post(
    "/refresh_trusted",
    response_model=DetailResponse,
    dependencies=[Depends(verify_token)],
)
async def refresh_trusted_folders() -> Dict[str, str]:
    folders = get_accessible_folders()
    folder_ids = {f["id"] for f in folders}
    trusted_folder_objs = await TrustedFolder.find_all().to_list()
    removed = 0

    for trusted in trusted_folder_objs:
        if trusted.folder_id not in folder_ids:
            await trusted.delete()
            removed += 1

    return DetailResponse(detail=f"Refreshed trusted list. Removed {removed} records")


@router.get("/{folder_id}", responses=common_responses)
async def get_folder(folder_id: str) -> FolderContents:
    try:
        current_folder = get_file_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    ensure_folder(current_folder["mimeType"])

    try:
        contents = get_folder_contents(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    trusted_folder_objs = await TrustedFolder.find_all().to_list()
    trusted_ids = {f.folder_id for f in trusted_folder_objs}

    folders = []
    documents = []

    for item in contents:
        mime_type = item["mimeType"]

        if mime_type == "application/vnd.google-apps.folder":
            folder = format_drive_file_metadata(item)
            is_trusted = folder.id in trusted_ids
            folders.append(DriveFolder(**folder.model_dump(), is_trusted=is_trusted))
        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            documents.append(format_drive_file_metadata(item))

    current_is_trusted = current_folder["id"] in trusted_ids

    return FolderContents(
        folders=folders,
        documents=documents,
        current_folder=DriveFolder(
            **format_drive_file_metadata(current_folder).model_dump(),
            is_trusted=current_is_trusted,
        ),
    )


@router.post(
    "/{folder_id}/trust",
    response_model=DetailResponse,
    responses=common_responses,
    dependencies=[Depends(verify_token)],
)
async def trust_folder(folder_id: str):
    try:
        metadata = get_file_metadata(folder_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Folder not found or access denied")

    ensure_folder(metadata["mimeType"])

    existing = await TrustedFolder.find_one(TrustedFolder.folder_id == folder_id)
    if existing:
        raise HTTPException(status_code=400, detail="Folder already trusted")

    folder = TrustedFolder(folder_id=folder_id)
    await folder.insert()

    return DetailResponse(detail="Folder trusted")


@router.post(
    "/{folder_id}/untrust",
    response_model=DetailResponse,
    responses={
        404: {
            "description": "Folder not found in trusted list",
            "content": {
                "application/json": {
                    "example": {"detail": "Folder not found in trusted list"}
                }
            },
        },
    },
    dependencies=[Depends(verify_token)],
)
async def untrust_folder(folder_id: str):
    deleted = await TrustedFolder.find_one(TrustedFolder.folder_id == folder_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Folder not found in trusted list")

    await deleted.delete()

    return DetailResponse(detail="Folder untrusted")

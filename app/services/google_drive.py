from datetime import datetime
from typing import Any, BinaryIO, Hashable
from cachetools import TTLCache, cached
from fastapi import HTTPException
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]

from app.constants import (
    CHUNK_DOWNLOAD_THRESHOLD,
    DOC_COMPATIBLE_MIME_TYPES,
    DRIVE_FOLDER_MIME_TYPE,
    MAX_DOWNLOAD_RETRIES,
)
from app.schemas.google import DriveFile, DriveFolder
from app.google_credentials import credentials
from app.services.resource_limits import validate_file_size


drive_client = build("drive", "v3", credentials=credentials)

folder_graph_cache: TTLCache[Hashable, dict[str, Any]] = TTLCache(maxsize=1, ttl=60)
files_and_folders_cache: TTLCache[Hashable, list[dict[str, Any]]] = TTLCache(
    maxsize=1, ttl=60
)
drive_metadata_cache: TTLCache[Hashable, dict[str, Any]] = TTLCache(
    maxsize=1024, ttl=60
)


def get_results_by_query(
    query: str,
    fields: str = "nextPageToken, files(id, name, mimeType, parents, modifiedTime, createdTime, webViewLink, size)",
) -> list[dict[str, Any]]:
    results = []
    page_token = None

    while True:
        response = (
            drive_client.files()
            .list(
                q=query,
                spaces="drive",
                fields=fields,
                pageToken=page_token,
                pageSize=1000,
            )
            .execute()
        )
        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def get_accessible_folders() -> list[dict[str, Any]]:
    return get_results_by_query(
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )


@cached(files_and_folders_cache)
def get_accessible_files_and_folders() -> list[dict[str, Any]]:
    mime_types_query = " or ".join(
        [f"mimeType='{mime}'" for mime in DOC_COMPATIBLE_MIME_TYPES]
    )
    mime_types_query += " or mimeType='application/vnd.google-apps.folder'"

    return get_results_by_query(f"({mime_types_query}) and trashed=false")


@cached(folder_graph_cache)
def get_folder_graph() -> dict[str, Any]:
    folders = get_accessible_folders()

    graph = {}

    for f in folders:
        graph[f["id"]] = {
            "id": f["id"],
            "name": f["name"],
            "parents": f.get("parents", []),
            "children": set(),
        }

    for folder_id, node in graph.items():
        for parent_id in node["parents"]:
            if parent_id in graph:
                graph[parent_id]["children"].add(folder_id)

    return graph


def get_folder_path(folder_id: str) -> list[str]:
    graph = get_folder_graph()

    path: list[str] = []
    current_id = folder_id

    while current_id in graph:
        path.append(current_id)
        node = graph[current_id]
        parents = node.get("parents", [])
        if not parents:
            break

        current_id = parents[0]

    path.reverse()

    return path


def get_item_path(item_id: str, file_parent: str | None = None) -> list[str]:
    graph = get_folder_graph()

    path: list[str] = []

    if item_id in graph:
        current_id = item_id
    elif file_parent:
        current_id = file_parent
        path.append(item_id)
    else:
        # Probably a file
        metadata: dict[str, Any] = (
            drive_client.files()
            .get(
                fileId=item_id,
                fields="parents",
            )
            .execute()
        )

        parents = metadata.get("parents", [])
        if not parents:
            return [item_id]

        current_id = parents[0]
        path.append(item_id)

    while current_id in graph:
        path.append(current_id)
        node = graph[current_id]
        parents = node.get("parents", [])
        if not parents:
            break

        current_id = parents[0]

    path.reverse()

    return path


def ensure_folder(mime_type: str) -> None:
    if mime_type != DRIVE_FOLDER_MIME_TYPE:
        raise HTTPException(
            status_code=400,
            detail="The requested resource is not a folder",
        )


def download_file(
    file_id: str,
    out: BinaryIO,
    export_mime_type: str | None = None,
    file_size: int | None = None,
) -> None:
    """
    Download a file from Google Drive with size validation.

    Args:
        file_id: Google Drive file ID
        out: Output stream to write file contents
        export_mime_type: MIME type for export (for Google Docs)
        file_size: File size in bytes (for validation)

    Raises:
        ResourceLimitError: If file size exceeds MAX_FILE_DOWNLOAD_SIZE
    """
    validate_file_size(file_size)

    if export_mime_type:
        request = drive_client.files().export_media(
            fileId=file_id, mimeType=export_mime_type
        )
    else:
        request = drive_client.files().get_media(fileId=file_id)

    use_chunks = not file_size or file_size >= CHUNK_DOWNLOAD_THRESHOLD

    if use_chunks:
        downloader = MediaIoBaseDownload(out, request)
        done = False
        while not done:
            _, done = downloader.next_chunk(MAX_DOWNLOAD_RETRIES)
    else:
        file_content: bytes = request.execute()
        out.write(file_content)


@cached(drive_metadata_cache)
def get_drive_item_metadata(file_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = (
        drive_client.files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, createdTime, webViewLink, size, parents",
        )
        .execute()
    )

    return metadata


def parse_google_datetime(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def format_drive_file_metadata(file_data: dict[str, Any]) -> DriveFile:
    created_time = parse_google_datetime(file_data["createdTime"])
    modified_time = parse_google_datetime(file_data["modifiedTime"])

    parents = file_data.get("parents")
    size_str: str | None = file_data.get("size")
    size = int(size_str) if size_str else None

    return DriveFile(
        id=file_data["id"],
        name=file_data["name"],
        created_time=created_time,
        modified_time=modified_time,
        web_view_link=file_data.get("webViewLink"),
        mime_type=file_data["mimeType"],
        parent=parents[0] if parents else None,
        size=size,
    )


def format_drive_folder_metadata(folder_data: dict[str, Any]) -> DriveFolder:
    created_time = parse_google_datetime(folder_data["createdTime"])
    modified_time = parse_google_datetime(folder_data["modifiedTime"])
    parents = folder_data.get("parents")

    return DriveFolder(
        id=folder_data["id"],
        name=folder_data["name"],
        created_time=created_time,
        modified_time=modified_time,
        web_view_link=folder_data.get("webViewLink"),
        mime_type=folder_data["mimeType"],
        parent=parents[0] if parents else None,
    )

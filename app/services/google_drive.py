from datetime import datetime
from typing import Any, BinaryIO, Dict, List, Optional
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]

from app.constants import (
    CHUNK_DOWNLOAD_THRESHOLD,
    DOC_COMPATIBLE_MIME_TYPES,
    MAX_DOWNLOAD_RETRIES,
)
from app.models.google import DriveFile, DriveFolder
from app.google_credentials import credentials


drive_client = build("drive", "v3", credentials=credentials)


def get_results_by_query(query: str) -> List[Any]:
    results = []
    page_token = None

    while True:
        response = (
            drive_client.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, webViewLink, size)",
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


def get_folder_contents(folder_id: str) -> List[Any]:
    return get_results_by_query(f"'{folder_id}' in parents")


def get_accessible_folders() -> List[Any]:
    return get_results_by_query(
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )


def get_accessible_documents() -> List[Any]:
    mime_types_query = " or ".join(
        [f"mimeType='{mime}'" for mime in DOC_COMPATIBLE_MIME_TYPES]
    )
    query = f"({mime_types_query}) and trashed=false"

    return get_results_by_query(query)


def download_file(
    file_id: str,
    out: BinaryIO,
    export_mime_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> None:
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


def get_drive_item_metadata(file_id: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = (
        drive_client.files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, createdTime, webViewLink, size",
        )
        .execute()
    )

    return metadata


def parse_google_datetime(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def format_drive_file_metadata(file_data: Dict[str, Any]) -> DriveFile:
    created_time = parse_google_datetime(file_data["createdTime"])
    modified_time = parse_google_datetime(file_data["modifiedTime"])

    size_str: Optional[str] = file_data.get("size")
    size = int(size_str) if size_str else None

    return DriveFile(
        id=file_data["id"],
        name=file_data["name"],
        created_time=created_time,
        modified_time=modified_time,
        web_view_link=file_data.get("webViewLink"),
        mime_type=file_data["mimeType"],
        size=size,
    )


def format_drive_folder_metadata(folder_data: Dict[str, Any]) -> DriveFolder:
    created_time = parse_google_datetime(folder_data["createdTime"])
    modified_time = parse_google_datetime(folder_data["modifiedTime"])

    return DriveFolder(
        id=folder_data["id"],
        name=folder_data["name"],
        created_time=created_time,
        modified_time=modified_time,
        web_view_link=folder_data.get("webViewLink"),
        is_pinned=False,  # Requires database check
    )

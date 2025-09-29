from datetime import datetime
from io import BytesIO
from typing import Any, Dict
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.models.google import DriveFile
from app.settings import settings
from app.google_credentials import credentials


drive_client = build("drive", "v3", credentials=credentials)


def get_results_by_query(query: str):
    results = []
    page_token = None

    while True:
        response = (
            drive_client.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, webViewLink)",
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


def get_folder_contents(folder_id: str):
    return get_results_by_query(f"'{folder_id}' in parents")


def get_accessible_folders():
    return get_results_by_query(
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )


def get_accessible_documents():
    mime_types_query = " or ".join(
        [f"mimeType='{mime}'" for mime in DOC_COMPATIBLE_MIME_TYPES]
    )
    query = f"({mime_types_query}) and trashed=false"

    return get_results_by_query(query)


def download_file(file_id: str) -> bytes:
    request = drive_client.files().get_media(fileId=file_id)
    file_content = request.execute()

    return file_content


def export_file(file_id: str, mime_type: str):
    request = drive_client.files().export_media(fileId=file_id, mimeType=mime_type)
    file_content = request.execute()

    return file_content


def get_file_metadata(file_id: str):
    return (
        drive_client.files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, createdTime, webViewLink",
        )
        .execute()
    )


def parse_google_datetime(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def format_drive_file_metadata(file_data: Dict[str, Any]) -> DriveFile:
    return DriveFile(
        id=file_data["id"],
        name=file_data["name"],
        modified_time=parse_google_datetime(file_data["modifiedTime"]),
        created_time=parse_google_datetime(file_data["createdTime"]),
        web_view_link=file_data.get("webViewLink"),
        mime_type=file_data["mimeType"],
    )


def export_config() -> BytesIO:
    request = drive_client.files().export(
        fileId=settings.CONFIG_SPREADSHEET_ID,
        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    content = BytesIO()
    downloader = MediaIoBaseDownload(content, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()  # downloads in chunks

    content.seek(0)

    return content

import regex as re


CHUNK_DOWNLOAD_THRESHOLD = 10 * 1024 * 1024
MAX_DOWNLOAD_RETRIES = 1

NAME_REGEX = re.compile(r"^[\p{L}]+(?:[’'\- ]\p{L}+)*$", re.UNICODE)

GOOGLE_AUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DOC_COMPATIBLE_MIME_TYPES = [
    "application/vnd.google-apps.document",  # native Google Doc
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/rtf",  # .rtf
    "application/vnd.oasis.opendocument.text",  # .odt
    "text/plain",  # .txt
]

DEFAULT_VARIABLE_ORDER = 10

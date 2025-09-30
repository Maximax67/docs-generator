CHUNK_DOWNLOAD_THRESHOLD = 10 * 1024 * 1024
MAX_DOWNLOAD_RETRIES = 1

GOOGLE_AUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

DOC_COMPATIBLE_MIME_TYPES = [
    "application/vnd.google-apps.document",  # native Google Doc
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/rtf",  # .rtf
    "application/vnd.oasis.opendocument.text",  # .odt
    "text/plain",  # .txt
]

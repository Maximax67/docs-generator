from enum import Enum


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"


class UserRole(str, Enum):
    GOD = "god"
    ADMIN = "admin"
    USER = "user"


class UserStatus(str, Enum):
    active = "active"
    banned = "banned"


class DocumentResponseFormat(str, Enum):
    DOCX = "docx"
    PDF = "pdf"


class AccessLevel(str, Enum):
    ANY = "any"
    AUTHORIZED = "authorized"
    EMAIL_VERIFIED = "email_verified"
    ADMIN = "admin"


FORMAT_TO_MIME = {
    DocumentResponseFormat.PDF: "application/pdf",
    DocumentResponseFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

MIME_TO_FORMAT = {
    "application/pdf": DocumentResponseFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentResponseFormat.DOCX,
}

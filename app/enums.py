from enum import Enum


class VariableType(str, Enum):
    STRING = "string"
    INTEGER = "number"
    FLOAT = "float"
    ARRAY = "array"
    OBJECT = "object"
    BOOLEAN = "boolean"



class ValidationType(str, Enum):
    PLAIN = "plain"
    MULTICHOICE = "multichoice"
    CONSTANT = "constant"
    ROW = "row"
    LOOP = "loop"


class ConfigSheetName(str, Enum):
    VALIDATION = "Validation"
    VARIABLES = "Variables"
    MULTICHOICE_VARIABLES = "Multichoice_Variables"
    CONSTANTS = "Constants"
    ROW = "Rows"
    LOOPS = "Loops"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"


class UserRole(str, Enum):
    GOD = "god"
    ADMIN = "admin"
    USER = "user"


class DocumentResponseFormat(str, Enum):
    DOCX = "docx"
    PDF = "pdf"


FORMAT_TO_MIME = {
    DocumentResponseFormat.PDF: "application/pdf",
    DocumentResponseFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

MIME_TO_FORMAT = {
    "application/pdf": DocumentResponseFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentResponseFormat.DOCX,
}

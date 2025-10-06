from enum import Enum


class VariableType(str, Enum):
    PLAIN = "plain"
    MULTICHOICE = "multichoice"
    CONSTANT = "constant"


class ConfigSheetName(str, Enum):
    VALIDATION = "Validation"
    VARIABLES = "Variables"
    MULTICHOICE_VARIABLES = "Multichoice_Variables"
    CONSTANTS = "Constants"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"


class UserRole(str, Enum):
    GOD = "god"
    ADMIN = "admin"
    USER = "user"

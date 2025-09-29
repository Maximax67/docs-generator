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

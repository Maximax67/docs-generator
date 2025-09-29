import re
from typing import List, Optional

from app.settings import settings
from app.models.validation import ValidationRule
from app.services.config import get_validation_rules_dict


def is_rule_name_valid(variable: str) -> bool:
    pattern = rf"^\w{{1,{settings.MAX_RULE_NAME}}}$"
    return bool(re.fullmatch(pattern, variable))


def get_validation_rules() -> List[ValidationRule]:
    return list(get_validation_rules_dict().values())


def get_validation_rule(name: str) -> Optional[ValidationRule]:
    return get_validation_rules_dict().get(name)


def validate_value(rule: ValidationRule, value: str) -> Optional[str]:
    if not rule.is_valid:
        return "Invalid regex pattern"

    try:
        if re.match(rule.regex, value):
            return None

        if rule.error_message:
            return rule.error_message

        return f"Invalid value for rule '{rule.name}'"
    except re.error:
        return "Regex evaluation failed"

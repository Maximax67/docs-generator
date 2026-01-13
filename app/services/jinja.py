import json
from typing import Any

import jinja2


def from_json(value: Any) -> Any:
    return json.loads(value)


def dict_get(d: dict[Any, Any], key: Any, default: Any = "") -> Any:
    return d.get(key, default)


jinja_env = jinja2.Environment()
jinja_env.filters["from_json"] = from_json
jinja_env.filters["dict_get"] = dict_get

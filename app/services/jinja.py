from datetime import datetime, timezone, tzinfo
import json
from typing import Any
import uuid
from zoneinfo import ZoneInfo

import jinja2


def load_json(value: Any) -> Any:
    return json.loads(value)


def _parse_timezone(tz: str | tzinfo | None) -> tzinfo:
    if tz is None:
        return timezone.utc
    if isinstance(tz, str):
        return ZoneInfo(tz)

    return tz


def now(
    fmt: str = "%Y-%m-%d %H:%M",
    tz: str | tzinfo | None = timezone.utc,
) -> str:
    tzinfo = _parse_timezone(tz)
    return datetime.now(tzinfo).strftime(fmt)


def format_datetime(
    value: Any,
    fmt: str = "%Y-%m-%d %H:%M",
    tz: str | tzinfo | None = timezone.utc,
) -> str:
    if value in (None, ""):
        return ""

    tzinfo = _parse_timezone(tz)

    # datetime input
    if isinstance(value, datetime):
        dt = value

    # Unix timestamp
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=tzinfo)

    # String input
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value  # safe Jinja fallback

    else:
        return str(value)

    # Attach timezone if missing
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tzinfo)

    return dt.strftime(fmt)


def yesno(value: Any, yes: str = "Yes", no: str = "No") -> str:
    return yes if bool(value) else no


def join_non_empty(values: list[Any], sep: str = ", ") -> str:
    return sep.join(str(v) for v in values if v not in (None, ""))


def format_currency(
    value: Any,
    symbol: str = "$",
    decimals: int = 2,
    thousands: str = ",",
) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    formatted = f"{value:,.{decimals}f}"
    return f"{symbol}{formatted.replace(',', thousands)}"


def pluralize(count: Any, singular: str, plural: str | None = None) -> str:
    try:
        count = int(count)
    except Exception:
        return plural or singular + "s"

    return singular if count == 1 else (plural or singular + "s")


def today(fmt: str = "%Y-%m-%d", tz: str | tzinfo | None = timezone.utc) -> str:
    return now(fmt=fmt, tz=tz)


def uuid4() -> str:
    return str(uuid.uuid4())


jinja_env = jinja2.Environment()
jinja_env.filters.update(
    {
        "load_json": load_json,
        "format_datetime": format_datetime,
        "yesno": yesno,
        "join_non_empty": join_non_empty,
        "format_currency": format_currency,
        "pluralize": pluralize,
    }
)

jinja_env.globals.update(
    {
        "now": now,
        "today": today,
        "uuid": uuid4,
    }
)

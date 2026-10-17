from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_models import (
    CustomDimension,
    CustomFilter,
    CustomProtocolFailure,
    CustomRankingEntry,
    CustomRankingGroup,
    CustomSeries,
    CustomUnit,
    LocalizedText,
    V2RankingGroup,
)

PROTOCOL_VERSION = "ccuv.custom/v1"

V2_PROTOCOL_VERSION = "ccuv.custom/v2"

_ERROR_CODES = frozenset(
    {
        "unsupported_dataset",
        "unsupported_chart_kind",
        "unsupported_query",
        "invalid_request",
        "invalid_filter",
        "range_not_available",
        "source_unavailable",
        "internal_error",
    }
)

_DECIMAL_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?$")

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}$")

class CustomProtocolError(ValueError):
    """A command response violates the custom-command protocol."""

    def __init__(self, message: str, *, failure: CustomProtocolFailure | None = None) -> None:
        super().__init__(message)
        self.failure = failure

def _parse_unit(value: object) -> CustomUnit:
    source = _mapping(value, "unit")
    placement = _string(source.get("placement"), "unit placement")
    decimals = source.get("decimal_places")
    if placement not in {"prefix", "suffix"}:
        raise CustomProtocolError("unit placement must be prefix or suffix")
    if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
        raise CustomProtocolError("unit decimal_places must be a non-negative integer")
    return CustomUnit(
        _string(source.get("id"), "unit ID"),
        _parse_localized(source.get("label"), "unit label"),
        placement,
        decimals,
    )  # type: ignore[arg-type]

def _parse_localized(value: object, name: str) -> LocalizedText:
    source = _mapping(value, name)
    return LocalizedText(
        _string(source.get("en"), f"{name} en"), _string(source.get("zh-CN"), f"{name} zh-CN")
    )

def _parse_https_url(value: object, name: str) -> str:
    url = _string(value, name)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in url)
    ):
        raise CustomProtocolError(f"{name} must be an absolute https URL")
    return url

def _parse_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise CustomProtocolError(f"{name} must be a decimal string")
    if not _DECIMAL_RE.fullmatch(value):
        raise CustomProtocolError(f"{name} must be an ordinary decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise CustomProtocolError(f"{name} must be a decimal string") from error

def _parse_date(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise CustomProtocolError(f"{name} must be an ISO-8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise CustomProtocolError(f"{name} must be an ISO-8601 date") from error

def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise CustomProtocolError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CustomProtocolError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise CustomProtocolError(f"{name} must include a timezone")
    return parsed

def _canonical_filters(
    filters: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in filters:
        _require_id(key, "filter ID")
        normalized[key] = tuple(sorted(set(values)))
    return tuple(sorted(normalized.items()))

def _interval_wire(interval: DateInterval) -> dict[str, str]:
    return {"start_date": interval.since.isoformat(), "end_date": interval.until.isoformat()}

def _interval_key(interval: DateInterval | None) -> tuple[str, str] | None:
    return None if interval is None else (interval.since.isoformat(), interval.until.isoformat())

def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CustomProtocolError(f"{name} must be an object")
    return value

def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise CustomProtocolError(f"{name} must be an array")
    return value

def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CustomProtocolError(f"{name} must be a non-empty string")
    return value

def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    values = tuple(_string(item, name) for item in _sequence(value, name))
    if len(set(values)) != len(values):
        raise CustomProtocolError(f"{name} must not contain duplicates")
    return values

def _group_by_tuple(value: object, name: str) -> tuple[str | None, ...]:
    values = tuple(item if item is None else _string(item, name) for item in _sequence(value, name))
    if len(set(values)) != len(values):
        raise CustomProtocolError(f"{name} must not contain duplicates")
    return values

def _unique_ids(
    items: tuple[
        CustomDimension
        | CustomFilter
        | CustomSeries
        | CustomRankingGroup
        | CustomRankingEntry
        | V2RankingGroup,
        ...,
    ],
    name: str,
) -> None:
    if len({item.id for item in items}) != len(items):
        raise CustomProtocolError(f"{name} IDs must be unique")

def _validate_timezone(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("timezone must not be empty")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"timezone must be a valid IANA timezone: {value}") from error

def _require_id(value: str, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")

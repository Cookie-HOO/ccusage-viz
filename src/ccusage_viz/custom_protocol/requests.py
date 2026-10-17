from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, TypeAlias

from ccusage_viz.core.custom_ranking_time import parse_subday_period
from ccusage_viz.core.time import parse_period
from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_protocol.primitives import (
    PROTOCOL_VERSION,
    V2_PROTOCOL_VERSION,
    _canonical_filters,
    _interval_key,
    _interval_wire,
    _json_bytes,
    _require_id,
    _validate_timezone,
)


@dataclass(frozen=True, slots=True)
class CustomChartRequest:
    request_id: str
    dataset_id: str
    timezone: str
    start_date: date
    end_date: date
    period: str | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    granularity: str = "day"
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["chart"] = "chart"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _validate_timezone(self.timezone)
        if self.end_date < self.start_date:
            raise ValueError("custom request range end date must not precede start date")
        if self.period is not None:
            try:
                parse_period(self.period)
            except ValueError as exc:
                raise ValueError("custom request period must be a valid period") from exc
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "timezone": self.timezone,
            "range": {
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "period": self.period,
            },
            "query": {
                "filters": {key: list(values) for key, values in self.filters},
                "group_by": self.group_by,
                "granularity": self.granularity,
            },
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class CustomSummaryRequest:
    request_id: str
    dataset_id: str
    timezone: str
    scope: str
    current: DateInterval
    sequential: DateInterval | None = None
    year_over_year: DateInterval | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["summary"] = "summary"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _validate_timezone(self.timezone)
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        intervals: dict[str, object] = {"current": _interval_wire(self.current)}
        if self.sequential is not None:
            intervals["sequential"] = _interval_wire(self.sequential)
        if self.year_over_year is not None:
            intervals["year_over_year"] = _interval_wire(self.year_over_year)
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "timezone": self.timezone,
            "query": {"filters": {key: list(values) for key, values in self.filters}},
            "summary": {"scope": self.scope, "intervals": intervals},
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class CustomProbeRequest:
    request_id: str
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["probe"] = "probe"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2ProbeRequest:
    request_id: str
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["probe"] = "probe"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2ChartRequest:
    request_id: str
    dataset_id: str
    metric_id: str
    timezone: str
    start_date: date | None = None
    end_date: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    period: str | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    granularity: str = "day"
    top: int | None = None
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["chart"] = "chart"
    partition_by: str | None = None
    partition_declared: bool = False
    chart_kind: Literal["timeline", "calendar", "stack", "ranking"] | None = None

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        if self.chart_kind is None:
            raise ValueError("v2 custom chart request requires chart_kind")
        has_dates = self.start_date is not None or self.end_date is not None
        has_timestamps = self.start_at is not None or self.end_at is not None
        if has_dates == has_timestamps:
            raise ValueError("v2 custom request requires exactly one range shape")
        if has_dates:
            if self.start_date is None or self.end_date is None:
                raise ValueError("v2 custom request date bounds must be complete")
            if self.end_date < self.start_date:
                raise ValueError("v2 custom request range end date must not precede start date")
        else:
            if self.chart_kind != "ranking":
                raise ValueError("v2 custom timestamp ranges are supported only by ranking")
            if self.start_at is None or self.end_at is None:
                raise ValueError("v2 custom request timestamp bounds must be complete")
            if any(
                value.tzinfo is None or value.utcoffset() is None
                for value in (self.start_at, self.end_at)
            ):
                raise ValueError("v2 custom request timestamp bounds must be timezone aware")
            if self.end_at.astimezone(UTC) <= self.start_at.astimezone(UTC):
                raise ValueError("v2 custom request end_at must be after start_at")
        if self.period is not None:
            try:
                if has_timestamps:
                    parse_subday_period(self.period)
                elif self.chart_kind == "ranking" and self.period == "all":
                    pass
                else:
                    parse_period(self.period)
            except ValueError as exc:
                raise ValueError("v2 custom request period must be valid") from exc
        if self.top is not None and self.top < 1:
            raise ValueError("v2 custom request top must be positive")
        if not self.partition_declared and self.partition_by is not None:
            raise ValueError("v2 custom request partition_by requires partition_declared")
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        query: dict[str, object] = {
            "filters": {key: list(values) for key, values in self.filters},
            "group_by": self.group_by,
            "top": self.top,
        }
        if self.chart_kind != "ranking":
            query["granularity"] = self.granularity
        if self.partition_declared:
            query["partition_by"] = self.partition_by
        assert (self.start_at is not None and self.end_at is not None) or (
            self.start_date is not None and self.end_date is not None
        )
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "chart_kind": self.chart_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "range": {
                **(
                    {"start_at": self.start_at.isoformat(), "end_at": self.end_at.isoformat()}
                    if self.start_at is not None and self.end_at is not None
                    else {
                        "start_date": self.start_date.isoformat(),  # ty: ignore[unresolved-attribute]
                        "end_date": self.end_date.isoformat(),  # ty: ignore[unresolved-attribute]
                    }
                ),
                "period": self.period,
            },
            "query": query,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2MonitorRequest:
    request_id: str
    dataset_id: str
    metric_id: str
    timezone: str
    end_at: datetime
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["monitor"] = "monitor"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        if self.end_at.tzinfo is None:
            raise ValueError("v2 monitor end_at must be timezone aware")
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "range": {"end_at": self.end_at.isoformat()},
            "query": {
                "filters": {key: list(values) for key, values in self.filters},
                "group_by": self.group_by,
            },
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2SummaryRequest:
    request_id: str
    dataset_id: str
    metric_id: str
    timezone: str
    scope: str
    current: DateInterval
    sequential: DateInterval | None = None
    year_over_year: DateInterval | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["summary"] = "summary"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        intervals: dict[str, object] = {"current": _interval_wire(self.current)}
        if self.sequential is not None:
            intervals["sequential"] = _interval_wire(self.sequential)
        if self.year_over_year is not None:
            intervals["year_over_year"] = _interval_wire(self.year_over_year)
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "query": {"filters": {key: list(values) for key, values in self.filters}},
            "summary": {"scope": self.scope, "intervals": intervals},
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


CustomRequest: TypeAlias = (
    CustomChartRequest
    | CustomSummaryRequest
    | CustomProbeRequest
    | V2ProbeRequest
    | V2ChartRequest
    | V2MonitorRequest
    | V2SummaryRequest
)

CustomPaneRequest = CustomChartRequest

CustomDashboardSummaryRequest = CustomSummaryRequest


def canonical_custom_request_key(request: CustomRequest) -> tuple[object, ...]:
    if isinstance(request, (CustomProbeRequest, V2ProbeRequest)):
        return (request.command_argv, request.execution_context, request.request_kind)
    common: tuple[object, ...] = (
        request.command_argv,
        request.execution_context,
        request.dataset_id,
        request.request_kind,
    )
    common += (request.timezone,)
    if isinstance(request, (CustomChartRequest, V2ChartRequest)):
        if isinstance(request, V2ChartRequest):
            assert (request.start_at is not None and request.end_at is not None) or (
                request.start_date is not None and request.end_date is not None
            )
        return common + (
            *((request.metric_id,) if isinstance(request, V2ChartRequest) else ()),
            *(
                (
                    request.start_at.astimezone(UTC).isoformat(),
                    request.end_at.astimezone(UTC).isoformat(),
                )
                if isinstance(request, V2ChartRequest)
                and request.start_at is not None
                and request.end_at is not None
                else (
                    request.start_date.isoformat(),  # ty: ignore[unresolved-attribute]
                    request.end_date.isoformat(),  # ty: ignore[unresolved-attribute]
                )
            ),
            request.period,
            request.filters,
            request.group_by,
            (
                None
                if isinstance(request, V2ChartRequest) and request.chart_kind == "ranking"
                else request.granularity
            ),
            request.top if isinstance(request, V2ChartRequest) else None,
            *(
                (request.partition_declared, request.partition_by, request.chart_kind)
                if isinstance(request, V2ChartRequest)
                else ()
            ),
        )
    if isinstance(request, V2MonitorRequest):
        return common + (
            request.metric_id,
            request.end_at.astimezone(UTC).isoformat(),
            request.filters,
            request.group_by,
        )
    if isinstance(request, V2SummaryRequest):
        return common + (
            request.metric_id,
            request.filters,
            request.scope,
            _interval_key(request.current),
            _interval_key(request.sequential),
            _interval_key(request.year_over_year),
        )
    if isinstance(request, CustomSummaryRequest):
        return common + (
            request.filters,
            request.scope,
            _interval_key(request.current),
            _interval_key(request.sequential),
            _interval_key(request.year_over_year),
        )
    return common

from __future__ import annotations

import re

from ccusage_viz.core.custom_ranking_time import parse_subday_period
from ccusage_viz.core.time import parse_period
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomDimension,
    CustomEnvironmentDeclaration,
    CustomFilter,
    CustomFilterOption,
    CustomProbeDescriptor,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_protocol.primitives import (
    CustomProtocolError,
    _group_by_tuple,
    _mapping,
    _parse_localized,
    _parse_unit,
    _require_id,
    _sequence,
    _string,
    _string_tuple,
    _unique_ids,
    _validate_timezone,
)


def _parse_dataset(value: object) -> CustomDataset:
    source = _mapping(value, "dataset")
    return CustomDataset(
        _parse_localized(source.get("title"), "dataset title"),
        _parse_localized(source.get("description"), "dataset description"),
        _parse_unit(source.get("unit")),
    )

def _parse_capabilities(value: object) -> CustomCapabilities:
    source = _mapping(value, "capabilities")
    dimensions = tuple(
        _parse_dimension(item, "group-by dimension")
        for item in _sequence(source.get("group_by"), "capabilities group_by")
    )
    filters = tuple(
        _parse_filter(item) for item in _sequence(source.get("filters"), "capabilities filters")
    )
    charts = _mapping(source.get("charts"), "capabilities charts")
    parsed: dict[str, CustomChartCapability] = {}
    for kind, item in charts.items():
        if kind not in {"timeline", "calendar", "stack", "ranking"}:
            raise CustomProtocolError(f"unsupported chart capability: {kind}")
        chart = _mapping(item, f"chart capability {kind}")
        max_items = chart.get("max_items")
        if max_items is not None and (
            kind != "ranking"
            or not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or max_items < 1
        ):
            raise CustomProtocolError("ranking max_items must be a positive integer")
        descriptions_default = chart.get("descriptions_default", "collapsed")
        if (kind != "ranking" and "descriptions_default" in chart) or descriptions_default not in {
            "expanded",
            "collapsed",
        }:
            raise CustomProtocolError("ranking descriptions_default must be expanded or collapsed")
        comparison = chart.get("comparison", "full")
        if (kind != "ranking" and "comparison" in chart) or comparison not in {
            "full",
            "rank",
            "none",
        }:
            raise CustomProtocolError("ranking comparison must be full, rank, or none")
        show_percentage = chart.get("show_percentage", True)
        if (kind != "ranking" and "show_percentage" in chart) or not isinstance(
            show_percentage, bool
        ):
            raise CustomProtocolError("ranking show_percentage must be a boolean")
        if "sort_direction" in chart:
            raise CustomProtocolError("sort_direction is supported only by v2 ranking capabilities")
        refresh_interval_seconds = chart.get("refresh_interval_seconds")
        if refresh_interval_seconds is not None and (
            not isinstance(refresh_interval_seconds, int)
            or isinstance(refresh_interval_seconds, bool)
            or refresh_interval_seconds < 1
        ):
            raise CustomProtocolError("chart refresh_interval_seconds must be a positive integer")
        parsed[kind] = CustomChartCapability(
            _string_tuple(chart.get("granularities"), f"chart {kind} granularities"),
            _group_by_tuple(chart.get("group_by"), f"chart {kind} group_by"),
            _string_tuple(chart.get("filters"), f"chart {kind} filters"),
            max_items,
            descriptions_default,  # type: ignore[arg-type]
            (),
            comparison,  # type: ignore[arg-type]
            show_percentage,
            refresh_interval_seconds,
        )
    _unique_ids(dimensions, "group-by dimensions")
    _unique_ids(filters, "filters")
    return CustomCapabilities(dimensions, filters, parsed)

def _parse_probe_descriptor(value: object) -> CustomProbeDescriptor:
    source = _mapping(value, "probe descriptor")
    revision = _string(source.get("revision"), "probe descriptor revision")
    version = _string(source.get("version"), "probe descriptor version")
    source_timezone = source.get("source_timezone")
    if source_timezone is not None:
        source_timezone = _string(source_timezone, "probe descriptor source_timezone")
        _validate_timezone(source_timezone)
    defaults_source = _mapping(source.get("defaults"), "probe descriptor defaults")
    defaults: dict[str, CustomChartDefaults] = {}
    for kind, value in defaults_source.items():
        if kind not in {"timeline", "calendar", "stack", "ranking"}:
            raise CustomProtocolError(f"unsupported chart default: {kind}")
        item = _mapping(value, f"chart default {kind}")
        if set(item) != {"period", "group_by", "top"}:
            raise CustomProtocolError(
                f"chart default {kind} must contain period, group_by, and top"
            )
        period = item["period"]
        group_by = item["group_by"]
        top = item["top"]
        if period is not None:
            period = _string(period, f"chart default {kind} period")
            try:
                parse_period(period)
            except ValueError as exc:
                raise CustomProtocolError(f"chart default {kind} period must be valid") from exc
        if group_by is not None:
            group_by = _string(group_by, f"chart default {kind} group_by")
        if top is not None and (not isinstance(top, int) or isinstance(top, bool) or top < 1):
            raise CustomProtocolError(f"chart default {kind} top must be a positive integer")
        defaults[kind] = CustomChartDefaults(period, group_by, top)
    environment = tuple(
        _parse_environment_declaration(item)
        for item in _sequence(source.get("environment"), "environment")
    )
    if len({item.name for item in environment}) != len(environment):
        raise CustomProtocolError("environment names must be unique")
    return CustomProbeDescriptor(
        revision,
        version,
        _parse_dataset(source.get("dataset")),
        _parse_capabilities(source.get("capabilities")),
        defaults,
        environment,
        source_timezone,
    )

def parse_probe_descriptor(value: object) -> CustomProbeDescriptor:
    """Parse a persisted static Dataset descriptor without a response envelope."""

    return _parse_probe_descriptor(value)

def parse_v2_probe_descriptor(value: object) -> V2ProbeDescriptor:
    """Parse a V2 Dataset descriptor with Metric-owned capabilities."""

    source = _mapping(value, "v2 probe descriptor")
    revision = _string(source.get("revision"), "v2 probe descriptor revision")
    version = _string(source.get("version"), "v2 probe descriptor version")
    source_timezone = source.get("source_timezone")
    if source_timezone is not None:
        source_timezone = _string(source_timezone, "v2 probe descriptor source_timezone")
        _validate_timezone(source_timezone)
    dataset = _mapping(source.get("dataset"), "v2 dataset")
    metric_groups = tuple(
        _parse_v2_metric_group(item)
        for item in _sequence(source.get("metric_groups", []), "v2 metric_groups")
    )
    if len({group.id for group in metric_groups}) != len(metric_groups):
        raise CustomProtocolError("v2 metric group IDs must be unique")
    metrics = tuple(
        _parse_v2_metric(item) for item in _sequence(source.get("metrics"), "v2 metrics")
    )
    if not metrics:
        raise CustomProtocolError("v2 metrics must not be empty")
    if len({metric.id for metric in metrics}) != len(metrics):
        raise CustomProtocolError("v2 metric IDs must be unique")
    group_ids = {group.id for group in metric_groups}
    for metric in metrics:
        if metric.group_id is not None and metric.group_id not in group_ids:
            raise CustomProtocolError("v2 metric group_id must reference a declared metric group")
    default_metric_id = source.get("default_metric_id")
    if default_metric_id is not None:
        default_metric_id = _string(default_metric_id, "v2 default_metric_id")
        if default_metric_id not in {metric.id for metric in metrics}:
            raise CustomProtocolError("v2 default_metric_id must reference a declared metric")
    environment = tuple(
        _parse_environment_declaration(item)
        for item in _sequence(source.get("environment"), "v2 environment")
    )
    if len({item.name for item in environment}) != len(environment):
        raise CustomProtocolError("v2 environment names must be unique")
    return V2ProbeDescriptor(
        revision,
        version,
        V2Dataset(
            _parse_localized(dataset.get("title"), "v2 dataset title"),
            _parse_localized(dataset.get("description"), "v2 dataset description"),
        ),
        metrics,
        environment,
        source_timezone,
        default_metric_id,
        metric_groups,
    )

def _parse_v2_metric_group(value: object) -> V2MetricGroup:
    source = _mapping(value, "v2 metric group")
    identifier = _string(source.get("id"), "v2 metric group ID")
    try:
        _require_id(identifier, "v2 metric group ID")
    except ValueError as error:
        raise CustomProtocolError(str(error)) from error
    return V2MetricGroup(identifier, _parse_localized(source.get("title"), "v2 metric group title"))

def _parse_v2_metric(value: object) -> V2MetricDescriptor:
    source = _mapping(value, "v2 metric")
    aggregation = _string(source.get("aggregation"), "v2 metric aggregation")
    if aggregation not in {"sum", "value"}:
        raise CustomProtocolError("v2 metric aggregation must be sum or value")
    summary = source.get("summary", "comparisons")
    if summary not in {"comparisons", "total", "none"}:
        raise CustomProtocolError("v2 metric summary must be comparisons, total, or none")
    group_id = source.get("group_id")
    if group_id is not None:
        group_id = _string(group_id, "v2 metric group_id")
        try:
            _require_id(group_id, "v2 metric group_id")
        except ValueError as error:
            raise CustomProtocolError(str(error)) from error
    return V2MetricDescriptor(
        _string(source.get("id"), "v2 metric ID"),
        _parse_localized(source.get("title"), "v2 metric title"),
        _parse_localized(source.get("description"), "v2 metric description"),
        _parse_unit(source.get("unit")),
        aggregation,  # type: ignore[arg-type]
        capabilities := _parse_v2_capabilities(source.get("capabilities")),
        _parse_v2_defaults(source.get("defaults"), capabilities),
        summary,  # type: ignore[arg-type]
        group_id,
    )

def _parse_v2_capabilities(value: object) -> V2MetricCapabilities:
    source = _mapping(value, "v2 metric capabilities")
    dimensions = tuple(
        _parse_dimension(item, "v2 group-by dimension")
        for item in _sequence(source.get("group_by"), "v2 capabilities group_by")
    )
    partition_dimensions = (
        tuple(
            _parse_dimension(item, "v2 partition-by dimension")
            for item in _sequence(source.get("partition_by"), "v2 capabilities partition_by")
        )
        if "partition_by" in source
        else None
    )
    if "filters" in source:
        raise CustomProtocolError("v2 metric capabilities must not declare filters")
    charts: dict[str, V2HistoricalChartCapability | V2MonitorCapability] = {}
    for kind, raw in _mapping(source.get("charts"), "v2 capabilities charts").items():
        chart = _mapping(raw, f"v2 chart capability {kind}")
        group_by = _group_by_tuple(chart.get("group_by"), f"v2 chart {kind} group_by")
        partition_by = (
            _group_by_tuple(chart.get("partition_by"), f"v2 chart {kind} partition_by")
            if "partition_by" in chart
            else None
        )
        if partition_by is not None and kind != "ranking":
            raise CustomProtocolError("v2 partition_by is supported only by ranking")
        if "filters" in chart:
            raise CustomProtocolError(f"v2 chart {kind} must not declare filters")
        if kind == "monitor":
            window_seconds = chart.get("window_seconds")
            refresh = chart.get("refresh_interval_seconds")
            if (
                not isinstance(window_seconds, int)
                or isinstance(window_seconds, bool)
                or window_seconds < 1
            ):
                raise CustomProtocolError("v2 monitor window_seconds must be a positive integer")
            if refresh is not None and (
                not isinstance(refresh, int) or isinstance(refresh, bool) or refresh < 1
            ):
                raise CustomProtocolError(
                    "v2 monitor refresh_interval_seconds must be a positive integer"
                )
            charts[kind] = V2MonitorCapability(window_seconds, refresh, group_by, ())
            rate_label = chart.get("rate_label")
            if rate_label is not None:
                charts[kind] = V2MonitorCapability(
                    window_seconds,
                    refresh,
                    group_by,
                    (),
                    _parse_localized(rate_label, "v2 monitor rate_label"),
                )
        elif kind in {"timeline", "calendar", "stack", "ranking"}:
            periods = _string_tuple(chart.get("periods", []), f"v2 chart {kind} periods")
            for period in periods:
                if period != "all":
                    try:
                        if kind == "ranking":
                            try:
                                parse_subday_period(period)
                            except ValueError:
                                parse_period(period)
                        else:
                            parse_period(period)
                    except ValueError as exc:
                        raise CustomProtocolError(f"v2 chart {kind} period must be valid") from exc
            if kind != "ranking" and "all" in periods:
                raise CustomProtocolError("v2 all period is supported only by ranking")
            if "all" in periods and periods[-1] != "all":
                raise CustomProtocolError("v2 ranking all period must be last")
            max_items = chart.get("max_items")
            if max_items is not None and (
                kind != "ranking"
                or not isinstance(max_items, int)
                or isinstance(max_items, bool)
                or max_items < 1
            ):
                raise CustomProtocolError("v2 ranking max_items must be a positive integer")
            descriptions_default = chart.get("descriptions_default", "collapsed")
            if (
                kind != "ranking" and "descriptions_default" in chart
            ) or descriptions_default not in {"expanded", "collapsed"}:
                raise CustomProtocolError(
                    "v2 ranking descriptions_default must be expanded or collapsed"
                )
            comparison = chart.get("comparison", "full")
            if (kind != "ranking" and "comparison" in chart) or comparison not in {
                "full",
                "rank",
                "none",
            }:
                raise CustomProtocolError("v2 ranking comparison must be full, rank, or none")
            show_percentage = chart.get("show_percentage", True)
            if (kind != "ranking" and "show_percentage" in chart) or not isinstance(
                show_percentage, bool
            ):
                raise CustomProtocolError("v2 ranking show_percentage must be a boolean")
            sort_direction = chart.get("sort_direction", "descending")
            if (kind != "ranking" and "sort_direction" in chart) or sort_direction not in {
                "ascending",
                "descending",
            }:
                raise CustomProtocolError(
                    "v2 ranking sort_direction must be ascending or descending"
                )
            refresh_interval_seconds = chart.get("refresh_interval_seconds")
            if refresh_interval_seconds is not None and (
                not isinstance(refresh_interval_seconds, int)
                or isinstance(refresh_interval_seconds, bool)
                or refresh_interval_seconds < 1
            ):
                raise CustomProtocolError(
                    "v2 historical refresh_interval_seconds must be a positive integer"
                )
            charts[kind] = V2HistoricalChartCapability(
                (
                    ()
                    if kind == "ranking"
                    else _string_tuple(chart.get("granularities"), f"v2 chart {kind} granularities")
                ),
                group_by,
                (),
                periods,
                max_items,
                descriptions_default,  # type: ignore[arg-type]
                comparison,  # type: ignore[arg-type]
                show_percentage,
                refresh_interval_seconds,
                sort_direction,  # type: ignore[arg-type]
                partition_by,
            )
        else:
            raise CustomProtocolError(f"unsupported v2 chart capability: {kind}")
    _unique_ids(dimensions, "v2 group-by dimensions")
    if partition_dimensions is not None:
        _unique_ids(partition_dimensions, "v2 partition-by dimensions")
    partition_ids = {
        item.id
        for item in (partition_dimensions if partition_dimensions is not None else dimensions)
    }
    for capability in charts.values():
        if not isinstance(capability, V2HistoricalChartCapability):
            continue
        if capability.partition_by is not None:
            for identifier in capability.partition_by:
                if identifier is not None and identifier not in partition_ids:
                    raise CustomProtocolError(
                        "v2 ranking partition_by must reference a declared partition dimension"
                    )
    return V2MetricCapabilities(dimensions, (), charts, partition_dimensions)

def validate_partition_selection(
    partition_by: str | None,
    group_by: str | None,
    capability: V2HistoricalChartCapability | CustomChartCapability,
) -> None:
    """Validate one Ranking partition/group selection."""

    supported = capability.partition_by
    if supported is None:
        if partition_by is not None:
            raise CustomProtocolError("partition_by is not supported by this capability")
        return
    if partition_by not in supported:
        if partition_by is None:
            raise CustomProtocolError("partition_by is required by this capability")
        raise CustomProtocolError("partition_by is not supported by this capability")
    if partition_by is not None and group_by is None:
        raise CustomProtocolError("active partition_by requires a non-null group_by")
    if partition_by is not None and partition_by == group_by:
        raise CustomProtocolError("partition_by and group_by must differ")

def _parse_v2_defaults(
    value: object, capabilities: V2MetricCapabilities
) -> dict[str, CustomChartDefaults]:
    defaults: dict[str, CustomChartDefaults] = {}
    for kind, raw in _mapping(value, "v2 metric defaults").items():
        if kind not in {"timeline", "calendar", "stack", "ranking", "monitor"}:
            continue
        if not isinstance(raw, dict):
            continue
        declared = frozenset(raw)
        period = raw.get("period")
        if (
            not isinstance(period, str)
            or (period != "all" and _valid_period(period, subday=kind == "ranking") is False)
            or (period == "all" and kind != "ranking")
        ):
            period = None
        group_by = raw.get("group_by")
        if group_by is not None and not isinstance(group_by, str):
            group_by = None
        partition_by = raw.get("partition_by")
        if "partition_by" in raw:
            if kind != "ranking":
                raise CustomProtocolError("v2 default partition_by is supported only by ranking")
            if partition_by is not None and not isinstance(partition_by, str):
                raise CustomProtocolError("v2 default partition_by must be a string or null")
            capability = capabilities.charts.get(kind)
            if not isinstance(capability, V2HistoricalChartCapability):
                raise CustomProtocolError("v2 default partition_by requires a ranking capability")
            try:
                validate_partition_selection(partition_by, group_by, capability)
            except CustomProtocolError as exc:
                raise CustomProtocolError(f"v2 default {exc}") from exc
        else:
            partition_by = None
        top = raw.get("top")
        if not isinstance(top, int) or isinstance(top, bool) or top < 1:
            top = None
        granularity = raw.get("granularity")
        if kind == "ranking" or not isinstance(granularity, str):
            granularity = None
        filters = _default_filters(raw.get("filters"))
        other = raw.get("other") if raw.get("other") in {"show", "hide"} else None
        style = raw.get("style") if isinstance(raw.get("style"), str) else None
        theme = raw.get("theme") if isinstance(raw.get("theme"), str) else None
        window_seconds = _default_window_seconds(raw.get("window"))
        defaults[kind] = CustomChartDefaults(
            period,
            group_by,
            top,
            granularity,
            filters,
            other,
            style,
            theme,
            window_seconds,
            declared,
            partition_by,
        )
    return defaults

def _valid_period(value: str, *, subday: bool = False) -> bool:
    try:
        parse_period(value)
    except ValueError:
        if not subday:
            return False
        try:
            parse_subday_period(value)
        except ValueError:
            return False
    return True

def _default_filters(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict):
        return ()
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for filter_id, option_ids in value.items():
        if not isinstance(filter_id, str) or not isinstance(option_ids, list):
            continue
        options = tuple(sorted({item for item in option_ids if isinstance(item, str)}))
        if options:
            parsed.append((filter_id, options))
    return tuple(sorted(parsed))

def _default_window_seconds(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([1-9][0-9]*)([mh])", value)
    if match is None:
        return None
    seconds = int(match.group(1)) * (60 if match.group(2) == "m" else 3600)
    return seconds if 5 * 60 <= seconds <= 24 * 3600 else None

def _parse_environment_declaration(value: object) -> CustomEnvironmentDeclaration:
    source = _mapping(value, "environment declaration")
    expected = {"name", "required", "sensitive", "label", "how_to_get"}
    if set(source) - (expected | {"help_url"}) or not expected <= set(source):
        raise CustomProtocolError("environment declaration has invalid fields")
    required = source["required"]
    sensitive = source["sensitive"]
    if not isinstance(required, bool) or not isinstance(sensitive, bool):
        raise CustomProtocolError("environment declaration required and sensitive must be booleans")
    help_url = source.get("help_url")
    if help_url is not None:
        help_url = _string(help_url, "environment declaration help_url")
    return CustomEnvironmentDeclaration(
        _string(source["name"], "environment declaration name"),
        required,
        sensitive,
        _parse_localized(source["label"], "environment declaration label"),
        _parse_localized(source["how_to_get"], "environment declaration how_to_get"),
        help_url,
    )

def _parse_dimension(value: object, name: str) -> CustomDimension:
    source = _mapping(value, name)
    return CustomDimension(
        _string(source.get("id"), f"{name} ID"),
        _parse_localized(source.get("label"), f"{name} label"),
    )

def _parse_filter(value: object) -> CustomFilter:
    source = _mapping(value, "filter")
    mode = source.get("mode", "multi_select")
    if mode not in {"multi_select", "single_select"}:
        raise CustomProtocolError("custom filter mode must be multi_select or single_select")
    options = tuple(
        _parse_dimension(item, "filter option")
        for item in _sequence(source.get("options"), "filter options")
    )
    _unique_ids(options, "filter options")
    return CustomFilter(
        _string(source.get("id"), "filter ID"),
        _parse_localized(source.get("label"), "filter label"),
        tuple(CustomFilterOption(item.id, item.label) for item in options),
        mode,  # type: ignore[arg-type]
    )

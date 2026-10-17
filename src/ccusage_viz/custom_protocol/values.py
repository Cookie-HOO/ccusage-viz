from __future__ import annotations

from ccusage_viz.custom_models import (
    CustomComparison,
    CustomData,
    CustomPoint,
    CustomRankingEntry,
    CustomRankingGroup,
    CustomSeries,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    LocalizedText,
    V2MetricValue,
    V2MonitorObservation,
    V2RankingData,
    V2RankingGroup,
)
from ccusage_viz.custom_protocol.primitives import (
    CustomProtocolError,
    _mapping,
    _parse_date,
    _parse_decimal,
    _parse_https_url,
    _parse_localized,
    _parse_timestamp,
    _sequence,
    _string,
    _unique_ids,
)


def _parse_data(
    value: object,
    *,
    descriptions_allowed: bool = False,
    partitioned: bool = False,
    max_items: int | None = None,
) -> CustomData:
    source = _mapping(value, "data")
    if "series" in source and "groups" in source:
        raise CustomProtocolError("data series and groups are mutually exclusive")
    if partitioned:
        groups = tuple(
            _parse_ranking_group(item, index=index)
            for index, item in enumerate(_sequence(source.get("groups"), "data groups"))
        )
        _unique_ids(groups, "data groups")
        item_count = sum(len(group.series) for group in groups)
        if max_items is not None and item_count > max_items:
            raise CustomProtocolError(f"data must not contain more than {max_items} series")
        return CustomData(groups=groups)
    series = tuple(
        _parse_series(
            item,
            descriptions_allowed=descriptions_allowed,
            name=f"data.series[{index}]" if "groups" in source else "series",
        )
        for index, item in enumerate(_sequence(source.get("series"), "data series"))
    )
    _unique_ids(series, "data series")
    if max_items is not None and len(series) > max_items:
        raise CustomProtocolError(f"data must not contain more than {max_items} series")
    return CustomData(series)

def _parse_ranking_group(value: object, *, index: int) -> CustomRankingGroup:
    name = f"data.groups[{index}]"
    source = _mapping(value, name)
    series = tuple(
        _parse_series(
            item,
            descriptions_allowed=True,
            name=f"{name}.series[{series_index}]",
        )
        for series_index, item in enumerate(_sequence(source.get("series"), f"{name}.series"))
    )
    _unique_ids(series, f"{name}.series")
    return CustomRankingGroup(
        _string(source.get("id"), f"{name}.id"),
        _parse_localized(source.get("label"), f"{name}.label"),
        series,
        _parse_localized(source["description"], f"{name}.description")
        if "description" in source
        else None,
        _parse_localized(source["display"], f"{name}.display") if "display" in source else None,
        _parse_localized(source["comparison_display"], f"{name}.comparison_display")
        if "comparison_display" in source
        else None,
        _parse_https_url(source["link"], f"{name}.link") if "link" in source else None,
    )

def _parse_v2_ranking_data(
    value: object, *, partitioned: bool, max_items: int | None
) -> V2RankingData:
    source = _mapping(value, "data")
    if "series" in source and "groups" in source:
        raise CustomProtocolError("data series and groups are mutually exclusive")
    if partitioned:
        groups = tuple(
            _parse_v2_ranking_group(item, index=index)
            for index, item in enumerate(_sequence(source.get("groups"), "data groups"))
        )
        _unique_ids(groups, "data groups")
        count = sum(len(group.series) for group in groups)
        if max_items is not None and count > max_items:
            raise CustomProtocolError(f"data must not contain more than {max_items} series")
        return V2RankingData(groups=groups)
    series = tuple(
        _parse_v2_ranking_entry(item, name=f"data.series[{index}]")
        for index, item in enumerate(_sequence(source.get("series"), "data series"))
    )
    _unique_ids(series, "data series")
    if max_items is not None and len(series) > max_items:
        raise CustomProtocolError(f"data must not contain more than {max_items} series")
    return V2RankingData(series=series)

def _parse_v2_ranking_group(value: object, *, index: int) -> V2RankingGroup:
    name = f"data.groups[{index}]"
    source = _mapping(value, name)
    series = tuple(
        _parse_v2_ranking_entry(item, name=f"{name}.series[{series_index}]")
        for series_index, item in enumerate(_sequence(source.get("series"), f"{name}.series"))
    )
    _unique_ids(series, f"{name}.series")
    return V2RankingGroup(
        _string(source.get("id"), f"{name}.id"),
        _parse_localized(source.get("label"), f"{name}.label"),
        series,
        _parse_localized(source["description"], f"{name}.description")
        if "description" in source
        else None,
        _parse_localized(source["display"], f"{name}.display") if "display" in source else None,
        _parse_localized(source["comparison_display"], f"{name}.comparison_display")
        if "comparison_display" in source
        else None,
        _parse_https_url(source["link"], f"{name}.link") if "link" in source else None,
    )

def _parse_v2_ranking_entry(value: object, *, name: str) -> CustomRankingEntry:
    source = _mapping(value, name)
    if "points" in source:
        raise CustomProtocolError(f"{name} must use scalar value and must not contain points")
    return CustomRankingEntry(
        _string(source.get("id"), f"{name}.id"),
        _parse_localized(source.get("label"), f"{name}.label"),
        _parse_decimal(source.get("value"), f"{name}.value"),
        _parse_localized(source["description"], f"{name}.description")
        if "description" in source
        else None,
        _parse_localized(source["display"], f"{name}.display") if "display" in source else None,
        _parse_localized(source["comparison_display"], f"{name}.comparison_display")
        if "comparison_display" in source
        else None,
        _parse_https_url(source["link"], f"{name}.link") if "link" in source else None,
    )

def _normalized_localized(source: object, key: str) -> LocalizedText | None:
    """Parse an optional localized field, normalising whitespace-only values to None."""
    value = source.get(key, None) if isinstance(source, dict) else None
    if value is None:
        return None
    result = _parse_localized(value, f"v2 monitor group {key}")
    if not (result.en.strip() or result.zh_cn.strip()):
        return None
    return result

def _parse_v2_monitor_observation(value: object) -> V2MonitorObservation:
    source = _mapping(value, "v2 monitor observation")
    end_at = _parse_timestamp(source.get("end_at"), "v2 monitor observation end_at")
    groups = tuple(
        V2MetricValue(
            _string(item.get("id"), "v2 monitor group ID"),
            _parse_localized(item.get("label"), "v2 monitor group label"),
            _parse_decimal(item.get("value"), "v2 monitor group value"),
            _normalized_localized(item, "description"),
            _normalized_localized(item, "display"),
        )
        for raw in _sequence(source.get("groups"), "v2 monitor observation groups")
        for item in (_mapping(raw, "v2 monitor group"),)
    )
    if len({group.id for group in groups}) != len(groups):
        raise CustomProtocolError("v2 monitor group IDs must be unique")
    return V2MonitorObservation(
        end_at,
        _parse_decimal(source.get("total"), "v2 monitor observation total"),
        groups,
    )

def _parse_series(
    value: object, *, descriptions_allowed: bool, name: str = "series"
) -> CustomSeries:
    source = _mapping(value, name)
    if not descriptions_allowed and (
        {"description", "display", "comparison_display", "link"} & source.keys()
    ):
        raise CustomProtocolError("series presentation fields are supported only by ranking")
    points_name = f"{name}.points" if name != "series" else "series points"
    points = tuple(
        _parse_point(
            point,
            name=(f"{name}.points[{index}]" if name != "series" else "point"),
        )
        for index, point in enumerate(_sequence(source.get("points"), points_name))
    )
    if len({point.date for point in points}) != len(points):
        raise CustomProtocolError(f"{points_name} dates must be unique")

    def field(wire_name: str, flat_name: str | None = None) -> str:
        if name != "series":
            return f"{name}.{wire_name}"
        return f"series {flat_name or wire_name}"

    return CustomSeries(
        _string(source.get("id"), field("id", "ID")),
        _parse_localized(source.get("label"), field("label")),
        points,
        _parse_localized(source["description"], field("description"))
        if "description" in source
        else None,
        _parse_localized(source["display"], field("display")) if "display" in source else None,
        _parse_localized(
            source["comparison_display"], field("comparison_display", "comparison display")
        )
        if "comparison_display" in source
        else None,
        _parse_https_url(source["link"], field("link")) if "link" in source else None,
    )

def _parse_point(value: object, *, name: str = "point") -> CustomPoint:
    source = _mapping(value, name)
    separator = "." if name != "point" else " "
    return CustomPoint(
        _parse_date(source.get("date"), f"{name}{separator}date"),
        _parse_decimal(source.get("value"), f"{name}{separator}value"),
    )

def _parse_summary(value: object) -> CustomSummary:
    source = _mapping(value, "summary")
    metric = _mapping(source.get("metric"), "metric")
    current = _mapping(metric.get("current"), "metric current")
    return CustomSummary(
        CustomSummaryMetric(
            _string(metric.get("id"), "metric ID"),
            _parse_localized(metric.get("label"), "metric label"),
            CustomSummaryCurrent(
                _parse_decimal(current.get("value"), "metric current value"),
                _parse_localized(current.get("display"), "metric current display"),
            ),
            _parse_comparison(metric.get("sequential"), "sequential comparison"),
            _parse_comparison(metric.get("year_over_year"), "year-over-year comparison"),
        )
    )

def _parse_comparison(value: object, name: str) -> CustomComparison:
    source = _mapping(value, name)
    status = _string(source.get("status"), f"{name} status")
    if status not in {"ready", "pending", "unavailable"}:
        raise CustomProtocolError(f"invalid {name} status: {status}")
    has_base = "base_value" in source
    if status == "ready":
        if not has_base:
            raise CustomProtocolError(f"ready {name} requires base_value")
        base = _parse_decimal(source["base_value"], f"{name} base_value")
    else:
        if has_base:
            raise CustomProtocolError(f"{status} {name} must omit base_value")
        base = None
    return CustomComparison(status, base)  # type: ignore[arg-type]

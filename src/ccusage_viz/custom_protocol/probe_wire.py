from __future__ import annotations

from ccusage_viz.custom_models import (
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
    V2HistoricalChartCapability,
    V2MonitorCapability,
    V2ProbeDescriptor,
)


def probe_descriptor_to_wire(descriptor: CustomProbeDescriptor) -> dict[str, object]:
    """Serialize the safe static metadata persisted for a managed Dataset."""

    def localized(value: LocalizedText) -> dict[str, str]:
        return {"en": value.en, "zh-CN": value.zh_cn}

    def unit(value: CustomUnit) -> dict[str, object]:
        return {
            "id": value.id,
            "label": localized(value.label),
            "placement": value.placement,
            "decimal_places": value.decimal_places,
        }

    def dataset(value: CustomDataset) -> dict[str, object]:
        return {
            "title": localized(value.title),
            "description": localized(value.description),
            "unit": unit(value.unit),
        }

    capabilities = {
        "group_by": [
            {"id": item.id, "label": localized(item.label)}
            for item in descriptor.capabilities.group_by
        ],
        "filters": [
            {
                "id": item.id,
                "label": localized(item.label),
                "mode": item.mode,
                "options": [
                    {"id": option.id, "label": localized(option.label)} for option in item.options
                ],
            }
            for item in descriptor.capabilities.filters
        ],
        "charts": {
            kind: {
                "granularities": list(value.granularities),
                "group_by": list(value.group_by),
                "filters": list(value.filters),
                **(
                    {"descriptions_default": value.descriptions_default}
                    if kind == "ranking" and value.descriptions_default != "collapsed"
                    else {}
                ),
                **({"comparison": value.comparison} if value.comparison != "full" else {}),
                **(
                    {"show_percentage": False}
                    if kind == "ranking" and not value.show_percentage
                    else {}
                ),
                **(
                    {"refresh_interval_seconds": value.refresh_interval_seconds}
                    if value.refresh_interval_seconds is not None
                    else {}
                ),
            }
            for kind, value in sorted(descriptor.capabilities.charts.items())
        },
    }
    return {
        "revision": descriptor.revision,
        "version": descriptor.version,
        **(
            {"source_timezone": descriptor.source_timezone}
            if descriptor.source_timezone is not None
            else {}
        ),
        "dataset": dataset(descriptor.dataset),
        "capabilities": capabilities,
        "defaults": {
            kind: {"period": value.period, "group_by": value.group_by, "top": value.top}
            for kind, value in sorted(descriptor.defaults.items())
        },
        "environment": [
            {
                "name": item.name,
                "required": item.required,
                "sensitive": item.sensitive,
                "label": localized(item.label),
                "how_to_get": localized(item.how_to_get),
                **({"help_url": item.help_url} if item.help_url is not None else {}),
            }
            for item in descriptor.environment
        ],
    }


def v2_probe_descriptor_to_wire(descriptor: V2ProbeDescriptor) -> dict[str, object]:
    """Serialize safe V2 descriptor metadata for a local registration snapshot."""

    def localized(value: LocalizedText) -> dict[str, str]:
        return {"en": value.en, "zh-CN": value.zh_cn}

    def unit(value: CustomUnit) -> dict[str, object]:
        return {
            "id": value.id,
            "label": localized(value.label),
            "placement": value.placement,
            "decimal_places": value.decimal_places,
        }

    def capability(
        value: V2HistoricalChartCapability | V2MonitorCapability, *, ranking: bool = False
    ) -> dict[str, object]:
        common = {"group_by": list(value.group_by)}
        if isinstance(value, V2MonitorCapability):
            return {
                **common,
                "window_seconds": value.window_seconds,
                **(
                    {"refresh_interval_seconds": value.refresh_interval_seconds}
                    if value.refresh_interval_seconds is not None
                    else {}
                ),
                **(
                    {"rate_label": localized(value.rate_label)}
                    if value.rate_label is not None
                    else {}
                ),
            }
        return {
            **common,
            **({} if ranking else {"granularities": list(value.granularities)}),
            **(
                {"partition_by": list(value.partition_by)} if value.partition_by is not None else {}
            ),
            **({"periods": list(value.periods)} if value.periods else {}),
            **({"max_items": value.max_items} if value.max_items is not None else {}),
            **(
                {"descriptions_default": value.descriptions_default}
                if value.descriptions_default != "collapsed"
                else {}
            ),
            **({"comparison": value.comparison} if value.comparison != "full" else {}),
            **({"show_percentage": False} if not value.show_percentage else {}),
            **(
                {"sort_direction": value.sort_direction}
                if value.sort_direction != "descending"
                else {}
            ),
            **(
                {"refresh_interval_seconds": value.refresh_interval_seconds}
                if value.refresh_interval_seconds is not None
                else {}
            ),
        }

    return {
        "revision": descriptor.revision,
        "version": descriptor.version,
        **({"source_timezone": descriptor.source_timezone} if descriptor.source_timezone else {}),
        "dataset": {
            "title": localized(descriptor.dataset.title),
            "description": localized(descriptor.dataset.description),
        },
        **(
            {
                "metric_groups": [
                    {"id": group.id, "title": localized(group.title)}
                    for group in descriptor.metric_groups
                ]
            }
            if descriptor.metric_groups
            else {}
        ),
        "metrics": [
            {
                "id": metric.id,
                "title": localized(metric.title),
                "description": localized(metric.description),
                "unit": unit(metric.unit),
                "aggregation": metric.aggregation,
                "capabilities": {
                    "group_by": [
                        {"id": item.id, "label": localized(item.label)}
                        for item in metric.capabilities.group_by
                    ],
                    **(
                        {
                            "partition_by": [
                                {"id": item.id, "label": localized(item.label)}
                                for item in metric.capabilities.partition_by
                            ]
                        }
                        if metric.capabilities.partition_by is not None
                        else {}
                    ),
                    "charts": {
                        kind: capability(item, ranking=kind == "ranking")
                        for kind, item in metric.capabilities.charts.items()
                    },
                },
                "defaults": {
                    kind: _defaults_to_wire(item, ranking=kind == "ranking")
                    for kind, item in metric.defaults.items()
                },
                "summary": metric.summary,
                **({"group_id": metric.group_id} if metric.group_id is not None else {}),
            }
            for metric in descriptor.metrics
        ],
        **(
            {"default_metric_id": descriptor.default_metric_id}
            if descriptor.default_metric_id
            else {}
        ),
        "environment": [
            {
                "name": item.name,
                "required": item.required,
                "sensitive": item.sensitive,
                "label": localized(item.label),
                "how_to_get": localized(item.how_to_get),
                **({"help_url": item.help_url} if item.help_url else {}),
            }
            for item in descriptor.environment
        ],
    }


def _defaults_to_wire(value: CustomChartDefaults, *, ranking: bool = False) -> dict[str, object]:
    declared = value.declared or frozenset({"period", "group_by", "top"})
    fields: dict[str, object] = {}
    for name, item in (
        ("period", value.period),
        ("group_by", value.group_by),
        ("partition_by", value.partition_by),
        ("top", value.top),
        ("granularity", value.granularity),
        ("other", value.other),
        ("style", value.style),
        ("theme", value.theme),
    ):
        if name in declared and not (ranking and name == "granularity"):
            fields[name] = item
    if "window" in declared and value.window_seconds is not None:
        suffix = "h" if value.window_seconds % 3600 == 0 else "m"
        divisor = 3600 if suffix == "h" else 60
        fields["window"] = f"{value.window_seconds // divisor}{suffix}"
    if "filters" in declared and value.filters:
        fields["filters"] = {filter_id: list(options) for filter_id, options in value.filters}
    return fields

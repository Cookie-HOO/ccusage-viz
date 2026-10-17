from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomRankingEntry,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2ProbeDescriptor,
    V2RankingData,
    V2RankingGroup,
    V2Runtime,
)
from ccusage_viz.custom_protocol.responses import V2ChartResponse
from ccusage_viz.data_view import custom_data_payload, render_custom_data
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_ranking import process_custom_ranking


def entry(identifier: str, value: str) -> CustomRankingEntry:
    return CustomRankingEntry(identifier, LocalizedText(identifier, identifier), Decimal(value))


def response(data: V2RankingData, *, direction: str = "descending") -> V2ChartResponse:
    text = LocalizedText("Requests", "请求")
    unit = CustomUnit("request", text, "suffix", 0)
    capability = V2HistoricalChartCapability(
        (),
        ("route",),
        (),
        sort_direction=direction,  # type: ignore[arg-type]
    )
    metric = V2MetricDescriptor(
        "requests",
        text,
        text,
        unit,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability}),
        {},
    )
    return V2ChartResponse(
        "requests",
        data,
        V2ProbeDescriptor("1", "1", V2Dataset(text, text), (metric,), ()),
        V2Runtime(()),
    )


def config(**changes: object) -> CustomChartConfig:
    values: dict[str, object] = {
        "kind": "ranking",
        "source": CustomCommandSource("routes", ("routes",)),
        "metric_id": "requests",
        "date_range": DateRange(date(2026, 10, 1), date(2026, 10, 2)),
        "presentation": ChartPresentation(theme="no-color"),
        "group_by": "route",
        "top": 1,
        "other": "show",
    }
    values.update(changes)
    return CustomChartConfig(**values)  # type: ignore[arg-type]


def test_scalar_flat_top_other_has_no_temporal_axis() -> None:
    projection = process_custom_ranking(
        response(V2RankingData((entry("a", "100"), entry("b", "200"), entry("c", "50")))),
        config(),
    )

    assert [item.id for item in projection.series] == ["b", "other"]
    assert [item.value for item in projection.series] == [Decimal("200"), Decimal("150")]
    assert projection.series[0].total == Decimal("200")
    assert not hasattr(projection, "days")
    assert not hasattr(projection.series[0], "values")


def test_scalar_grouped_projection_preserves_order_and_scopes_comparison() -> None:
    current = response(
        V2RankingData(
            groups=(
                V2RankingGroup(
                    "one", LocalizedText("One", "一"), (entry("same", "9"), entry("x", "2"))
                ),
                V2RankingGroup(
                    "two", LocalizedText("Two", "二"), (entry("same", "3"), entry("y", "4"))
                ),
            )
        )
    )
    previous = response(
        V2RankingData(
            groups=(
                V2RankingGroup("one", LocalizedText("One", "一"), (entry("same", "8"),)),
                V2RankingGroup("two", LocalizedText("Two", "二"), (entry("same", "1"),)),
            )
        )
    )

    projection = process_custom_ranking(
        current,
        replace(config(), top=None, other="hide"),
        comparison_response=previous,
        comparison_config=replace(config(), top=None, other="hide"),
    )

    assert projection.groups is not None
    assert [group.id for group in projection.groups] == ["one", "two"]
    assert projection.groups[0].series[0].previous_total == Decimal("8")
    assert projection.groups[1].series[1].previous_total == Decimal("1")
    assert projection.groups[0].total == Decimal("11")
    assert projection.groups[1].maximum == Decimal("4")


def test_component_dispatches_v2_ranking_to_scalar_projection() -> None:
    chart = config(top=None, other="hide")
    component = CustomHistoricalComponent(chart)
    payload = response(V2RankingData((entry("route", "42"),)))

    assert component.apply_provider_result(SimpleNamespace(custom_response=payload))
    assert component.model is not None
    assert not hasattr(component.model, "days")
    assert component.model.series[0].value == Decimal("42")  # type: ignore[union-attr]


def test_component_attaches_scalar_comparison_using_issued_request_config() -> None:
    component = CustomHistoricalComponent(config(top=None, other="hide"))
    assert component.apply_provider_result(
        SimpleNamespace(custom_response=response(V2RankingData((entry("route", "42"),))))
    )
    issued = component.start_comparison()
    assert issued is not None

    assert component.apply_provider_result(
        SimpleNamespace(custom_response=response(V2RankingData((entry("route", "30"),)))),
        purpose="comparison",
        comparison_request_config=issued,
    )

    assert component.model is not None
    assert component.model.comparison_available
    assert component.model.series[0].previous_total == Decimal("30")  # type: ignore[union-attr]


def test_component_attaches_grouped_scalar_comparison_using_issued_request_config() -> None:
    current = V2RankingData(
        groups=(V2RankingGroup("api", LocalizedText("API", "接口"), (entry("read", "42"),)),)
    )
    previous = V2RankingData(
        groups=(V2RankingGroup("api", LocalizedText("API", "接口"), (entry("read", "30"),)),)
    )
    component = CustomHistoricalComponent(config(top=None, other="hide"))
    assert component.apply_provider_result(SimpleNamespace(custom_response=response(current)))
    issued = component.start_comparison()
    assert issued is not None

    assert component.apply_provider_result(
        SimpleNamespace(custom_response=response(previous)),
        purpose="comparison",
        comparison_request_config=issued,
    )

    assert component.model is not None
    assert component.model.groups is not None  # type: ignore[union-attr]
    assert component.model.groups[0].series[0].previous_total == Decimal("30")  # type: ignore[union-attr]


def test_scalar_flat_data_views_have_no_fabricated_time_axis() -> None:
    projection = process_custom_ranking(
        response(V2RankingData((entry("a", "10"), entry("b", "5")))),
        config(top=None, other="hide"),
    )

    payload = custom_data_payload(projection, language="en")
    table = render_custom_data(projection, language="en", translator=load_translator("en"))

    assert "range" not in payload
    assert "granularity" not in payload
    assert payload["rows"] == [
        {"rank": 1, "series_id": "a", "series": "a", "is_other": False, "value": "10"},
        {"rank": 2, "series_id": "b", "series": "b", "is_other": False, "value": "5"},
    ]
    assert table.splitlines()[0] == "| rank | series_id | series | is_other | value |"


def test_scalar_partition_data_views_render_partition_rows_without_time() -> None:
    projection = process_custom_ranking(
        response(
            V2RankingData(
                groups=(
                    V2RankingGroup("api", LocalizedText("API", "接口"), (entry("read", "7"),)),
                    V2RankingGroup("web", LocalizedText("Web", "网页"), (entry("write", "3"),)),
                )
            )
        ),
        config(top=None, other="hide"),
    )

    payload = custom_data_payload(projection, language="zh")

    assert "range" not in payload
    assert "granularity" not in payload
    assert payload["rows"] == [
        {
            "partition_id": "api",
            "partition": "接口",
            "rank": 1,
            "series_id": "read",
            "series": "read",
            "is_other": False,
            "value": "7",
        },
        {
            "partition_id": "web",
            "partition": "网页",
            "rank": 1,
            "series_id": "write",
            "series": "write",
            "is_other": False,
            "value": "3",
        },
    ]


def test_scalar_projection_ascending_is_stable_by_id_and_supports_signed_values() -> None:
    projection = process_custom_ranking(
        response(
            V2RankingData((entry("b", "-2"), entry("a", "-2"), entry("c", "3"))),
            direction="ascending",
        ),
        config(top=None, other="hide"),
    )

    assert [item.id for item in projection.series] == ["a", "b", "c"]

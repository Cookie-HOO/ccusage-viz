from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest

import ccusage_viz.custom_component as custom_component_module
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import (
    CustomCompletion,
    CustomHistoricalComponent,
    custom_date_summary_supported,
    custom_projection_replacement_required,
    custom_replacement_required,
    custom_summary_replacement_required,
)
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomData,
    CustomPoint,
    CustomProtocolFailure,
    CustomProtocolWarning,
    CustomSeries,
    LocalizedText,
)
from ccusage_viz.custom_protocol.responses import (
    CustomChartResponse,
    CustomPaneResponse,
    CustomSummaryResponse,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, CustomCommandSource, Density
from ccusage_viz.processing.custom_historical import (
    CustomProjectionError,
    process_custom_historical,
)
from ccusage_viz.render import custom
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_projection
from ccusage_viz.render.summary import format_custom_value, render_custom_summary

from .helpers import RANGE, UNIT, _grouped_response, config, response, v2_chart_response


def test_primary_response_retains_its_protocol_warnings() -> None:
    component = CustomHistoricalComponent(config())
    warning = CustomProtocolWarning("coverage", LocalizedText("using 2d", "使用 2 天"))
    source = response()
    warned = CustomPaneResponse(
        source.dataset, source.capabilities, source.data, source.summary, warnings=(warning,)
    )

    assert component.accept_response(warned)
    assert component.accepted_warnings == (warning,)


def test_warning_free_primary_response_clears_accepted_warnings() -> None:
    component = CustomHistoricalComponent(config())
    warning = CustomProtocolWarning("coverage", LocalizedText("using 2d", "使用 2 天"))
    source = response()
    warned = CustomPaneResponse(
        source.dataset, source.capabilities, source.data, source.summary, warnings=(warning,)
    )
    assert component.accept_response(warned)

    assert component.accept_response(response())
    assert component.accepted_warnings == ()


def test_projection_rejects_manually_constructed_partition_selection_outside_capability() -> None:
    source = _grouped_response((("one", (("a", "1"),)),))

    with pytest.raises(CustomProjectionError, match="partition_by is not supported"):
        process_custom_historical(
            source,
            config(
                kind="ranking",
                partition_by="unsupported",
                group_by="real_model",
                top=None,
            ),
        )


def test_projection_rejects_manually_constructed_flat_selection_for_required_partition() -> None:
    source = _grouped_response((("one", (("a", "1"),)),))

    with pytest.raises(CustomProjectionError, match="partition_by is required"):
        process_custom_historical(
            source,
            config(kind="ranking", partition_by=None, group_by="real_model", top=None),
        )


def test_grouped_projection_preserves_dataset_order_and_projects_each_group() -> None:
    projection = process_custom_historical(
        _grouped_response(
            (
                ("small-first", (("d", "1"), ("b", "3"), ("a", "4"), ("c", "2"))),
                ("large-second", (("a", "400"), ("b", "300"), ("c", "200"), ("d", "100"))),
                ("empty", ()),
            )
        ),
        config(
            kind="ranking",
            partition_by="logical_model",
            group_by="real_model",
            top=2,
            other="show",
        ),
    )

    assert projection.series == ()
    assert projection.groups is not None
    assert [group.id for group in projection.groups] == [
        "small-first",
        "large-second",
        "empty",
    ]
    first, second, empty = projection.groups
    assert [(item.id, item.total, item.rank) for item in first.series] == [
        ("a", Decimal("4"), 1),
        ("b", Decimal("3"), 2),
        ("other", Decimal("3"), None),
    ]
    assert first.total == Decimal("10") and first.maximum == Decimal("4")
    assert second.total == Decimal("1000") and second.maximum == Decimal("400")
    assert empty.series == () and empty.total == empty.maximum == Decimal()
    assert projection.total == Decimal("1010")
    assert first.description == LocalizedText("About small-first", "关于 small-first")
    assert first.display == LocalizedText("Total small-first", "总计 small-first")
    assert first.link == "https://example.com/small-first"


def test_grouped_projection_keeps_full_facts_when_other_is_hidden_and_supports_signed_values() -> (
    None
):
    source = _grouped_response(
        (("signed", (("positive", "5"), ("negative", "-2"), ("more-negative", "-4"))),)
    )
    base = config(
        kind="ranking",
        partition_by="logical_model",
        group_by="real_model",
        top=1,
    )

    shown = process_custom_historical(source, replace(base, other="show"))
    hidden = process_custom_historical(source, replace(base, other="hide"))

    assert shown.groups is not None and hidden.groups is not None
    shown_group, hidden_group = shown.groups[0], hidden.groups[0]
    assert shown_group.total == hidden_group.total == Decimal("-1")
    assert shown_group.maximum == hidden_group.maximum == Decimal("5")
    assert shown_group.series[-1].is_other
    assert shown_group.series[-1].total == Decimal("-6")
    assert [item.id for item in hidden_group.series] == ["positive"]


def test_grouped_projection_preserves_zero_totals_and_deterministic_ranks() -> None:
    projection = process_custom_historical(
        _grouped_response((("zeroes", (("b", "0"), ("a", "0"))),)),
        config(
            kind="ranking",
            partition_by="logical_model",
            group_by="real_model",
            top=None,
        ),
    )

    assert projection.groups is not None
    group = projection.groups[0]
    assert [(item.id, item.total, item.rank) for item in group.series] == [
        ("a", Decimal(), 1),
        ("b", Decimal(), 2),
    ]
    assert group.total == group.maximum == Decimal()


def test_grouped_projection_sorts_ties_and_ascending_values_independently() -> None:
    projection = process_custom_historical(
        _grouped_response(
            (("one", (("z", "2"), ("b", "1"), ("a", "1"))), ("two", (("x", "-1"),))),
            ascending=True,
        ),
        config(
            kind="ranking",
            partition_by="logical_model",
            group_by="real_model",
            top=None,
        ),
    )

    assert projection.groups is not None
    assert [[item.id for item in group.series] for group in projection.groups] == [
        ["a", "b", "z"],
        ["x"],
    ]
    assert [[item.rank for item in group.series] for group in projection.groups] == [[1, 2, 3], [1]]
    assert projection.groups[1].maximum == Decimal("-1")


def test_grouped_projection_matches_previous_within_group_and_treats_moves_as_new() -> None:
    current = _grouped_response(
        (("one", (("shared", "5"), ("moved", "4"))), ("two", (("moved", "3"),)))
    )
    previous = _grouped_response(
        (("one", (("shared", "2"),)), ("old", (("moved", "9"),))),
        point_date=date(2026, 8, 30),
    )
    chart = config(
        kind="ranking",
        partition_by="logical_model",
        group_by="real_model",
        top=None,
    )
    projection = process_custom_historical(
        current,
        chart,
        comparison_response=previous,
        comparison_config=replace(
            chart, date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31))
        ),
    )

    assert projection.groups is not None
    one, two = projection.groups
    shared, moved_in_one = one.series
    assert one.comparison_ready and one.previous_total == Decimal("2")
    assert shared.comparison_ready and shared.previous_total == Decimal("2")
    assert not moved_in_one.comparison_ready and moved_in_one.previous_total is None
    assert not two.comparison_ready and two.previous_total is None
    assert not two.series[0].comparison_ready


def test_grouped_projection_scopes_repeated_inner_ids_to_their_group() -> None:
    current = _grouped_response((("one", (("shared", "5"),)), ("two", (("shared", "7"),))))
    previous = _grouped_response(
        (("one", (("shared", "2"),)), ("two", (("shared", "11"),))),
        point_date=date(2026, 8, 30),
    )
    chart = config(
        kind="ranking",
        partition_by="logical_model",
        group_by="real_model",
        top=None,
    )

    projection = process_custom_historical(
        current,
        chart,
        comparison_response=previous,
        comparison_config=replace(
            chart, date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31))
        ),
    )

    assert projection.groups is not None
    assert [group.series[0].previous_total for group in projection.groups] == [
        Decimal("2"),
        Decimal("11"),
    ]


def test_grouped_data_is_rejected_for_non_ranking_projection() -> None:
    with pytest.raises(CustomProjectionError, match="only by ranking"):
        process_custom_historical(
            _grouped_response((("one", (("a", "1"),)),)),
            config(kind="timeline", partition_by=None, group_by=None),
        )


def test_top_n_and_other_are_local_decimal_operations() -> None:
    projection = process_custom_historical(response(), config())

    assert [series.label.en for series in projection.series] == ["a", "b", "Other"]
    assert projection.series[-1].label.zh_cn == "其他"
    assert projection.series[-1].values[0] == Decimal("2")
    assert projection.series[-1].values[1] == Decimal("0")


def test_projection_rejects_selected_filter_option_outside_capabilities() -> None:
    with pytest.raises(CustomProjectionError, match="filter options"):
        process_custom_historical(response(), config(filters=(("genre", ("unknown",)),)))


def test_projection_accepts_and_accumulates_overlapping_month_bucket() -> None:
    monthly = replace(
        response((("total", "0"),)),
        capabilities=CustomCapabilities(
            (), (), {"timeline": CustomChartCapability(("month",), (), ())}
        ),
        data=CustomData(
            (
                CustomSeries(
                    "total",
                    LocalizedText("Total", "总计"),
                    (
                        CustomPoint(date(2026, 9, 1), Decimal("1.25")),
                        CustomPoint(date(2026, 9, 17), Decimal("2.75")),
                    ),
                ),
            )
        ),
    )
    chart = config(
        group_by=None,
        top=None,
        granularity="month",
        date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30)),
    )

    projection = process_custom_historical(monthly, chart)

    assert projection.days == (date(2026, 9, 1),)
    assert projection.series[0].values == (Decimal("4.00"),)


def test_projection_rejects_non_overlapping_aggregation_bucket() -> None:
    monthly = replace(
        response((("total", "1"),), point_date=date(2026, 8, 1)),
        capabilities=CustomCapabilities(
            (), (), {"timeline": CustomChartCapability(("month",), (), ())}
        ),
    )
    chart = config(
        group_by=None,
        top=None,
        granularity="month",
        date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30)),
    )

    with pytest.raises(CustomProjectionError, match="outside the requested range"):
        process_custom_historical(monthly, chart)


def test_primary_v1_response_clears_previously_accepted_v2_metadata() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.apply_provider_result(
        SimpleNamespace(custom_response=v2_chart_response("stars"))
    )
    assert component.v2_descriptor is not None

    assert component.apply_provider_result(SimpleNamespace(custom_response=response()))

    assert component.v2_descriptor is None


def test_component_accepts_provider_chart_response_without_legacy_summary() -> None:
    legacy = response()
    chart = CustomChartResponse(legacy.dataset, legacy.capabilities, legacy.data)
    component = CustomHistoricalComponent(config())

    assert component.apply_provider_result(SimpleNamespace(custom_response=chart))
    assert component.accepted_response is chart


def test_component_rejects_provider_summary_response_for_chart() -> None:
    component = CustomHistoricalComponent(config())
    summary = CustomSummaryResponse(response().summary)

    with pytest.raises(TypeError, match="chart response"):
        component.apply_provider_result(SimpleNamespace(custom_response=summary))


def test_timestamp_completion_for_distinct_dst_fold_instant_is_rejected() -> None:
    zone = ZoneInfo("America/New_York")
    first = config(
        kind="ranking",
        metric_id="reading_time",
        date_range=TimestampRange(
            datetime(2026, 11, 1, 0, 30, tzinfo=zone),
            datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
            relative_until=True,
            period="1h",
        ),
    )
    component = CustomHistoricalComponent(first)
    second = replace(
        first,
        date_range=TimestampRange(
            datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
            datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1),
            relative_until=True,
            period="1h",
        ),
    )
    component.configure(second, data_affecting=True)

    assert not component.apply_result(CustomCompletion(component.generation, first, response()))
    assert component.accepted_config is None


def test_timestamp_completion_for_an_older_exact_range_is_rejected() -> None:
    first_end = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    first = config(
        kind="ranking",
        metric_id="reading_time",
        date_range=TimestampRange(
            first_end - timedelta(minutes=10),
            first_end,
            relative_until=True,
            period="10m",
        ),
    )
    component = CustomHistoricalComponent(first)
    newer = replace(
        first,
        date_range=TimestampRange(
            first_end - timedelta(minutes=5),
            first_end + timedelta(minutes=5),
            relative_until=True,
            period="10m",
        ),
    )
    component.configure(newer, data_affecting=True)

    assert not component.apply_result(CustomCompletion(component.generation, first, response()))
    assert component.accepted_config is None


def test_custom_failure_without_presentation_metadata_uses_chart_and_range_only() -> None:
    chart = config(
        group_by=None,
        metric_id="internal_metric_id",
        metric_titles=None,
        source=CustomCommandSource("internal_dataset_id", ("reader", "ccuv")),
    )

    rendered = custom.render_custom_failure(
        chart,
        RenderContext(120, 20, load_translator("en"), color=False),
    ).strip()

    assert rendered == "Timeline · 2026-09-01–2026-09-02"
    assert "internal_dataset_id" not in rendered
    assert "internal_metric_id" not in rendered


def test_date_only_summary_support_restores_after_leaving_subday_period() -> None:
    end = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    subday = config(
        kind="ranking",
        metric_id="reading_time",
        date_range=TimestampRange(
            end - timedelta(minutes=10), end, relative_until=True, period="10m"
        ),
    )

    assert not custom_date_summary_supported(subday)
    assert custom_date_summary_supported(replace(subday, date_range=RANGE))


def test_component_clears_accepted_projection_after_failed_source_replacement() -> None:
    component = CustomHistoricalComponent(config())
    accepted_at = datetime(2026, 9, 2, tzinfo=UTC)
    assert component.accept_response(response(), accepted_at=accepted_at)
    changed = replace(component.candidate, source=CustomCommandSource("other", ("other",)))
    component.configure(changed, data_affecting=True)

    assert component.is_pending
    assert component.fail(RuntimeError("source unavailable"), generation=component.generation)
    assert component.model is None
    assert component.accepted_config is None
    assert component.presentation is not None
    assert component.error is not None


def test_component_preserves_accepted_projection_after_same_query_refresh_failure() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    accepted = component.model

    assert component.fail(RuntimeError("source unavailable"), generation=component.generation)
    assert component.model is accepted


def test_component_clears_month_projection_after_week_replacement_failure() -> None:
    monthly = config(
        kind="ranking",
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 30), period="1mo"),
    )
    component = CustomHistoricalComponent(monthly)
    assert component.accept_response(response())
    weekly = replace(
        monthly, date_range=DateRange(date(2026, 9, 28), date(2026, 10, 5), period="1w")
    )
    component.configure(weekly, data_affecting=True)

    assert component.fail(RuntimeError("source unavailable"), generation=component.generation)
    assert component.model is None
    assert component.accepted_response is None
    assert component.presentation is not None
    assert component.candidate.date_range.period == "1w"


def test_period_unsupported_failure_clears_an_accepted_projection() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    failure = QueryError(
        "error.custom_command_protocol",
        custom_failure=CustomProtocolFailure(
            "unsupported_query",
            LocalizedText("Period unavailable", "周期不可用"),
            {"field": "range.period", "value": "14d"},
        ),
    )

    component.configure(replace(component.candidate, group_by="author"), data_affecting=True)

    assert component.fail(failure, generation=component.generation)
    assert component.model is None
    assert component.accepted_config is None
    assert component.accepted_response is None
    assert component.error is failure


def test_non_period_unsupported_failure_clears_the_replacement_projection() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    failure = QueryError(
        "error.custom_command_protocol",
        custom_failure=CustomProtocolFailure(
            "unsupported_query",
            LocalizedText("Grouping unavailable", "分组不可用"),
            {"field": "query.group_by", "value": "author"},
        ),
    )

    component.configure(replace(component.candidate, group_by="author"), data_affecting=True)
    assert component.fail(failure, generation=component.generation)
    assert component.model is None
    assert component.accepted_response is None
    assert component.error is failure


def test_custom_replacement_requires_only_source_query_fields() -> None:
    current = config()

    assert custom_replacement_required(current, replace(current, group_by=None))
    assert custom_replacement_required(current, replace(current, granularity="month"))
    assert not custom_replacement_required(
        replace(current, kind="ranking", metric_id="books"),
        replace(current, kind="ranking", metric_id="books", granularity="legacy"),
    )
    assert custom_replacement_required(current, replace(current, partition_by="collection"))
    assert custom_replacement_required(
        current, replace(current, filters=(("genre", ("fiction",)),))
    )
    assert not custom_replacement_required(current, replace(current, top=1))
    assert not custom_replacement_required(current, replace(current, other="hide"))
    assert not custom_replacement_required(
        current,
        replace(current, presentation=replace(current.presentation, theme="ocean")),
    )


@pytest.mark.parametrize(
    "updated",
    (
        lambda value: replace(value, top=1),
        lambda value: replace(value, other="hide"),
        lambda value: replace(value, ranking_comparison="none"),
    ),
)
def test_local_projection_changes_require_custom_reprojection(updated: object) -> None:
    current = config(kind="ranking", top=10)

    assert callable(updated)
    assert custom_projection_replacement_required(current, updated(current))


def test_custom_summary_replacement_requires_only_summary_query_fields() -> None:
    current = config()

    assert custom_summary_replacement_required(
        current, replace(current, source=CustomCommandSource("other", ("other",)))
    )
    assert custom_summary_replacement_required(
        current, replace(current, filters=(("genre", ("fiction",)),))
    )
    assert custom_summary_replacement_required(current, replace(current, granularity="month"))
    assert not custom_summary_replacement_required(
        replace(current, kind="ranking", metric_id="books"),
        replace(current, kind="ranking", metric_id="books", granularity="legacy"),
    )
    assert custom_summary_replacement_required(
        current,
        replace(
            current, date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2), fixed_bounds=True)
        ),
    )
    assert not custom_summary_replacement_required(current, replace(current, group_by=None))
    assert not custom_summary_replacement_required(current, replace(current, top=1))
    assert not custom_summary_replacement_required(current, replace(current, other="hide"))
    assert not custom_summary_replacement_required(
        current,
        replace(current, presentation=replace(current.presentation, theme="ocean")),
    )


def test_component_rejects_stale_response_without_mutation() -> None:
    component = CustomHistoricalComponent(config())
    component.configure(replace(component.candidate, group_by=None), data_affecting=True)

    assert not component.apply_result(CustomCompletion(0, config(), response()))
    assert component.model is None


def test_component_rejects_same_generation_response_for_different_candidate() -> None:
    component = CustomHistoricalComponent(config())
    candidate = replace(component.candidate, group_by=None)
    component.configure(candidate, data_affecting=True)

    assert not component.apply_result(CustomCompletion(component.generation, config(), response()))
    assert component.accepted_response is None
    assert component.accepted_config is None
    assert component.model is None


def test_component_reprojects_only_display_local_configuration() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    accepted_model = component.model
    accepted_config = component.accepted_config
    accepted_response = component.accepted_response
    generation = component.generation
    source_changed = replace(component.candidate, source=CustomCommandSource("other", ("other",)))

    component.configure(source_changed, data_affecting=False)

    assert component.model is accepted_model
    assert component.accepted_config is accepted_config
    assert component.accepted_response is accepted_response
    assert component.generation == generation


@pytest.mark.parametrize(
    ("updated", "expected_labels"),
    (
        (lambda value: replace(value, top=1), ["a", "Other"]),
        (lambda value: replace(value, other="hide"), ["a", "b"]),
        (lambda value: replace(value, ranking_comparison="none"), ["a", "b", "Other"]),
    ),
)
def test_local_projection_config_invokes_processor_and_preserves_semantics(
    monkeypatch: pytest.MonkeyPatch, updated: object, expected_labels: list[str]
) -> None:
    component = CustomHistoricalComponent(config(kind="ranking", top=2))
    source_response = response()
    assert component.accept_response(source_response)
    calls: list[object] = []

    def processor_spy(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return process_custom_historical(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(custom_component_module, "process_custom_historical", processor_spy)
    assert callable(updated)
    next_config = updated(component.candidate)
    component.configure(next_config, data_affecting=False)

    assert len(calls) == 1
    assert component.model == process_custom_historical(source_response, next_config)
    assert component.model is not None
    assert [series.label.en for series in component.model.series] == expected_labels


@pytest.mark.parametrize(
    ("updated", "expected_labels"),
    (
        (lambda value: replace(value, top=1), ["a", "Other"]),
        (lambda value: replace(value, other="hide"), ["a", "b"]),
        (lambda value: replace(value, ranking_comparison="none"), ["a", "b", "Other"]),
    ),
)
def test_primary_pending_completion_accepts_local_projection_drift(
    updated: object, expected_labels: list[str]
) -> None:
    component = CustomHistoricalComponent(config(kind="ranking", metric_id="read", top=2))
    assert component.accept_response(response())
    issued = replace(component.candidate, filters=(("genre", ("fiction",)),))
    component.configure(issued, data_affecting=True)
    assert callable(updated)
    current = updated(issued)
    component.configure(current, data_affecting=False)

    assert component.apply_result(CustomCompletion(component.generation, issued, response()))
    assert component.accepted_config == current
    assert component.model is not None
    assert component.model.config == current
    assert [series.label.en for series in component.model.series] == expected_labels
    assert component.retrieval_top == issued.top
    assert not component.is_pending


@pytest.mark.parametrize(
    ("density", "current", "comparison"),
    (
        ("minimal", False, False),
        ("compact", True, False),
        ("full", True, True),
        ("detailed", True, True),
    ),
)
def test_custom_summary_uses_complete_content_densities(
    density: str, current: bool, comparison: bool
) -> None:
    output = render_custom_summary(
        response().summary,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density=cast(Density, density),
        ),
    )

    assert ("Today’s Read 3.50 pages" in output) is current
    assert ("75.0%" in output) is comparison


def test_custom_summary_formats_declared_decimal_unit_without_token_adapter() -> None:
    summary = response().summary
    context = RenderContext(22, 24, load_translator("en"), color=False)

    assert format_custom_value(Decimal("1.2"), UNIT, language="en") == "1.20 pages"
    output = render_custom_summary(summary, context)
    assert "Today’s Read 3.50 page" in output
    assert "75.0%" in output
    assert "??" in output
    assert all(display_width(line) <= context.width for line in output.splitlines())


def test_custom_ranking_prefers_dataset_owned_localized_display() -> None:
    source = response((("book", "10"),))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(
                    source.data.series[0],
                    display=LocalizedText("10 chapters", "10 章"),
                ),
            ),
        ),
    )
    projection = process_custom_historical(
        source,
        config(
            kind="ranking", group_by=None, top=None, presentation=ChartPresentation(style="dot")
        ),
    )

    english = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="dot")
    )
    chinese = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("zh"), color=False, style="dot")
    )

    assert "10 chapters" in english
    assert "10 章" in chinese
    assert "10.00 pages" not in english


def test_non_ranking_custom_projection_rejects_project_links() -> None:
    source = response((("book", "10"),))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(replace(source.data.series[0], link="https://example.com/books/book"),),
        ),
    )

    with pytest.raises(CustomProjectionError, match="presentation fields"):
        process_custom_historical(source, config(kind="timeline", group_by=None, top=None))


def test_custom_ranking_other_never_inherits_a_project_link() -> None:
    source = response((("first", "10"), ("second", "5")))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(source.data.series[0], link="https://example.com/projects/first"),
                replace(source.data.series[1], link="https://example.com/projects/second"),
            ),
        ),
    )
    projection = process_custom_historical(
        source,
        config(kind="ranking", group_by=None, top=1, other="show"),
    )

    first, other = projection.series
    assert first.link == "https://example.com/projects/first"
    assert other.is_other and other.link is None


def test_custom_ranking_preserves_long_dataset_labels_without_prefix_compaction() -> None:
    source = response((("doctor", "10"), ("doctor-sandbox", "5")))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(
                    source.data.series[0], label=LocalizedText("project-doctor", "项目-doctor")
                ),
                replace(
                    source.data.series[1],
                    label=LocalizedText("project-doctor-sandbox", "项目-doctor-sandbox"),
                ),
            ),
        ),
    )
    projection = process_custom_historical(
        source,
        config(
            kind="ranking", group_by=None, top=None, presentation=ChartPresentation(style="dot")
        ),
    )

    output = render_custom_projection(
        projection, RenderContext(110, 20, load_translator("en"), color=False, style="dot")
    )

    assert "project-doctor" in output
    assert "project-doctor-sandbox" in output
    assert "…doctor" not in output


def test_custom_series_labels_follow_the_active_language() -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(group_by=None, top=None)
    )
    context = RenderContext(80, 20, load_translator("zh"), color=False, style="points")

    output = render_custom_projection(projection, context)

    assert "时间趋势" in output
    assert "今日 阅读 3.50 页" not in output

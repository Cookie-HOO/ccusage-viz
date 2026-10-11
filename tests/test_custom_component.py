from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import (
    CustomCompletion,
    CustomHistoricalComponent,
    custom_replacement_required,
    custom_summary_replacement_required,
)
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomComparison,
    CustomData,
    CustomDataset,
    CustomFilter,
    CustomFilterOption,
    CustomMetric,
    CustomPaneSummary,
    CustomPoint,
    CustomProtocolFailure,
    CustomSeries,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.custom_protocol import (
    CustomChartResponse,
    CustomPaneResponse,
    CustomSummaryResponse,
)
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    Density,
)
from ccusage_viz.processing.custom_historical import (
    CustomProjectionError,
    process_custom_historical,
)
from ccusage_viz.render import custom
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_projection
from ccusage_viz.render.palette import categorical_color
from ccusage_viz.render.ranking_presentation import copyable_description_text
from ccusage_viz.render.summary import format_custom_value, render_custom_summary
from ccusage_viz.render.timeline_presentation import TimelinePlot

SOURCE = CustomCommandSource("reading", ("reader", "ccuv"))
RANGE = DateRange(date(2026, 9, 1), date(2026, 9, 2))
UNIT = CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2)


def config(**changes: object) -> CustomChartConfig:
    values: dict[str, object] = {
        "kind": "timeline",
        "source": SOURCE,
        "date_range": RANGE,
        "presentation": ChartPresentation(theme="no-color"),
        "group_by": "book",
        "top": 2,
    }
    values.update(changes)
    return CustomChartConfig(**values)  # type: ignore[arg-type]


def response(
    values: tuple[tuple[str, str], ...] = (("a", "10"), ("b", "5"), ("c", "2")),
    *,
    point_date: date = date(2026, 9, 1),
) -> CustomPaneResponse:
    capability = CustomChartCapability(("day",), ("book",), ("genre",))
    capabilities = CustomCapabilities(
        (),
        (
            CustomFilter(
                "genre",
                LocalizedText("Genre", "类型"),
                (CustomFilterOption("fiction", LocalizedText("Fiction", "小说")),),
            ),
        ),
        {kind: capability for kind in ("timeline", "calendar", "stack", "ranking")},
    )
    data = CustomData(
        tuple(
            CustomSeries(
                series_id,
                LocalizedText(series_id, series_id),
                (CustomPoint(point_date, Decimal(value)),),
            )
            for series_id, value in values
        )
    )
    metric = CustomMetric(
        "read",
        LocalizedText("Read", "阅读"),
        UNIT,
        Decimal("3.5"),
        CustomComparison("ready", Decimal("2")),
        CustomComparison("unavailable"),
    )
    return CustomPaneResponse(
        CustomDataset(LocalizedText("Reading", "阅读"), LocalizedText("Daily", "每日"), UNIT),
        capabilities,
        data,
        CustomPaneSummary(metric),
    )


def test_historical_metric_switch_commits_only_after_target_response() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    old_model = component.model

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "updated_days"
    assert component.model is old_model
    assert component.accept_response(response())
    assert component.candidate.metric_id == "updated_days"
    assert component.request_config.metric_id == "updated_days"


def test_historical_metric_switch_failure_retains_old_facts_and_metric() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    old_model = component.model

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.fail(RuntimeError("unavailable"), generation=component.generation)
    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "stars"
    assert component.model is old_model


def test_custom_ranking_uses_capability_sort_direction_for_entries_and_prior_ranks() -> None:
    current = response((("older", "8"), ("recent", "2")))
    previous = response((("older", "1"), ("recent", "9")), point_date=date(2026, 8, 30))
    ascending = replace(
        current,
        capabilities=replace(
            current.capabilities,
            charts={
                **current.capabilities.charts,
                "ranking": replace(current.capabilities.charts["ranking"], sort_direction="ascending"),
            },
        ),
    )
    chart = config(kind="ranking")
    comparison_chart = replace(chart, date_range=DateRange(date(2026, 8, 30), date(2026, 8, 30)))

    projection = process_custom_historical(
        ascending, chart, comparison_response=previous, comparison_config=comparison_chart
    )

    assert [series.id for series in projection.series] == ["recent", "older"]
    assert [series.previous_rank for series in projection.series] == [2, 1]


def test_custom_ranking_derives_decimal_comparison_facts_from_raw_responses() -> None:
    current = response((("api", "3"), ("app", "1")))
    previous = response((("api", "1"), ("app", "2"), ("batch", "4")), point_date=date(2026, 8, 30))
    comparison_config = replace(
        config(kind="ranking"), date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31))
    )

    projection = process_custom_historical(
        current,
        config(kind="ranking"),
        comparison_response=previous,
        comparison_config=comparison_config,
    )

    api, app = projection.series
    assert api.total == Decimal("3")
    assert api.previous_total == Decimal("1")
    assert api.previous_rank == 3
    assert api.comparison_ready
    assert app.previous_total == Decimal("2")
    assert app.previous_rank == 2


def test_custom_ranking_distinguishes_missing_comparison_response_from_new_series() -> None:
    current = response((("api", "3"), ("app", "2"), ("batch", "1")))
    current_config = config(
        kind="ranking",
        group_by=None,
        top=2,
        presentation=ChartPresentation(density="detailed", style="dot"),
    )
    previous = response((("api", "1"),), point_date=date(2026, 8, 30))
    comparison_config = replace(
        current_config,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
    )

    unavailable = process_custom_historical(current, current_config)
    partial = process_custom_historical(
        current,
        current_config,
        comparison_response=previous,
        comparison_config=comparison_config,
    )

    assert not unavailable.comparison_available
    assert all(not series.comparison_ready for series in unavailable.series)
    assert partial.comparison_available
    api, app, other = partial.series
    assert api.comparison_ready and api.previous_total == Decimal("1")
    assert not app.comparison_ready and app.previous_total is None
    assert not other.comparison_ready and other.previous_total is None


def test_custom_ranking_hides_unavailable_comparison_columns_and_labels_new_entries() -> None:
    current = response((("api", "3"), ("app", "2"), ("batch", "1")))
    current_config = config(
        kind="ranking",
        group_by=None,
        top=2,
        presentation=ChartPresentation(density="detailed", style="dot"),
    )
    previous = response((("api", "1"),), point_date=date(2026, 8, 30))
    comparison_config = replace(
        current_config,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
    )
    context = RenderContext(
        110,
        20,
        load_translator("en"),
        color=False,
        density="detailed",
        style="dot",
        period="14d",
    )

    unavailable = render_custom_projection(
        process_custom_historical(current, current_config), context
    )
    partial = render_custom_projection(
        process_custom_historical(
            current,
            current_config,
            comparison_response=previous,
            comparison_config=comparison_config,
        ),
        context,
    )

    assert "vs prior" not in unavailable
    assert "Rank Δ" not in unavailable
    assert "vs prior 14d" in partial
    assert "New" in next(line for line in partial.splitlines() if "app" in line)
    assert "New in ranking" in next(line for line in partial.splitlines() if "app" in line)
    assert "New" not in next(line for line in partial.splitlines() if "Other" in line)

    chinese = render_custom_projection(
        process_custom_historical(
            current,
            current_config,
            comparison_response=previous,
            comparison_config=comparison_config,
        ),
        replace(context, translator=load_translator("zh")),
    )
    app_line = next(line for line in chinese.splitlines() if "app" in line)
    assert "新增" in app_line
    assert "新上榜" in app_line


def test_top_n_and_other_are_local_decimal_operations() -> None:
    projection = process_custom_historical(response(), config())

    assert [series.label.en for series in projection.series] == ["a", "b", "Other"]
    assert projection.series[-1].label.zh_cn == "其他"
    assert projection.series[-1].values[0] == Decimal("2")
    assert projection.series[-1].values[1] == Decimal("0")


def test_projection_rejects_selected_filter_option_outside_capabilities() -> None:
    with pytest.raises(CustomProjectionError, match="filter options"):
        process_custom_historical(response(), config(filters=(("genre", ("unknown",)),)))


def test_calendar_rejects_grouped_or_non_daily_results() -> None:
    calendar = config(kind="calendar", group_by="book")

    with pytest.raises(CustomProjectionError, match="calendar"):
        process_custom_historical(response(), calendar)


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


def test_component_accepts_matching_comparison_without_replacing_current_projection() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response((("api", "3"), ("app", "1"))))
    comparison_config = component.start_comparison()
    assert comparison_config is not None
    previous = response(
        (("api", "1"), ("app", "2"), ("batch", "4")), point_date=comparison_config.date_range.since
    )

    assert component.accept_response(previous, purpose="comparison")

    assert component.model is not None
    api, app = component.model.series
    assert api.previous_total == Decimal("1")
    assert api.previous_rank == 3
    assert app.previous_total == Decimal("2")
    assert not component.comparison_is_pending


def test_component_rejects_stale_or_unrequested_comparison_response() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response())
    comparison_config = component.start_comparison()
    assert comparison_config is not None

    assert not component.apply_result(
        CustomCompletion(component.generation, component.candidate, response(), "comparison")
    )
    assert component.comparison_response is None


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
    assert custom_replacement_required(
        current, replace(current, filters=(("genre", ("fiction",)),))
    )
    assert not custom_replacement_required(current, replace(current, top=1))
    assert not custom_replacement_required(current, replace(current, other="hide"))
    assert not custom_replacement_required(
        current,
        replace(current, presentation=replace(current.presentation, theme="ocean")),
    )


def test_custom_summary_replacement_requires_only_summary_query_fields() -> None:
    current = config()

    assert custom_summary_replacement_required(
        current, replace(current, source=CustomCommandSource("other", ("other",)))
    )
    assert custom_summary_replacement_required(
        current, replace(current, filters=(("genre", ("fiction",)),))
    )
    assert custom_summary_replacement_required(current, replace(current, granularity="month"))
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


@pytest.mark.parametrize(
    ("density", "expected"),
    (("minimal", False), ("compact", False), ("full", True), ("detailed", True)),
)
def test_ranking_comparison_request_uses_complete_content_densities(
    density: str, expected: bool
) -> None:
    component = CustomHistoricalComponent(
        config(kind="ranking", presentation=ChartPresentation(density=cast(Density, density)))
    )

    request = component.comparison_request_config()

    assert (request is not None) is expected
    if request is not None:
        assert request.date_range.fixed_bounds


def test_ranking_all_period_never_requests_a_prior_range() -> None:
    component = CustomHistoricalComponent(
        replace(
            config(kind="ranking", presentation=ChartPresentation(density="detailed")),
            date_range=DateRange(
                date(1971, 1, 1), date(2026, 10, 9), relative_until=True, period="all"
            ),
        )
    )

    assert component.comparison_request_config() is None


@pytest.mark.parametrize(
    ("comparison", "expected"),
    (("full", True), ("rank", True), ("none", False)),
)
def test_ranking_comparison_capability_controls_prior_range_requests(
    comparison: str, expected: bool
) -> None:
    component = CustomHistoricalComponent(
        replace(
            config(kind="ranking", presentation=ChartPresentation(density="detailed")),
            ranking_comparison=cast(Literal["full", "rank", "none"], comparison),
        )
    )

    assert (component.comparison_request_config() is not None) is expected


def test_component_reprojects_only_display_local_configuration() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    accepted_model = component.model
    accepted_config = component.accepted_config
    source_changed = replace(component.candidate, source=CustomCommandSource("other", ("other",)))

    component.configure(source_changed, data_affecting=False)

    assert component.model is accepted_model
    assert component.accepted_config is accepted_config
    assert component.accepted_response is not None


def test_component_reprojects_accepted_response_for_local_display_change() -> None:
    component = CustomHistoricalComponent(config(top=None))
    assert component.accept_response(response())

    component.configure(replace(component.candidate, top=1), data_affecting=False)

    assert component.accepted_config == component.candidate
    assert component.model is not None
    assert [series.label.en for series in component.model.series] == ["a", "Other"]


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


@pytest.mark.parametrize(
    ("kind", "style", "expected"),
    (
        ("timeline", "points", "09-01"),
        ("stack", "stacked", "09-01"),
        ("calendar", "grid", "Se"),
        ("ranking", "dots", "a"),
    ),
)
def test_custom_charts_use_native_layout_primitives(kind: str, style: str, expected: str) -> None:
    projection = process_custom_historical(
        response((("total", "10"),)),
        config(kind=kind, group_by=None, top=None, presentation=ChartPresentation(style=style)),
    )
    context = RenderContext(80, 20, load_translator("en"), color=False, style=style)

    output = render_custom_projection(projection, context)

    assert "Today’s Read 3.50 pages" not in output
    assert expected in output


def test_custom_ranking_heading_is_centered_once() -> None:
    projection = process_custom_historical(
        response(),
        config(kind="ranking", presentation=ChartPresentation(style="dot")),
    )
    context = RenderContext(80, 20, load_translator("zh"), color=False, period="14d", style="dot")

    heading = render_custom_projection(projection, context).splitlines()[0]

    assert heading.lstrip() == "阅读 · book · 累计排名 · 14d"
    assert (
        len(heading) - len(heading.lstrip())
        == (context.width - display_width(heading.lstrip())) // 2
    )


def test_custom_ranking_renders_localized_descriptions_only_when_visible() -> None:
    source = response((("api", "10"),))
    described = replace(
        source,
        data=CustomData(
            (
                CustomSeries(
                    "api",
                    LocalizedText("API", "接口"),
                    (CustomPoint(date(2026, 9, 1), Decimal("10")),),
                    LocalizedText(
                        "Release validation and regression testing account for most activity.",
                        "发布验证和回归测试构成了大部分活动。",
                    ),
                ),
            )
        ),
    )
    projection = process_custom_historical(described, config(kind="ranking"))
    context = RenderContext(34, 20, load_translator("zh"), color=False, style="dot")

    collapsed = render_custom_projection(projection, context)
    expanded = render_custom_projection(projection, context, descriptions_visible=True)

    assert "发布验证" not in collapsed
    assert "发布验证" in expanded
    assert len(expanded.splitlines()) <= len(collapsed.splitlines()) + 2
    description_rows = [line for line in expanded.splitlines() if "发布" in line or "测试" in line]
    assert description_rows
    assert all(display_width(line) <= context.width for line in description_rows)


def test_custom_descriptions_are_rejected_outside_ranking() -> None:
    source = response((("api", "10"),))
    described = replace(
        source,
        data=CustomData(
            (
                CustomSeries(
                    "api",
                    LocalizedText("API", "接口"),
                    (CustomPoint(date(2026, 9, 1), Decimal("10")),),
                    LocalizedText("Release validation", "发布验证"),
                    LocalizedText("10 requests", "10 个请求"),
                ),
            )
        ),
    )

    with pytest.raises(CustomProjectionError, match="only by ranking"):
        process_custom_historical(described, config(kind="timeline"))


def test_custom_calendar_preserves_decimal_values_for_shared_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = process_custom_historical(
        response((("total", "1.234567890123456789"),)),
        config(kind="calendar", group_by=None, top=None),
    )
    captured: dict[str, object] = {}

    def capture(days: tuple[date, ...], values: object, context: RenderContext) -> tuple[str, ...]:
        captured["days"] = days
        captured["values"] = values
        return ()

    monkeypatch.setattr(custom, "render_calendar_grid", capture)

    assert render_custom_projection(projection, RenderContext(80, 20, load_translator("en")))
    values = captured["values"]
    assert isinstance(values, dict)
    assert values[date(2026, 9, 1)] == Decimal("1.234567890123456789")


@pytest.mark.parametrize(
    ("density", "has_footer", "has_streaks", "has_legend"),
    (
        ("minimal", False, False, False),
        ("compact", False, False, False),
        ("full", True, False, False),
        ("detailed", True, True, True),
    ),
)
def test_custom_calendar_uses_shared_density_footer(
    density: str, has_footer: bool, has_streaks: bool, has_legend: bool
) -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(kind="calendar", group_by=None, top=None)
    )

    output = render_custom_projection(
        projection,
        RenderContext(100, 24, load_translator("en"), color=False, ascii=True, density=density),
    )

    assert ("Active days 1" in output) is has_footer
    assert ("Daily average 5.00 pages" in output) is has_footer
    assert ("Peak 2026-09-01 · 10.00 pages" in output) is has_footer
    assert ("Current streak 0" in output) is has_streaks
    assert ("Longest streak 1" in output) is has_streaks
    assert ("Less . o O # More" in output) is has_legend


def test_custom_timeline_preserves_decimal_values_until_plot_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = process_custom_historical(
        response((("total", "1.234567890123456789"),)), config(group_by=None, top=None)
    )
    captured: dict[str, object] = {}

    def capture(series: object, **kwargs: object) -> TimelinePlot:
        captured["series"] = series
        captured.update(kwargs)
        return TimelinePlot("plot", "")

    monkeypatch.setattr(custom, "render_timeline_plot", capture)

    assert render_custom_projection(projection, RenderContext(80, 20, load_translator("en")))
    series = captured["series"]
    assert isinstance(series, tuple)
    assert series[0].values[0] == Decimal("1.234567890123456789")
    assert all(value == Decimal() for value in series[0].values[1:])
    assert captured["y_ticks"] == (
        [
            Decimal("0"),
            Decimal("0.30864197253086419725"),
            Decimal("0.6172839450617283945"),
            Decimal("0.92592591759259259175"),
            Decimal("1.234567890123456789"),
        ],
        ["0.00", "0.31", "0.62", "0.93", "1.23"],
    )


def test_custom_stack_preserves_decimal_values_until_grouped_plot_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = process_custom_historical(
        response((("total", "1.234567890123456789"),)),
        config(
            kind="stack", group_by=None, top=None, presentation=ChartPresentation(style="stacked")
        ),
    )
    captured: dict[str, object] = {}

    def capture(values: object, **kwargs: object) -> str:
        captured["values"] = values
        captured.update(kwargs)
        return "stack"

    monkeypatch.setattr(custom, "render_stack_grid", capture)

    assert render_custom_projection(projection, RenderContext(80, 20, load_translator("en")))
    values = captured["values"]
    assert isinstance(values, list)
    assert values[0][0] == Decimal("1.234567890123456789")
    assert captured["tick_positions"][-1] == Decimal("1.234567890123456789")


def test_custom_timeline_matches_native_total_palette_identity() -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(group_by=None, top=None)
    )
    context = RenderContext(80, 20, load_translator("en"), color=True, style="points")

    output = render_custom_projection(projection, context)

    assert f"\x1b[38;5;{categorical_color('total')}m" in output
    assert "pages" in output


def test_custom_timeline_labels_unit_once_and_keeps_numeric_ticks_unit_free() -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(group_by=None, top=None)
    )
    output = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="points")
    )

    assert "Timeline · 2026-09-01–2026-09-02 · pages" in output
    assert "0.00 pages" not in output
    assert "2.50 pages" not in output


def test_custom_timeline_places_prefix_unit_before_heading() -> None:
    prefix_unit = CustomUnit("credit", LocalizedText("$", "元"), "prefix", 2)
    projection = process_custom_historical(
        replace(
            response((("total", "10"),)), dataset=replace(response().dataset, unit=prefix_unit)
        ),
        config(group_by=None, top=None),
    )
    output = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="points")
    )

    assert "$ · Reading · Timeline · 2026-09-01–2026-09-02" in output
    assert "$0.00" not in output


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


def test_custom_ranking_shows_copy_marker_and_clipboard_description_text() -> None:
    source = response((("book", "10"),))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(
                    source.data.series[0],
                    description=LocalizedText(
                        "Read [GitHub](https://github.com/example/book)",
                        "阅读 [GitHub](https://github.com/example/book)",
                    ),
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

    regular = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="dot")
    )
    copied = render_custom_projection(
        projection,
        RenderContext(80, 20, load_translator("en"), color=False, style="dot"),
        copied_entry_id="book",
    )

    assert "book | ⊞" in regular
    assert "book | ✓" in copied
    assert (
        copyable_description_text(source.data.series[0].description.en)
        == "Read GitHub https://github.com/example/book"
    )


def test_custom_ranking_renders_project_link_after_copy_marker() -> None:
    source = response((("book", "10"),))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(source.data.series[0], link="https://example.com/books/book"),
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
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="dot")
    )

    assert "book | ⊞ · →" in strip_ansi(output)
    assert output.count("\x1b]8;;https://example.com/books/book\x1b\\") == 1
    assert projection.series[0].link == "https://example.com/books/book"


def test_non_ranking_custom_projection_rejects_project_links() -> None:
    source = response((("book", "10"),))
    source = replace(
        source,
        data=replace(
            source.data,
            series=(
                replace(source.data.series[0], link="https://example.com/books/book"),
            ),
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


def test_custom_ranking_title_includes_selected_dataset_filters() -> None:
    source = response((("book", "10"),))
    projection = process_custom_historical(
        source,
        replace(
            config(
                kind="ranking", group_by=None, top=None, presentation=ChartPresentation(style="dot")
            ),
            filters=(("genre", ("fiction",)),),
        ),
    )

    output = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("en"), color=False, style="dot")
    )

    assert "Filters: Genre Fiction" in output


def test_custom_timeline_title_includes_selected_dataset_filters() -> None:
    source = response((("book", "10"),))
    projection = process_custom_historical(
        source,
        replace(config(kind="timeline"), filters=(("genre", ("fiction",)),)),
    )

    output = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("en"), color=False, style="points")
    )

    assert "Filters: Genre Fiction" in output


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


def test_custom_ranking_prefers_dataset_owned_localized_comparison_display() -> None:
    current = response((("book", "10"),))
    previous = response((("book", "3"),), point_date=date(2026, 8, 30))
    current = replace(
        current,
        data=replace(
            current.data,
            series=(
                replace(
                    current.data.series[0],
                    comparison_display=LocalizedText("+7 chapters", "+7 章"),
                ),
            ),
        ),
    )
    projection = process_custom_historical(
        current,
        config(
            kind="ranking", group_by=None, top=None, presentation=ChartPresentation(style="dot")
        ),
        comparison_response=previous,
        comparison_config=replace(
            config(kind="ranking", group_by=None, top=None),
            date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
        ),
    )

    english = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("en"), color=False, style="dot")
    )
    chinese = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("zh"), color=False, style="dot")
    )

    assert "+7 chapters" in english
    assert "+7 章" in chinese


def test_custom_timeline_uses_native_area_validation() -> None:
    projection = process_custom_historical(response(), config(top=None))
    context = RenderContext(80, 20, load_translator("en"), color=False, style="area")

    with pytest.raises(UsageError) as error:
        render_custom_projection(projection, context)

    assert error.value.message_key == "error.timeline_area_series"


def test_custom_series_labels_follow_the_active_language() -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(group_by=None, top=None)
    )
    context = RenderContext(80, 20, load_translator("zh"), color=False, style="points")

    output = render_custom_projection(projection, context)

    assert "时间趋势" in output
    assert "今日 阅读 3.50 页" not in output

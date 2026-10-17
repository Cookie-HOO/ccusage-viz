from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

import ccusage_viz.custom_component as custom_component_module
from ccusage_viz.configuration import apply_custom_probe_defaults, v2_metric_probe_descriptor
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.custom_component import (
    CustomCompletion,
    CustomHistoricalComponent,
    custom_projection_replacement_required,
)
from ccusage_viz.custom_models import (
    CustomChartDefaults,
    CustomData,
    CustomDimension,
    CustomPoint,
    CustomRankingEntry,
    CustomSeries,
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
from ccusage_viz.custom_protocol.responses import (
    V2ChartResponse,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation
from ccusage_viz.processing.custom_historical import (
    CustomProjectionError,
    process_custom_historical,
)
from ccusage_viz.processing.custom_ranking import process_custom_ranking
from ccusage_viz.render import custom
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_projection
from ccusage_viz.render.palette import categorical_color
from ccusage_viz.render.ranking_description import copyable_description_text
from ccusage_viz.render.timeline_presentation import TimelinePlot

from .helpers import config, response


def test_calendar_rejects_grouped_or_non_daily_results() -> None:
    calendar = config(kind="calendar", group_by="book")

    with pytest.raises(CustomProjectionError, match="calendar"):
        process_custom_historical(response(), calendar)


def test_relative_timestamp_heading_uses_configured_period() -> None:
    interval = TimestampRange(
        datetime.fromisoformat("2026-10-15T11:50:00+08:00"),
        datetime.fromisoformat("2026-10-15T12:00:00+08:00"),
        relative_until=True,
        period="10m",
    )
    chart = config(
        kind="ranking",
        metric_id="reading_time",
        metric_titles=("Reading time", "阅读时长"),
        date_range=interval,
    )

    heading = custom.custom_heading(
        chart,
        RenderContext(120, 20, load_translator("en"), color=False),
    )

    assert "Reading time · Ranking · by book · 10m" in heading
    assert "pages" not in heading
    assert "2026-10-15T" not in heading


def test_fixed_timestamp_heading_uses_exact_aware_half_open_bounds() -> None:
    interval = TimestampRange(
        datetime.fromisoformat("2026-10-15T11:50:00+08:00"),
        datetime.fromisoformat("2026-10-15T12:00:00+08:00"),
    )
    chart = config(
        kind="ranking",
        metric_id="reading_time",
        metric_titles=("Reading time", "阅读时长"),
        date_range=interval,
    )

    heading = custom.custom_heading(
        chart,
        RenderContext(120, 20, load_translator("en"), color=False),
    )

    assert "Reading time · Ranking · by book" in heading
    assert "[2026-10-15T11:50:00+08:00, 2026-10-15T12:00:00+08:00)" in heading


def test_v2_partitioned_ranking_heading_prefers_accepted_descriptor_metric_title() -> None:
    dataset_title = LocalizedText("Routing Dataset", "路由数据集")
    metric_title = LocalizedText("Successful Requests", "成功请求数")
    unit = CustomUnit("request-unit", LocalizedText("calls", "调用次"), "suffix", 0)
    partition = CustomDimension("provider", LocalizedText("Provider", "供应商"))
    group = CustomDimension("model", LocalizedText("Model", "模型"))
    capability = V2HistoricalChartCapability(
        (),
        ("model",),
        ("region",),
        partition_by=("provider",),
    )
    metric = V2MetricDescriptor(
        "successful_requests_metric_id",
        metric_title,
        LocalizedText("Successful request count", "成功请求计数"),
        unit,
        "sum",
        V2MetricCapabilities((group,), (), {"ranking": capability}, (partition,)),
        {"ranking": CustomChartDefaults("14d", "model", 10, partition_by="provider")},
    )
    descriptor = V2ProbeDescriptor(
        "routing-v2",
        "2.0.0",
        V2Dataset(dataset_title, LocalizedText("Routing telemetry", "路由遥测")),
        (metric,),
        (),
    )
    dashboard_config = config(
        kind="ranking",
        metric_id=metric.id,
        metric_titles=("Stale Requests", "过期请求数"),
        group_by=None,
        partition_by=None,
        filters=(("region", ("apac",)),),
        top=None,
    )
    projected_descriptor = v2_metric_probe_descriptor(descriptor, metric.id)
    chart = apply_custom_probe_defaults(
        dashboard_config,
        projected_descriptor,
        timezone="UTC",
        now=datetime(2026, 10, 15, tzinfo=UTC),
    )
    payload = V2ChartResponse(
        metric.id,
        V2RankingData(
            groups=(
                V2RankingGroup(
                    "cloud",
                    LocalizedText("Cloud", "云厂商"),
                    (
                        CustomRankingEntry(
                            "model-a", LocalizedText("Model A", "模型 A"), Decimal("42")
                        ),
                    ),
                ),
            )
        ),
        descriptor,
        V2Runtime(()),
    )

    projection = process_custom_ranking(payload, chart)
    heading = render_custom_projection(
        projection,
        RenderContext(120, 24, load_translator("zh"), color=False, style="dot"),
    ).splitlines()[0]

    assert chart.partition_by == "provider"
    assert chart.group_by == "model"
    assert "成功请求数 · 累计排名 · by 供应商 → 模型" in heading
    for forbidden in (
        "路由数据集",
        "Routing Dataset",
        "successful_requests_metric_id",
        "Stale Requests",
        "过期请求数",
        "calls",
        "调用次",
        "region",
        "apac",
    ):
        assert forbidden not in heading


@pytest.mark.parametrize(
    "updated",
    (
        lambda value: replace(value, presentation=replace(value.presentation, theme="dracula")),
        lambda value: replace(value, presentation=replace(value.presentation, style="list")),
        lambda value: replace(value, presentation=replace(value.presentation, density="minimal")),
        lambda value: replace(value, presentation=replace(value.presentation, legend="hidden")),
        lambda value: replace(value, weekdays="hide"),
    ),
)
def test_renderer_only_changes_do_not_require_custom_reprojection(updated: object) -> None:
    current = config(kind="ranking", top=10)

    assert callable(updated)
    assert not custom_projection_replacement_required(current, updated(current))


@pytest.mark.parametrize(
    "updated",
    (
        lambda value: replace(value, presentation=replace(value.presentation, theme="dracula")),
        lambda value: replace(value, presentation=replace(value.presentation, style="list")),
        lambda value: replace(value, presentation=replace(value.presentation, density="minimal")),
        lambda value: replace(value, presentation=replace(value.presentation, legend="hidden")),
        lambda value: replace(value, weekdays="hide"),
    ),
)
def test_renderer_only_config_reuses_accepted_projection(
    monkeypatch: pytest.MonkeyPatch, updated: object
) -> None:
    component = CustomHistoricalComponent(config(kind="ranking", top=None))
    assert component.accept_response(response())
    model = component.model
    assert model is not None
    revision = component.render_revision
    lifecycle = (
        component.generation,
        component.pending_generation,
        component.comparison_config,
        component.comparison_response,
        component.comparison_pending_generation,
        component.comparison_error,
    )
    calls: list[object] = []

    def processor_spy(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return process_custom_historical(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(custom_component_module, "process_custom_historical", processor_spy)
    assert callable(updated)
    next_config = updated(component.candidate)
    component.configure(next_config, data_affecting=False)

    assert calls == []
    assert component.accepted_config == next_config
    assert component.model is not model
    assert component.model.config == next_config
    assert component.model.series is model.series
    assert component.model.days is model.days
    assert component.model.unit is model.unit
    assert component.model.presentation is model.presentation
    assert component.model.comparison_available == model.comparison_available
    assert component.model.show_percentage == model.show_percentage
    assert component.render_revision == revision + 1
    assert (
        component.generation,
        component.pending_generation,
        component.comparison_config,
        component.comparison_response,
        component.comparison_pending_generation,
        component.comparison_error,
    ) == lifecycle


def test_primary_completion_accepts_renderer_change_while_pending() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    pending_config = replace(component.candidate, group_by=None)
    component.configure(pending_config, data_affecting=True)
    generation = component.generation
    updated = replace(
        pending_config,
        presentation=replace(pending_config.presentation, theme="dracula"),
    )

    component.configure(updated, data_affecting=False)

    assert component.generation == generation
    assert component.apply_result(CustomCompletion(generation, pending_config, response()))
    assert component.accepted_config == updated
    assert component.model is not None
    assert component.model.config == updated
    assert not component.is_pending


def test_comparison_completion_accepts_and_normalizes_renderer_change() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response((("api", "3"), ("app", "1"))))
    issued = component.start_comparison()
    assert issued is not None
    updated = replace(
        component.candidate,
        presentation=replace(component.candidate.presentation, theme="dracula", density="full"),
    )

    component.configure(updated, data_affecting=False)
    previous = response((("api", "1"), ("app", "2")), point_date=issued.date_range.since)

    assert component.apply_result(
        CustomCompletion(component.generation, issued, previous, "comparison")
    )
    assert component.comparison_config == component.comparison_request_config()
    assert component.comparison_config is not None
    assert component.comparison_config.presentation == updated.presentation
    assert component.model is not None
    assert component.model.comparison_available
    assert not component.comparison_is_pending


def test_comparison_renderer_disable_cancels_pending_and_rejects_old_completion() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response())
    issued = component.start_comparison()
    assert issued is not None

    component.configure(
        replace(
            component.candidate,
            presentation=replace(component.candidate.presentation, density="minimal"),
        ),
        data_affecting=False,
    )

    assert not component.comparison_is_pending
    assert component.comparison_pending_generation is None
    assert not component.apply_result(
        CustomCompletion(component.generation, issued, response(), "comparison")
    )
    assert component.comparison_response is None


def test_renderer_only_config_while_pending_preserves_accepted_facts() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    accepted_config = component.accepted_config
    accepted_model = component.model
    component.configure(replace(component.candidate, group_by=None), data_affecting=True)
    revision = component.render_revision

    component.configure(
        replace(
            component.candidate,
            presentation=replace(component.candidate.presentation, theme="dracula"),
        ),
        data_affecting=False,
    )

    assert component.is_pending
    assert component.accepted_config is accepted_config
    assert component.model is accepted_model
    assert component.render_revision == revision + 1


def test_renderer_only_config_reprojects_when_accepted_model_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response())
    component.model = None
    calls = 0
    real_processor = process_custom_historical

    def processor_spy(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_processor(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(custom_component_module, "process_custom_historical", processor_spy)
    updated = replace(
        component.candidate,
        presentation=replace(component.candidate.presentation, theme="dracula"),
    )

    component.configure(updated, data_affecting=False)

    assert calls == 1
    assert component.accepted_config == updated
    assert component.model is not None
    assert component.model.config == updated


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

    assert heading.lstrip() == "阅读 · 累计排名 · by book · 14d"
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
    assert "pages" not in strip_ansi(output).splitlines()[0]


def test_custom_timeline_labels_unit_once_and_keeps_numeric_ticks_unit_free() -> None:
    projection = process_custom_historical(
        response((("total", "10"),)), config(group_by=None, top=None)
    )
    output = render_custom_projection(
        projection, RenderContext(80, 20, load_translator("en"), color=False, style="points")
    )

    assert "Reading · Timeline · 2026-09-01–2026-09-02" in output
    assert "pages" not in output.splitlines()[0]
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

    assert "Reading · Timeline · 2026-09-01–2026-09-02" in output
    assert "$" not in output.splitlines()[0]
    assert "$0.00" not in output


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
            series=(replace(source.data.series[0], link="https://example.com/books/book"),),
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


def test_custom_ranking_title_omits_selected_dataset_filters() -> None:
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

    assert "Filters: Genre Fiction" not in output.splitlines()[0]


def test_custom_timeline_title_omits_selected_dataset_filters() -> None:
    source = response((("book", "10"),))
    projection = process_custom_historical(
        source,
        replace(config(kind="timeline"), filters=(("genre", ("fiction",)),)),
    )

    output = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("en"), color=False, style="points")
    )

    assert "Filters: Genre Fiction" not in output.splitlines()[0]


def test_custom_timeline_uses_native_area_validation() -> None:
    projection = process_custom_historical(response(), config(top=None))
    context = RenderContext(80, 20, load_translator("en"), color=False, style="area")

    with pytest.raises(UsageError) as error:
        render_custom_projection(projection, context)

    assert error.value.message_key == "error.timeline_area_series"

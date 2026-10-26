from dataclasses import replace
from datetime import UTC, date, datetime
from typing import cast

import pytest

from ccusage_viz.configuration import (
    apply_custom_probe_defaults,
    default_custom_pane,
    default_pane,
    focused_dashboard_from_chart,
    v2_metric_probe_descriptor,
)
from ccusage_viz.core.time import DateRange, local_today, refresh_date_range
from ccusage_viz.custom_models import (
    CustomChartDefaults,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2ProbeDescriptor,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.options import (
    DENSITIES,
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    Density,
    EmptyPaneConfig,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_custom_chart,
    adjust_standalone,
    compatible_styles,
    has_complete_content,
    pane_kind,
    replace_chart_filters,
    resolve_date_range,
)

from .option_helpers import timeline


def test_chart_launch_becomes_focused_one_pane_dashboard() -> None:
    historical = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=31, ascii=True, timezone="Asia/Shanghai"),
        TimelineConfig("timeline", DateRange(date(2026, 1, 1), date(2026, 1, 14))),
        frozenset(("interval", "period")),
    )
    monitor = replace(
        historical,
        chart=MonitorConfig("monitor", DateRange(date(2026, 1, 1), date(2026, 1, 1))),
    )
    custom = replace(
        historical,
        chart=CustomChartConfig(
            "ranking",
            CustomCommandSource("reading", ("reader", "ccuv")),
            DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        ),
    )

    for launch, pane_type in (
        (historical, ChartPaneConfig),
        (monitor, ChartPaneConfig),
        (custom, CustomChartPaneConfig),
    ):
        dashboard = focused_dashboard_from_chart(launch)
        assert dashboard.process == launch.process
        assert (dashboard.host.columns, dashboard.host.spotlight) == (1, 0)
        assert dashboard.host.header_style == "hidden"
        assert dashboard.host.header_summary == "none"
        assert dashboard.host.ascii == launch.host.ascii
        assert dashboard.host.timezone == launch.host.timezone
        assert len(dashboard.panes) == 1
        assert isinstance(dashboard.panes[0], pane_type)
        assert dashboard.panes[0].chart == launch.chart

    historical_dashboard = focused_dashboard_from_chart(historical)
    monitor_dashboard = focused_dashboard_from_chart(monitor)
    assert historical_dashboard.host.refresh_interval == 31
    assert historical_dashboard.host.sampling_interval == 15
    assert monitor_dashboard.host.refresh_interval == 15
    assert monitor_dashboard.host.sampling_interval == 31
    assert historical_dashboard.explicit == frozenset(("refresh_interval", "period"))
    assert monitor_dashboard.explicit == frozenset(("sampling_interval", "period"))


def test_v2_ranking_all_default_period_survives_compatibility_projection() -> None:
    text = LocalizedText("Stars", "Star 数")
    descriptor = V2ProbeDescriptor(
        "stars-1",
        "0.1.0",
        V2Dataset(text, text),
        (
            V2MetricDescriptor(
                "stars",
                text,
                text,
                CustomUnit("star", text, "suffix", 0),
                "sum",
                V2MetricCapabilities(
                    (),
                    (),
                    {"ranking": V2HistoricalChartCapability(("day",), (), (), ("all",))},
                ),
                {"ranking": CustomChartDefaults("all", None, None)},
            ),
        ),
        (),
    )
    initial = CustomChartConfig(
        "ranking",
        CustomCommandSource("stars", ("stars",)),
        resolve_date_range("ranking", period="14d", since=None, until=None),
    )

    projected = v2_metric_probe_descriptor(descriptor, "stars")
    resolved = apply_custom_probe_defaults(initial, projected, timezone="UTC")

    assert projected.capabilities.charts["ranking"].periods == ("all",)
    assert resolved.date_range.period == "all"


@pytest.mark.parametrize("kind", ("timeline", "calendar", "stack", "ranking"))
def test_custom_declared_periods_limit_every_historical_chart_cycle(kind: str) -> None:
    chart = CustomChartConfig(
        kind,  # type: ignore[arg-type]
        CustomCommandSource("reading", ("reader", "ccuv")),
        resolve_date_range(kind, period="7d", since=None, until=None),
        metric_periods=("7d", "30d"),
    )

    assert adjust_custom_chart(chart, "p").date_range.period == "30d"
    assert adjust_custom_chart(chart, "P").date_range.period == "30d"


def test_v2_custom_ranking_cycles_dataset_subday_periods_in_declaration_order() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="1d", since=None, until=None),
        metric_id="tokens",
        metric_periods=("15s", "90s", "1d", "all"),
    )
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)

    seconds = adjust_custom_chart(chart, "p", now=now, timezone="UTC")
    previous = adjust_custom_chart(chart, "P", now=now, timezone="UTC")

    assert seconds.date_range.period == "all"
    assert previous.date_range.period == "90s"
    wrapped = adjust_custom_chart(seconds, "p", now=now, timezone="UTC")
    assert wrapped.date_range.period == "15s"
    assert wrapped.date_range.end_at == now  # type: ignore[union-attr]


def test_custom_pane_and_empty_pane_are_discriminated() -> None:
    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(), ())
    custom = default_custom_pane(
        "timeline",
        source=CustomCommandSource("weread", ("reader", "ccuv")),
        dashboard=dashboard,
    )

    assert isinstance(custom, CustomChartPaneConfig)
    assert pane_kind(EmptyPaneConfig()) == "empty"
    assert pane_kind(custom) == "custom"
    assert not hasattr(EmptyPaneConfig(), "source")
    assert not hasattr(EmptyPaneConfig(), "provider")


def test_custom_display_adjustments_stay_local() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        resolve_date_range("timeline", period="14d", since=None, until=None),
        group_by="book",
    )

    assert adjust_custom_chart(chart, "p").date_range.period == "30d"
    assert adjust_custom_chart(chart, "P").date_range.period == "7d"
    assert adjust_custom_chart(chart, "+").top == 1
    assert adjust_custom_chart(chart, "o").other == "hide"
    assert adjust_custom_chart(chart, "l").presentation.legend == "inside"
    assert adjust_custom_chart(chart, "d").presentation.density == DENSITIES[0]


def test_custom_ranking_top_adjusts_without_an_explicit_grouping() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        resolve_date_range("ranking", period="14d", since=None, until=None),
        group_by=None,
    )

    assert adjust_custom_chart(chart, "+").top == 1
    assert adjust_custom_chart(chart, "-").top is None
    assert adjust_custom_chart(replace(chart, top=1), "-").top is None
    assert adjust_custom_chart(replace(chart, top=2), "-").top == 1


def test_stack_defaults_to_composition_and_cycles_native_groupings() -> None:
    date_range = resolve_date_range("stack", period="14d", since=None, until=None)
    source = StandaloneLaunch(
        ProcessConfig(), StandaloneHostConfig(), StackConfig("stack", date_range)
    )

    assert source.chart.by == "composition"
    assert adjust_standalone(source, "b").chart.by == "agent"


def test_ranking_period_cycle_includes_today_only() -> None:
    source = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        RankingConfig(
            "ranking", resolve_date_range("ranking", period="7d", since=None, until=None)
        ),
    )

    adjusted = adjust_standalone(source, "P")

    assert adjusted.chart.date_range.period == "1d"
    assert adjusted.chart.date_range.days == 1


def test_ranking_period_cycle_includes_all_with_unix_epoch_anchor() -> None:
    chart = RankingConfig(
        "ranking", resolve_date_range("ranking", period="1y", since=None, until=None)
    )

    all_time = adjust_standalone(
        StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart), "p"
    ).chart
    back_to_year = adjust_standalone(
        StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), all_time), "P"
    ).chart

    assert all_time.date_range.period == "all"
    assert all_time.date_range.since == date(1971, 1, 1)
    assert back_to_year.date_range.period == "1y"


def test_all_period_is_ranking_only() -> None:
    with pytest.raises(UsageError):
        resolve_date_range("timeline", period="all", since=None, until=None)


def test_installed_custom_pane_uses_dashboard_timezone_today() -> None:
    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(timezone="Asia/Shanghai"), ())
    source = CustomCommandSource("weread", ("reader", "ccuv"), source_kind="installed")

    pane = default_custom_pane("timeline", source=source, dashboard=dashboard)

    assert pane.chart.date_range.until == local_today(timezone="Asia/Shanghai")
    assert pane.chart.date_range.period == "14d"


def test_ranking_defaults_to_dot_across_programmatic_and_dashboard_entry_points() -> None:
    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(), ())
    date_range = resolve_date_range("ranking", period=None, since=None, until=None)
    native = default_pane("ranking", dashboard=dashboard)
    custom = default_custom_pane(
        "ranking",
        source=CustomCommandSource("weread", ("reader", "ccuv")),
        dashboard=dashboard,
    )

    assert RankingConfig("ranking", date_range).presentation.style == "dot"
    assert native.chart.presentation == ChartPresentation(style="dot", density="full")
    assert custom.chart.presentation == native.chart.presentation


def test_custom_timeline_defaults_to_existing_historical_period_and_presentation() -> None:
    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(), ())
    pane = default_custom_pane(
        "timeline",
        source=CustomCommandSource("weread", ("reader", "ccuv")),
        dashboard=dashboard,
    )
    native = default_pane("timeline", dashboard=dashboard)

    assert pane.chart.date_range.period == native.chart.date_range.period == "14d"
    assert pane.chart.presentation == native.chart.presentation
    assert pane.chart.presentation == ChartPresentation(style="linear", density="compact")


def test_default_timeline_range_is_fourteen_inclusive_days() -> None:
    result = resolve_date_range(
        "timeline", period=None, since=None, until=None, today=date(2026, 9, 12)
    )
    assert (result.since, result.until, result.days, result.period) == (
        date(2026, 8, 30),
        date(2026, 9, 12),
        14,
        "14d",
    )
    assert result.relative_until


def test_relative_range_advances_but_historical_range_stays_fixed() -> None:
    relative = timeline().chart.date_range
    assert refresh_date_range(relative, today=date(2026, 9, 13)).until == date(2026, 9, 13)
    fixed = timeline(rolling=False).chart.date_range
    assert refresh_date_range(fixed, today=date(2026, 9, 13)) == fixed


@pytest.mark.parametrize(
    ("period", "since", "until"),
    [
        ("0d", None, None),
        ("7d", "2026-09-01", None),
        (None, "2026-09-10", "2026-09-01"),
        (None, None, "2026-09-13"),
    ],
)
def test_invalid_ranges_fail(period: str | None, since: str | None, until: str | None) -> None:
    with pytest.raises(UsageError):
        resolve_date_range(
            "timeline",
            period=period,
            since=since,
            until=until,
            today=date(2026, 9, 12),
        )


@pytest.mark.parametrize(
    ("density", "expected"),
    (("minimal", False), ("compact", False), ("full", True), ("detailed", True)),
)
def test_complete_content_density_contract(density: str, expected: bool) -> None:
    assert has_complete_content(cast(Density, density)) is expected


def test_chart_density_has_exactly_four_values_and_defaults_to_detailed() -> None:
    assert DENSITIES == ("minimal", "compact", "full", "detailed")
    assert ChartPresentation().density == "detailed"


def test_runtime_adjustments_replace_owned_nested_configs() -> None:
    source = timeline(by="model", top=10)
    assert adjust_standalone(source, "p").chart.date_range.period == "30d"
    assert adjust_standalone(source, "g").chart.granularity == "week"
    assert adjust_standalone(source, "s").chart.presentation.style == "step"
    assert adjust_standalone(source, "d").chart.presentation.density == "minimal"
    assert (
        adjust_standalone(adjust_standalone(source, "d"), "d").chart.presentation.density
        == "compact"
    )
    assert (
        adjust_standalone(
            adjust_standalone(adjust_standalone(source, "d"), "d"), "d"
        ).chart.presentation.density
        == "full"
    )
    assert (
        adjust_standalone(
            adjust_standalone(adjust_standalone(adjust_standalone(source, "d"), "d"), "d"),
            "d",
        ).chart.presentation.density
        == "detailed"
    )
    assert adjust_standalone(source, "S").chart.presentation.style == "stem"
    assert adjust_standalone(source, "G").chart.granularity == "year"
    assert adjust_standalone(source, "D").chart.presentation.density == "full"
    for uppercase_alias in ("K", "L", "C", "O", "W", "I"):
        assert adjust_standalone(source, uppercase_alias) == source
    assert adjust_standalone(source, "B").chart.by == "agent"
    assert adjust_standalone(source, "+").chart.top == 11
    assert adjust_standalone(source, "k").chart.weekdays == "hide"
    assert adjust_standalone(timeline(rolling=False), "p") == timeline(rolling=False)


@pytest.mark.parametrize(
    ("chart", "key", "expected_by"),
    (
        (
            TimelineConfig(
                "timeline", resolve_date_range("timeline", period="14d", since=None, until=None)
            ),
            "b",
            "agent",
        ),
        (
            StackConfig(
                "stack", resolve_date_range("stack", period="14d", since=None, until=None), top=None
            ),
            "b",
            "agent",
        ),
        (
            RankingConfig(
                "ranking",
                resolve_date_range("ranking", period="14d", since=None, until=None),
                top=None,
            ),
            "B",
            "composition",
        ),
        (MonitorConfig("monitor", 3600, top=None), "b", "model"),
    ),
)
def test_builtin_grouping_cycles_preserve_unbounded_top(chart, key, expected_by) -> None:
    source = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    updated = adjust_standalone(source, key)

    assert updated.chart.by == expected_by
    assert updated.chart.top is None


def test_builtin_grouping_cycles_preserve_explicit_top_in_both_directions() -> None:
    chart = TimelineConfig(
        "timeline",
        resolve_date_range("timeline", period="14d", since=None, until=None),
        by="model",
        top=7,
    )
    source = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    forward = adjust_standalone(source, "b")
    reverse = adjust_standalone(source, "B")
    to_total = adjust_standalone(
        StandaloneLaunch(
            ProcessConfig(),
            StandaloneHostConfig(),
            TimelineConfig(
                "timeline",
                resolve_date_range("timeline", period="14d", since=None, until=None),
                by="composition",
                top=7,
            ),
        ),
        "b",
    )

    assert (forward.chart.by, forward.chart.top) == ("project", 7)
    assert (reverse.chart.by, reverse.chart.top) == ("agent", 7)
    assert to_total.chart.top == 7


def test_calendar_style_key_cycles_between_relative_and_grid() -> None:
    source = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        CalendarConfig(
            "calendar",
            resolve_date_range(
                "calendar",
                period="7d",
                since=None,
                until=None,
                today=date(2026, 9, 12),
            ),
        ),
    )

    grid = adjust_standalone(source, "s")
    assert grid.chart.presentation.style == "grid"
    assert adjust_standalone(grid, "s").chart.presentation.style == "relative"


def test_period_keys_adjust_through_the_shared_historical_cycle() -> None:
    source = timeline()

    larger = adjust_standalone(source, "p")
    smaller = adjust_standalone(source, "P")
    weekly = adjust_standalone(source, "g")

    assert larger.chart.date_range.period == "30d"
    assert larger.chart.date_range.since == date(2026, 8, 14)
    assert smaller.chart.date_range.period == "7d"
    assert smaller.chart.date_range.since == date(2026, 9, 6)
    assert weekly.chart.granularity == "week"
    assert weekly.chart.date_range.period == "8w"
    assert adjust_standalone(weekly, "P").chart.date_range.period == "8w"
    week_to_date = adjust_standalone(
        replace(
            source,
            chart=replace(source.chart, date_range=replace(source.chart.date_range, period="365d")),
        ),
        "p",
    )
    assert week_to_date.chart.date_range.period == "1w"
    assert week_to_date.chart.date_range.since == date(2026, 9, 7)
    assert adjust_standalone(week_to_date, "p").chart.date_range.period == "1mo"
    assert (
        adjust_standalone(adjust_standalone(week_to_date, "p"), "p").chart.date_range.period == "1y"
    )
    assert (
        adjust_standalone(
            replace(
                source,
                chart=replace(
                    source.chart, date_range=replace(source.chart.date_range, period="7d")
                ),
            ),
            "P",
        ).chart.date_range.period
        == "1y"
    )
    assert adjust_standalone(timeline(rolling=False), "P") == timeline(rolling=False)


def test_replace_chart_filters_preserves_every_other_setting() -> None:
    source = timeline(by="model", top=10)
    filters = Filters(agents=("Claude Code",), models=("sonnet",))

    updated = replace_chart_filters(source, filters)

    assert updated.chart.filters == filters
    assert replace(updated.chart, filters=source.chart.filters) == source.chart
    assert updated.host == source.host
    assert updated.process == source.process


def test_monitor_list_is_available_for_total_and_grouped_views() -> None:
    assert "list" in compatible_styles("ranking", "model")
    assert "list" in compatible_styles("monitor", None)
    assert "ranking-dot" in compatible_styles("monitor", "model")
    assert "bars" not in compatible_styles("monitor", "model")

    monitor = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        MonitorConfig("monitor", 3600, presentation=ChartPresentation(style="ranking")),
    )
    assert adjust_standalone(monitor, "s").chart.presentation.style == "ranking-dot"
    assert adjust_standalone(monitor, "b").chart.presentation.style == "ranking"


def test_monitor_distribution_adjustments_change_only_display_projection() -> None:
    monitor = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=15),
        MonitorConfig("monitor", 3600, presentation=ChartPresentation(style="cumulative-bars")),
    )

    yesterday = adjust_standalone(monitor, "w")
    half_hour = adjust_standalone(monitor, "g")

    assert yesterday.chart.day_window == "yesterday"
    assert yesterday.chart.distribution_granularity == "hour"
    assert yesterday.chart.window_seconds == monitor.chart.window_seconds
    assert half_hour.chart.day_window == "today"
    assert half_hour.chart.distribution_granularity == "half-hour"
    assert half_hour.chart.window_seconds == monitor.chart.window_seconds
    assert adjust_standalone(monitor, "i").host.interval == 30


def test_monitor_ranking_styles_do_not_adjust_the_rolling_window() -> None:
    for style in ("ranking", "ranking-dot", "list"):
        monitor = StandaloneLaunch(
            ProcessConfig(),
            StandaloneHostConfig(),
            MonitorConfig("monitor", 3600, presentation=ChartPresentation(style=style)),
        )
        assert adjust_standalone(monitor, "w") == monitor

import shlex
from dataclasses import replace
from datetime import date
from typing import cast

import pytest

from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.command_copy import format_command, format_full_command, wrap_command
from ccusage_viz.configuration import (
    apply_custom_probe_defaults,
    default_custom_pane,
    default_pane,
)
from ccusage_viz.core.time import DateRange, local_today, refresh_date_range
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    DENSITIES,
    CalendarConfig,
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


def _probe_descriptor() -> CustomProbeDescriptor:
    text = LocalizedText("WeRead", "微信读书")
    return CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(text, text, CustomUnit("page", text, "suffix", 0)),
        CustomCapabilities(
            (),
            (),
            {
                "ranking": CustomChartCapability(("day",), ("book",), ()),
                "timeline": CustomChartCapability(("day",), (), ()),
            },
        ),
        {
            "ranking": CustomChartDefaults("1y", "book", 10),
            "timeline": CustomChartDefaults("14d", None, None),
        },
        (),
    )


def test_custom_source_requires_dataset_and_nonempty_argv() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    assert source.dataset_id == "weread"
    assert source.source_kind == "command"
    with pytest.raises(ValueError, match="dataset"):
        CustomCommandSource("", ("reader",))
    with pytest.raises(ValueError, match="command"):
        CustomCommandSource("weread", ())
    with pytest.raises(ValueError, match="source_kind"):
        CustomCommandSource("weread", ("reader",), source_kind="other")  # type: ignore[arg-type]


def test_custom_probe_defaults_apply_to_an_unconfigured_ranking_chart() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    initial = CustomChartConfig(
        "ranking",
        source,
        resolve_date_range("ranking", period=None, since=None, until=None, today=date(2026, 9, 30)),
    )

    resolved = apply_custom_probe_defaults(initial, _probe_descriptor(), timezone="UTC")

    assert resolved.date_range.period == "1y"
    assert resolved.date_range.since == date(2026, 1, 1)
    assert resolved.date_range.until == local_today(timezone="UTC")
    assert resolved.group_by == "book"
    assert resolved.top == 10


def test_custom_probe_defaults_preserve_explicit_range_grouping_and_top() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    initial = CustomChartConfig(
        "ranking",
        source,
        DateRange(date(2026, 8, 1), date(2026, 8, 31), fixed_bounds=True),
        group_by="book",
        top=3,
        initial_explicit=frozenset({"since", "until", "group_by", "top"}),
    )

    resolved = apply_custom_probe_defaults(initial, _probe_descriptor(), timezone="UTC")

    assert resolved == initial


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


def test_stack_defaults_to_composition_and_cycles_native_groupings() -> None:
    date_range = resolve_date_range("stack", period="14d", since=None, until=None)
    source = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), StackConfig("stack", date_range))

    assert source.chart.by == "composition"
    assert adjust_standalone(source, "b").chart.by == "agent"


def test_ranking_period_cycle_includes_today_only() -> None:
    source = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        RankingConfig("ranking", resolve_date_range("ranking", period="7d", since=None, until=None)),
    )

    adjusted = adjust_standalone(source, "P")

    assert adjusted.chart.date_range.period == "1d"
    assert adjusted.chart.date_range.days == 1


def test_ranking_period_cycle_includes_all_with_unix_epoch_anchor() -> None:
    chart = RankingConfig("ranking", resolve_date_range("ranking", period="1y", since=None, until=None))

    all_time = adjust_standalone(StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart), "p").chart
    back_to_year = adjust_standalone(StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), all_time), "P").chart

    assert all_time.date_range.period == "all"
    assert all_time.date_range.since == date(1971, 1, 1)
    assert back_to_year.date_range.period == "1y"


def test_all_period_is_ranking_only() -> None:
    with pytest.raises(UsageError):
        resolve_date_range("timeline", period="all", since=None, until=None)


def test_installed_custom_command_round_trips_without_executable_path() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource(
            "weread",
            ("/private/datasets/weread/bin/ccuv-dataset-weread", "ccuv"),
            source_kind="installed",
        ),
        resolve_date_range("timeline", period="14d", since=None, until=None),
    )
    launch = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    command = format_command(launch)

    assert "--dataset weread" in command
    assert "/private/datasets" not in command
    assert "--command" not in command
    assert "--installed" not in shlex.split(command)


def test_custom_standalone_command_round_trips() -> None:
    parser = build_parser(load_translator("en"))
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "export", "--format=json")),
        resolve_date_range(
            "timeline", period="30d", since=None, until=None, today=date(2026, 9, 30)
        ),
        filters=(("category", ("fiction", "literature")),),
        group_by="book",
        top=5,
        granularity="month",
        presentation=ChartPresentation(style="step", density="compact"),
    )
    launch = StandaloneLaunch(
        ProcessConfig(query_timeout=12), StandaloneHostConfig(timezone="Asia/Shanghai"), chart
    )

    command = format_full_command(launch)
    reparsed = _to_options(parser.parse_args(shlex.split(command)[1:]))

    expected = replace(
        launch,
        chart=replace(
            launch.chart,
            date_range=resolve_date_range(
                "timeline", period="30d", since=None, until=None, today=local_today()
            ),
        ),
    )
    assert reparsed == expected


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
    assert native.chart.presentation == ChartPresentation(style="dot", density="compact")
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


def timeline(
    *, rolling: bool = True, by: str | None = None, top: int | None = None
) -> StandaloneLaunch:
    date_range = (
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 12)
        )
        if rolling
        else resolve_date_range(
            "timeline",
            period=None,
            since="2026-01-01",
            until="2026-08-31",
            today=date(2026, 9, 12),
        )
    )
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        TimelineConfig("timeline", date_range, by=by, top=top, other="hide"),
    )


def test_wrap_command_breaks_at_tokens_within_display_width() -> None:
    command = "ccuv chart timeline --period 14d --by model --top 3"
    wrapped = wrap_command(command, 20)
    assert "\n" in wrapped
    assert " ".join(wrapped.splitlines()) == command
    assert all(display_width(line) <= 20 for line in wrapped.splitlines())


def test_concise_commands_omit_effective_defaults() -> None:
    parser = build_parser(load_translator("en"))

    assert format_command(_to_options(parser.parse_args(["chart", "timeline"]))) == (
        "ccuv chart timeline --timezone Asia/Shanghai"
    )
    assert format_command(_to_options(parser.parse_args(["chart", "ranking"]))) == (
        "ccuv chart ranking --timezone Asia/Shanghai"
    )
    assert format_command(_to_options(parser.parse_args(["chart", "monitor"]))) == (
        "ccuv chart monitor --timezone Asia/Shanghai"
    )

    explicit = _to_options(
        parser.parse_args(
            [
                "chart",
                "timeline",
                "--period",
                "14d",
                "--granularity",
                "day",
                "--weekdays",
                "show",
                "--other",
                "show",
                "--style",
                "linear",
                "--density",
                "detailed",
                "--legend",
                "below-title",
            ]
        )
    )
    assert format_command(explicit) == "ccuv chart timeline --timezone Asia/Shanghai"


def test_concise_monitor_command_uses_grouped_effective_defaults() -> None:
    parser = build_parser(load_translator("en"))
    grouped = _to_options(parser.parse_args(["chart", "monitor", "--by", "model"]))

    assert format_command(grouped) == "ccuv chart monitor --by model --timezone Asia/Shanghai"
    non_default = _to_options(
        parser.parse_args(["chart", "monitor", "--by", "model", "--top", "4", "--style", "points"])
    )
    assert format_command(non_default).endswith("--timezone Asia/Shanghai --style points")
    assert "--by model --top 4" in format_command(non_default)


def test_concise_command_keeps_effect_bearing_private_project_filter() -> None:
    parser = build_parser(load_translator("en"))
    launch = _to_options(parser.parse_args(["chart", "timeline", "--project", "/private/project"]))

    command = format_command(launch)
    reparsed = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert command == "ccuv chart timeline --project /private/project --timezone Asia/Shanghai"
    assert reparsed.chart.filters == launch.chart.filters


def test_project_aggregation_is_rejected_by_chart_commands() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError):
        parser.parse_args(["chart", "ranking", "--project-aggregation", "exact"])


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
    for uppercase_alias in ("D", "K", "L", "C", "O", "W", "I"):
        assert adjust_standalone(source, uppercase_alias) == source
    assert adjust_standalone(source, "B").chart.by == "agent"
    assert adjust_standalone(source, "+").chart.top == 11
    assert adjust_standalone(source, "k").chart.weekdays == "hide"
    assert adjust_standalone(timeline(rolling=False), "p") == timeline(rolling=False)


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
        replace(source, chart=replace(source.chart, date_range=replace(source.chart.date_range, period="365d"))),
        "p",
    )
    assert week_to_date.chart.date_range.period == "1w"
    assert week_to_date.chart.date_range.since == date(2026, 9, 7)
    assert adjust_standalone(week_to_date, "p").chart.date_range.period == "1mo"
    assert adjust_standalone(
        adjust_standalone(week_to_date, "p"), "p"
    ).chart.date_range.period == "1y"
    assert adjust_standalone(
        replace(source, chart=replace(source.chart, date_range=replace(source.chart.date_range, period="7d"))),
        "P",
    ).chart.date_range.period == "1y"
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
    assert "list" in compatible_styles("monitor", None)
    assert "list" in compatible_styles("monitor", "model")
    assert "bars" not in compatible_styles("monitor", "model")
    assert "list" not in compatible_styles("ranking", "model")

    monitor = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        MonitorConfig("monitor", 3600, presentation=ChartPresentation(style="ranking")),
    )
    assert adjust_standalone(monitor, "s").chart.presentation.style == "list"
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


def test_monitor_ranking_and_list_do_not_adjust_the_rolling_window() -> None:
    for style in ("ranking", "list"):
        monitor = StandaloneLaunch(
            ProcessConfig(),
            StandaloneHostConfig(),
            MonitorConfig("monitor", 3600, presentation=ChartPresentation(style=style)),
        )
        assert adjust_standalone(monitor, "w") == monitor


def test_monitor_copy_keeps_startup_selection() -> None:
    launch = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=15),
        MonitorConfig(
            "monitor",
            3600,
            filters=Filters(agents=("claude",), models=("sonnet",)),
            presentation=ChartPresentation(style="line"),
            by="model",
        ),
    )
    assert format_command(launch) == "ccuv chart monitor --by model --agent claude --model sonnet"


def test_full_command_preserves_implicit_until_semantics() -> None:
    parser = build_parser(load_translator("en"))
    launch = _to_options(parser.parse_args(["chart", "timeline", "--since", "2026-09-01"]))

    reparsed = _to_options(parser.parse_args(shlex.split(format_full_command(launch))[1:]))

    assert reparsed.chart.date_range == launch.chart.date_range
    assert reparsed.chart.date_range.implicit_until
    assert reparsed.chart.date_range.fixed_bounds


def test_command_serializers_round_trip_typed_launch() -> None:
    launch = StandaloneLaunch(
        ProcessConfig(ccusage_bin="/private/bin/ccusage"),
        StandaloneHostConfig(ascii=True, interval=5),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 9, 1), date(2026, 9, 14)),
            filters=Filters(
                agents=("claude",),
                models=("public model",),
                projects=("/private/project", "demo-project"),
            ),
            presentation=ChartPresentation(theme="nord", style="stem", density="compact"),
            by="model",
            top=3,
        ),
    )
    safe, full = format_command(launch), format_full_command(launch)
    assert "--project /private/project" in safe
    assert "--project /private/project" in full
    assert "--ccusage-bin /private/bin/ccusage" in full
    assert "--density compact" in safe
    assert "--density compact" in full
    parser = build_parser(load_translator("en"))
    for generated in (safe, full):
        reparsed = _to_options(parser.parse_args(shlex.split(generated)[1:]))
        assert isinstance(reparsed, StandaloneLaunch)
        assert reparsed.chart.kind == "timeline"
        assert reparsed.chart.presentation.density == "compact"
        assert reparsed.host.interval == 5

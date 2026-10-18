import shlex
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

import ccusage_viz.command_copy as command_copy_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_copy import copy_command, format_command, format_full_command, wrap_command
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange, local_today
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    Filters,
    MonitorConfig,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    custom_command_sources_equivalent,
    resolve_date_range,
)


@pytest.mark.parametrize(
    ("available", "expected"),
    (
        ({"pbcopy"}, ["/bin/pbcopy"]),
        ({"clip.exe"}, ["/bin/clip.exe"]),
        ({"wl-copy"}, ["/bin/wl-copy"]),
        ({"xclip"}, ["/bin/xclip", "-selection", "clipboard"]),
        ({"xsel"}, ["/bin/xsel", "--clipboard", "--input"]),
    ),
)
def test_copy_command_selects_platform_clipboard_backend(
    monkeypatch: pytest.MonkeyPatch, available: set[str], expected: list[str]
) -> None:
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(
        command_copy_module,
        "which",
        lambda name: f"/bin/{name}" if name in available else None,
    )
    monkeypatch.setattr(
        command_copy_module.subprocess,
        "run",
        lambda arguments, **kwargs: calls.append((arguments, kwargs["input"])),
    )

    assert copy_command("copied text")
    assert calls == [(expected, "copied text")]


def test_copy_command_reports_unavailable_without_a_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_copy_module, "which", lambda _name: None)

    assert not copy_command("copied text")


def test_custom_command_sources_use_filesystem_identity_for_absolute_paths(tmp_path) -> None:
    executable = tmp_path / "dataset"
    database = tmp_path / "catalog.db"
    executable.write_text("dataset")
    database.write_text("catalog")
    executable_alias = tmp_path / "dataset-alias"
    database_alias = tmp_path / "catalog-alias.db"
    executable_alias.symlink_to(executable)
    database_alias.symlink_to(database)

    registered = CustomCommandSource("reading", (str(executable), "--database", str(database)))
    equivalent = CustomCommandSource(
        "reading", (str(executable_alias), "--database", str(database_alias))
    )

    assert custom_command_sources_equivalent(registered, equivalent)
    assert not custom_command_sources_equivalent(
        registered,
        CustomCommandSource("reading", (str(executable_alias), "--database", "catalog.db")),
    )
    DashboardLaunch(
        ProcessConfig(),
        DashboardHostConfig(),
        (
            CustomChartPaneConfig(
                CustomChartConfig(
                    "timeline", registered, DateRange(date(2026, 1, 1), date(2026, 1, 1))
                )
            ),
            CustomChartPaneConfig(
                CustomChartConfig(
                    "ranking", equivalent, DateRange(date(2026, 1, 1), date(2026, 1, 1))
                )
            ),
        ),
    )


def test_subday_ranking_command_preserves_period_without_dates_or_granularity() -> None:
    end = datetime(2026, 10, 15, 12, tzinfo=UTC)
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        TimestampRange(end - timedelta(minutes=10), end, relative_until=True, period="10m"),
        metric_id="tokens",
        granularity="legacy",
    )
    launch = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    command = format_full_command(launch)

    assert "--period 10m" in command
    assert "--since" not in command
    assert "--until" not in command
    assert "--granularity" not in command


def test_fixed_timestamp_range_command_copy_is_explicitly_unsupported() -> None:
    end = datetime(2026, 10, 15, 12, tzinfo=UTC)
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        TimestampRange(end - timedelta(minutes=10), end, fixed_bounds=True),
        metric_id="tokens",
    )
    launch = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    with pytest.raises(ValueError, match="CLI has no timestamp-bound flags"):
        format_full_command(launch)


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


def test_wrap_command_breaks_at_tokens_within_display_width() -> None:
    command = "ccuv chart timeline --period 14d --by model --top 3"
    wrapped = wrap_command(command, 20)
    assert "\n" in wrapped
    assert " ".join(wrapped.splitlines()) == command
    assert all(display_width(line) <= 20 for line in wrapped.splitlines())


def test_concise_commands_omit_effective_defaults() -> None:
    parser = build_parser(load_translator("en"))

    timeline = _to_options(parser.parse_args(["chart", "timeline"]))
    ranking = _to_options(parser.parse_args(["chart", "ranking"]))
    monitor = _to_options(parser.parse_args(["chart", "monitor"]))

    assert format_command(timeline) == f"ccuv chart timeline --timezone {timeline.host.timezone}"
    assert format_command(ranking) == f"ccuv chart ranking --timezone {ranking.host.timezone}"
    assert format_command(monitor) == f"ccuv chart monitor --timezone {monitor.host.timezone}"

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
    assert format_command(explicit) == f"ccuv chart timeline --timezone {explicit.host.timezone}"


def test_concise_monitor_command_uses_grouped_effective_defaults() -> None:
    parser = build_parser(load_translator("en"))
    grouped = _to_options(parser.parse_args(["chart", "monitor", "--by", "model"]))

    assert format_command(grouped) == (
        f"ccuv chart monitor --by model --timezone {grouped.host.timezone}"
    )
    non_default = _to_options(
        parser.parse_args(["chart", "monitor", "--by", "model", "--top", "4", "--style", "points"])
    )
    assert format_command(non_default).endswith(
        f"--timezone {non_default.host.timezone} --style points"
    )
    assert "--by model --top 4" in format_command(non_default)


def test_concise_command_keeps_effect_bearing_private_project_filter() -> None:
    parser = build_parser(load_translator("en"))
    launch = _to_options(parser.parse_args(["chart", "timeline", "--project", "/private/project"]))

    command = format_command(launch)
    reparsed = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert command == (
        f"ccuv chart timeline --project /private/project --timezone {launch.host.timezone}"
    )
    assert reparsed.chart.filters == launch.chart.filters


def test_project_aggregation_is_rejected_by_chart_commands() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError):
        parser.parse_args(["chart", "ranking", "--project-aggregation", "exact"])


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

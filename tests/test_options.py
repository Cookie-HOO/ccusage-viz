import shlex
from datetime import date

import pytest

from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.command_copy import format_command, format_full_command, wrap_command
from ccusage_viz.core.time import DateRange, refresh_date_range
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    Filters,
    MonitorConfig,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
    resolve_date_range,
)


def timeline(
    *, rolling: bool = True, by: str | None = None, top: int | None = None
) -> StandaloneLaunch:
    date_range = (
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None, today=date(2026, 9, 12)
        )
        if rolling
        else resolve_date_range(
            "timeline",
            period=None,
            since="2026-01-01",
            until="2026-08-31",
            timezone=None,
            today=date(2026, 9, 12),
        )
    )
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        TimelineConfig("timeline", date_range, by=by, top=top, other="hide"),
    )


def test_wrap_command_breaks_at_tokens_within_display_width() -> None:
    command = "ccuv timeline --period 14d --by model --top 3"
    wrapped = wrap_command(command, 20)
    assert "\n" in wrapped
    assert " ".join(wrapped.splitlines()) == command
    assert all(display_width(line) <= 20 for line in wrapped.splitlines())


def test_default_timeline_range_is_fourteen_inclusive_days() -> None:
    result = resolve_date_range(
        "timeline", period=None, since=None, until=None, timezone=None, today=date(2026, 9, 12)
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
            timezone=None,
            today=date(2026, 9, 12),
        )


def test_runtime_adjustments_replace_owned_nested_configs() -> None:
    source = timeline(by="model", top=10)
    assert adjust_standalone(source, "p").chart.date_range.period == "30d"
    assert adjust_standalone(source, "g").chart.granularity == "month"
    assert adjust_standalone(source, "s").chart.presentation.style == "step"
    assert adjust_standalone(source, "+").chart.top == 11
    assert adjust_standalone(source, "k").chart.weekdays == "hide"
    assert adjust_standalone(timeline(rolling=False), "p") == timeline(rolling=False)


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
    assert (
        format_command(launch)
        == "ccuv monitor --window 1h --by model --agent claude --model sonnet --style line"
    )


def test_full_command_preserves_implicit_until_semantics() -> None:
    parser = build_parser(load_translator("en"))
    launch = _to_options(parser.parse_args(["timeline", "--since", "2026-09-01"]))

    reparsed = _to_options(parser.parse_args(shlex.split(format_full_command(launch))[1:]))

    assert reparsed.chart.date_range == launch.chart.date_range
    assert reparsed.chart.date_range.implicit_until
    assert not reparsed.chart.date_range.fixed_bounds


def test_command_serializers_round_trip_typed_launch() -> None:
    launch = StandaloneLaunch(
        ProcessConfig(ccusage_bin="/private/bin/ccusage"),
        StandaloneHostConfig(timezone="UTC", ascii=True, interval=5),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 9, 1), date(2026, 9, 14), "UTC"),
            filters=Filters(
                agents=("claude",),
                models=("public model",),
                projects=("/private/project", "demo-project"),
            ),
            presentation=ChartPresentation(theme="nord", style="stem"),
            by="model",
            top=3,
        ),
    )
    safe, full = format_command(launch), format_full_command(launch)
    assert "/private" not in safe
    assert "--project /private/project" in full
    assert "--ccusage-bin /private/bin/ccusage" in full
    parser = build_parser(load_translator("en"))
    for generated in (safe, full):
        reparsed = _to_options(parser.parse_args(shlex.split(generated)[1:]))
        assert isinstance(reparsed, StandaloneLaunch)
        assert reparsed.chart.kind == "timeline"
        assert reparsed.host.interval == 5

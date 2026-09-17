from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.command_copy import format_command, format_full_command, wrap_command
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.options import (
    CommandOptions,
    DateRange,
    adjust_option,
    refresh_date_range,
    resolve_date_range,
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
    assert result.since == date(2026, 8, 30)
    assert result.until == date(2026, 9, 12)
    assert result.days == 14
    assert result.relative_until
    assert result.period == "14d"


def test_relative_range_advances_but_historical_range_stays_fixed() -> None:
    relative = resolve_date_range(
        "timeline", period="7d", since=None, until=None, timezone=None, today=date(2026, 9, 12)
    )
    advanced = refresh_date_range(relative, today=date(2026, 9, 13))
    assert advanced.since == date(2026, 9, 7)
    assert advanced.until == date(2026, 9, 13)

    historical = resolve_date_range(
        "timeline",
        period=None,
        since="2026-08-01",
        until="2026-08-10",
        timezone=None,
        today=date(2026, 9, 12),
    )
    assert refresh_date_range(historical, today=date(2026, 9, 13)) == historical


def test_invalid_timezone_and_overflowing_days_are_localized() -> None:
    with pytest.raises(UsageError) as timezone_error:
        resolve_date_range("timeline", period=None, since=None, until=None, timezone="../UTC")
    assert timezone_error.value.key == "error.timezone"

    with pytest.raises(UsageError) as days_error:
        resolve_date_range(
            "timeline",
            period="999999999d",
            since=None,
            until=None,
            timezone=None,
            today=date(2026, 9, 12),
        )
    assert days_error.value.key == "error.arguments"


def test_explicit_start_and_end_are_marked_as_fixed_bounds() -> None:
    result = resolve_date_range(
        "timeline",
        period=None,
        since="2026-08-01",
        until="2026-08-10",
        timezone=None,
        today=date(2026, 9, 12),
    )
    assert result.fixed_bounds


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


def test_runtime_period_cycles_only_for_rolling_history() -> None:
    rolling = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None, today=date(2026, 9, 12)
        ),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )
    first = adjust_option(rolling, "p")
    assert first.date_range.period == "30d"
    assert first.date_range.days == 30
    assert adjust_option(adjust_option(first, "p"), "p").date_range.period == "7d"

    fixed = replace(
        rolling,
        date_range=resolve_date_range(
            "timeline",
            period=None,
            since="2026-09-01",
            until="2026-09-12",
            timezone=None,
            today=date(2026, 9, 12),
        ),
    )
    assert adjust_option(fixed, "p") == fixed
    assert adjust_option(rolling, "d") == rolling


def test_runtime_aggregation_cycles_and_uses_natural_default_periods() -> None:
    options = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None, today=date(2026, 9, 12)
        ),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )

    observed = []
    for _ in range(4):
        options = adjust_option(options, "g")
        observed.append((options.aggregation, options.date_range.period))

    assert observed == [
        ("month", "13mo"),
        ("quarter", "8q"),
        ("year", "5y"),
        ("day", "14d"),
    ]


def test_explicit_twelve_month_period_remains_legal() -> None:
    result = resolve_date_range(
        "timeline",
        period="12mo",
        since=None,
        until=None,
        timezone=None,
        aggregation="month",
        today=date(2026, 9, 12),
    )

    assert result.period == "12mo"
    assert result.since == date(2025, 10, 1)
    assert result.until == date(2026, 9, 12)


def test_fixed_range_aggregation_changes_without_rewriting_bounds() -> None:
    fixed = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline",
            period=None,
            since="2026-01-01",
            until="2026-08-31",
            timezone=None,
            today=date(2026, 9, 12),
        ),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )

    adjusted = adjust_option(fixed, "g")
    assert adjusted.aggregation == "month"
    assert adjusted.date_range == fixed.date_range
    assert adjusted.date_range.fixed_bounds


def test_timeline_style_cycles_through_uniform_point_variants() -> None:
    timeline = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None
        ),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )

    styles = [timeline.style]
    for _ in range(6):
        timeline = adjust_option(timeline, "s")
        styles.append(timeline.style)
    assert styles == ["linear", "step", "no-line", "points", "line-points", "stem", "area"]
    assert adjust_option(timeline, "s").style == "linear"
    assert adjust_option(timeline, "S").style == "stem"


def test_runtime_top_increases_without_wrapping_and_stops_at_one() -> None:
    timeline = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None
        ),
        by="model",
        top=10,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )

    assert adjust_option(timeline, "+").top == 11
    assert adjust_option(replace(timeline, top=128), "+").top == 129
    assert adjust_option(replace(timeline, top=1), "-").top == 1
    assert adjust_option(replace(timeline, top=None), "-").top == 1


def test_runtime_weekday_cycles_with_the_displayed_key_only() -> None:
    timeline = CommandOptions(
        command="timeline",
        date_range=resolve_date_range(
            "timeline", period="14d", since=None, until=None, timezone=None
        ),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=5,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
    )

    shown = adjust_option(timeline, "k")
    hidden = adjust_option(shown, "k")
    assert (shown.weekday_mode, hidden.weekday_mode) == ("show", "hidden")
    assert adjust_option(hidden, "k").weekday_mode == "auto"
    assert adjust_option(timeline, "w") == timeline


def test_monitor_copy_keeps_startup_agent_and_model_selection() -> None:
    options = CommandOptions(
        command="monitor",
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 1), None),
        by="model",
        top=None,
        show_other=False,
        split_cache=False,
        agents=("claude",),
        models=("sonnet",),
        projects=(),
        watch=None,
        demo=None,
        ccusage_bin="ccusage",
        timeout=30,
        no_color=False,
        ascii=False,
        window_seconds=3600,
        interval=15,
        style="line",
    )

    assert format_command(options) == (
        "ccuv monitor --window 1h --interval 15 --by model --agent claude "
        "--model sonnet --style line"
    )


def test_copied_command_is_safe_and_reproducible() -> None:
    options = CommandOptions(
        command="timeline",
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 14), "UTC"),
        by="model",
        top=3,
        show_other=True,
        split_cache=False,
        agents=("claude",),
        models=("public model",),
        projects=("/private/project", "demo-project"),
        watch=5,
        demo=None,
        ccusage_bin="/private/bin/ccusage",
        timeout=30,
        no_color=False,
        ascii=True,
        color_scheme="nord",
        style="stem",
        no_summary=True,
    )

    command = format_command(options)
    assert command == (
        "ccuv timeline --since 2026-09-01 --until 2026-09-14 --timezone UTC "
        "--by model --top 3 --show-other --no-summary --agent claude --model 'public model' "
        "--project demo-project --watch 5 --theme nord --style stem --ascii"
    )
    assert "/private" not in command
    assert "--ccusage-bin" not in command
    assert "--timeout" not in command

    full_command = format_full_command(options)
    assert "--project /private/project" in full_command
    assert "--ccusage-bin /private/bin/ccusage" in full_command
    assert "--timeout 30" in full_command
    assert "--aggregate day" in full_command
    assert "--weekdays auto" in full_command
    assert "--legend-position below-title" in full_command

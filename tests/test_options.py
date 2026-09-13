from datetime import date

import pytest

from ccusage_viz.command_copy import format_command
from ccusage_viz.errors import UsageError
from ccusage_viz.options import CommandOptions, DateRange, refresh_date_range, resolve_date_range


def test_default_timeline_range_is_fourteen_inclusive_days() -> None:
    result = resolve_date_range(
        "timeline", days=None, since=None, until=None, timezone=None, today=date(2026, 9, 12)
    )
    assert result.since == date(2026, 8, 30)
    assert result.until == date(2026, 9, 12)
    assert result.days == 14
    assert result.relative_until
    assert result.relative_days == 14


def test_relative_range_advances_but_historical_range_stays_fixed() -> None:
    relative = resolve_date_range(
        "timeline", days=7, since=None, until=None, timezone=None, today=date(2026, 9, 12)
    )
    advanced = refresh_date_range(relative, today=date(2026, 9, 13))
    assert advanced.since == date(2026, 9, 7)
    assert advanced.until == date(2026, 9, 13)

    historical = resolve_date_range(
        "timeline",
        days=7,
        since=None,
        until="2026-08-10",
        timezone=None,
        today=date(2026, 9, 12),
    )
    assert refresh_date_range(historical, today=date(2026, 9, 13)) == historical


def test_invalid_timezone_and_overflowing_days_are_localized() -> None:
    with pytest.raises(UsageError) as timezone_error:
        resolve_date_range("timeline", days=None, since=None, until=None, timezone="../UTC")
    assert timezone_error.value.key == "error.timezone"

    with pytest.raises(UsageError) as days_error:
        resolve_date_range(
            "timeline",
            days=999_999_999,
            since=None,
            until=None,
            timezone=None,
            today=date(2026, 9, 12),
        )
    assert days_error.value.key == "error.days_positive"


def test_days_can_end_on_historical_until() -> None:
    result = resolve_date_range(
        "timeline", days=7, since=None, until="2026-08-10", timezone=None, today=date(2026, 9, 12)
    )
    assert result.since == date(2026, 8, 4)
    assert result.until == date(2026, 8, 10)
    assert not result.fixed_bounds


def test_explicit_start_and_end_are_marked_as_fixed_bounds() -> None:
    result = resolve_date_range(
        "timeline",
        days=None,
        since="2026-08-01",
        until="2026-08-10",
        timezone=None,
        today=date(2026, 9, 12),
    )
    assert result.fixed_bounds


@pytest.mark.parametrize(
    ("days", "since", "until"),
    [
        (0, None, None),
        (7, "2026-09-01", None),
        (None, "2026-09-10", "2026-09-01"),
        (None, None, "2026-09-13"),
    ],
)
def test_invalid_ranges_fail(days: int | None, since: str | None, until: str | None) -> None:
    with pytest.raises(UsageError):
        resolve_date_range(
            "timeline",
            days=days,
            since=since,
            until=until,
            timezone=None,
            today=date(2026, 9, 12),
        )


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
        "ccusage-viz monitor --window 1h --interval 15 --by model --agent claude "
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
        "ccusage-viz timeline --since 2026-09-01 --until 2026-09-14 --timezone UTC "
        "--by model --top 3 --show-other --no-summary --agent claude --model 'public model' "
        "--project demo-project --watch 5 --theme nord --style stem --ascii"
    )
    assert "/private" not in command
    assert "--ccusage-bin" not in command
    assert "--timeout" not in command

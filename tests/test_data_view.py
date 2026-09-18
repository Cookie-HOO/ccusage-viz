from datetime import date, datetime
from json import loads

from ccusage_viz.core.time import DateRange
from ccusage_viz.data_view import (
    body_view_copy_kind,
    next_body_view,
    next_dashboard_body_view,
    render_monitor_data,
    render_snapshot_data,
)
from ccusage_viz.domain import Agent, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor import ObservedBucket
from ccusage_viz.options import (
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.terminal import Terminal
from ccusage_viz.watch import UsageSnapshot


def _options() -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 31), None),
            by="agent",
            top=1,
            granularity="month",
        ),
    )


def test_body_view_cycle_and_copy_permissions() -> None:
    view = "chart"
    observed = [view]
    for _ in range(5):
        view = next_body_view(view)
        observed.append(view)

    assert observed == ["chart", "command", "full-command", "data-table", "data-json", "chart"]
    assert body_view_copy_kind("chart") is None
    assert body_view_copy_kind("command") == "command"
    assert body_view_copy_kind("full-command") == "full-command"
    assert body_view_copy_kind("data-table") == "data-table"
    assert body_view_copy_kind("data-json") == "data-json"


def test_dashboard_body_view_cycle_has_no_data_views() -> None:
    view = "chart"
    observed = [view]
    for _ in range(2):
        view = next_dashboard_body_view(view)
        observed.append(view)

    assert observed == ["chart", "full-command", "chart"]


def test_snapshot_data_serializes_aggregated_chart_rows() -> None:
    snapshot = UsageSnapshot(
        records=(
            UsageRecord(
                day=date(2026, 1, 1),
                agent=Agent.CLAUDE,
                usage=TokenUsage.from_parts(
                    total=100, input=30, output=40, cache_read=20, cache_creation=10
                ),
                source=SourceKind.UNIFIED_DAILY,
            ),
            UsageRecord(
                day=date(2026, 1, 2),
                agent=Agent.CODEX,
                usage=TokenUsage.from_parts(
                    total=50, input=20, output=30, cache_read=0, cache_creation=0
                ),
                source=SourceKind.UNIFIED_DAILY,
            ),
        ),
        notices=(),
        elapsed=0,
    )
    terminal = Terminal(120, 40, False, False)
    translator = load_translator("en")

    table = render_snapshot_data(_options(), snapshot, translator, terminal)
    payload = loads(
        render_snapshot_data(_options(), snapshot, translator, terminal, view="data-json")
    )

    assert table.splitlines()[0].startswith("| period | series | is_other | total |")
    assert table.splitlines()[1].startswith("| --- |")
    assert len(payload["rows"]) == 2
    assert {row["series"] for row in payload["rows"]} == {"claude", "Other"}
    assert {row["period"] for row in payload["rows"]} == {"2026-01-01"}
    assert all("agent" not in row for row in payload["rows"])


def test_data_display_clips_but_complete_copy_payload_does_not() -> None:
    snapshot = UsageSnapshot(
        records=tuple(
            UsageRecord(
                day=date(2026, 1, day),
                agent=Agent.CLAUDE,
                usage=TokenUsage.from_parts(
                    total=day, input=day, output=0, cache_read=0, cache_creation=0
                ),
                source=SourceKind.UNIFIED_DAILY,
            )
            for day in range(1, 8)
        ),
        notices=(),
        elapsed=0,
    )
    translator = load_translator("en")
    terminal = Terminal(120, 6, False, False)

    displayed = render_snapshot_data(_options(), snapshot, translator, terminal)
    copied = render_snapshot_data(_options(), snapshot, translator, terminal, complete=True)

    assert displayed.endswith("…")
    assert len(copied.splitlines()) > len(displayed.splitlines())


def test_monitor_data_markdown_and_json_share_bucket_values() -> None:
    buckets = (ObservedBucket(0, 1, datetime(2026, 1, 1, 12, 0), {"Total": 42.5, "Other": 3.0}),)
    terminal = Terminal(120, 40, False, False)
    translator = load_translator("en")

    table = render_monitor_data(buckets, by=None, translator=translator, terminal=terminal)
    payload = loads(
        render_monitor_data(
            buckets, by=None, translator=translator, terminal=terminal, view="data-json"
        )
    )

    assert table.startswith("| ended_at | series | value | unit |")
    assert payload["rows"] == [
        {"ended_at": "2026-01-01T12:00:00", "series": "Other", "value": 3.0, "unit": "tpm"},
        {"ended_at": "2026-01-01T12:00:00", "series": "Total", "value": 42.5, "unit": "tpm"},
    ]

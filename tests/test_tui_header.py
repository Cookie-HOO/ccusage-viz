from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.custom_models import (
    CustomComparison,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    LocalizedText,
)
from ccusage_viz.custom_protocol import CustomSummaryResponse
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.historical_component import UsageSnapshot
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    CustomCommandSource,
)
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui import (
    _dashboard_title_line,
    _header_lines,
    _header_options,
    _header_refresh_interval,
    _new_header,
    _next_header_summary,
    _reconcile_custom_dashboard_summaries,
    _replace_header_interval,
    _set_header_theme,
    _text_view_footer,
)


def test_tui_text_footer_is_minimal_and_only_advertises_overflow() -> None:
    translator = load_translator("en")

    compact = _text_view_footer("data-table", translator, 120, line_count=2, visible_rows=2)[0]
    overflowing = _text_view_footer("data-table", translator, 120, line_count=3, visible_rows=2)[0]

    assert compact == "y copy · v/V switch view"
    assert "↑/↓ scroll · h go to top · e go to end" not in compact
    assert overflowing == "↑/↓ scroll · Home top · e end · y copy · v/V switch view"
    assert "Quick" not in overflowing
    assert "replace" not in overflowing
    assert "next pane" not in overflowing


def test_dashboard_title_places_version_left_and_freshness_right() -> None:
    line = _dashboard_title_line("Dashboard", "updated 12:34:56", 50, color=False)
    assert display_width(line) == 50
    assert line.startswith("v0.2.2")
    assert line.endswith("updated 12:34:56")
    assert line.index("Dashboard") == (50 - len("Dashboard")) // 2

    narrow = _dashboard_title_line("仪表盘", "更新于 12:34:56", 18, color=False)
    assert display_width(narrow) == 18
    assert narrow.startswith("v0.2.2")


def test_tui_is_not_a_dashboard_compatibility_alias() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        parser.parse_args(["tui"])


def test_dashboard_header_uses_host_summary_and_tracks_global_theme() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--header-summary", "quarter", "--theme", "nord"]),
        explicit=frozenset(("header_summary", "color_scheme")),
    )

    runtime = build_query_runtime()
    header = _new_header(options, runtime)
    assert header.runtime is runtime
    assert isinstance(header.scheduler, FixedIntervalScheduler)
    assert isinstance(header.lifecycle, LifecycleOperation)
    assert header.scheduler.interval == options.host.header_interval
    assert header.lifecycle.coordinator.owner_id == "dashboard:header"
    assert header.summary_period == "quarter"
    assert header.options.chart.presentation.theme == "nord"

    _set_header_theme(header, "dracula")
    assert header.options.chart.presentation.theme == "dracula"


def test_tui_header_query_is_unfiltered_and_independent() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo", "--header-style", "panel"]))
    header = _header_options(options)
    assert header.chart.kind == "timeline"
    assert (
        header.chart.filters.agents
        == header.chart.filters.models
        == header.chart.filters.projects
        == ()
    )
    assert header.chart.by is None
    assert header.chart.top is None
    assert header.chart.date_range.days == 8


def test_header_summary_cycle_includes_none_and_wraps() -> None:
    observed = []
    period = "day"
    for _ in range(5):
        period = _next_header_summary(period)
        observed.append(period)

    assert observed == ["week", "month", "quarter", "year", "none"]


def test_header_refresh_uses_missing_coverage_then_current_day() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--header-summary", "month"]),
        explicit=frozenset(("header_summary",)),
    )
    header = _new_header(options, build_query_runtime())
    today = date(2026, 3, 15)

    cold = _header_refresh_interval(header, today=today)
    assert cold == DateInterval(date(2025, 3, 1), today)

    header.coverage = DateCoverage((cold,))
    header.records = (UsageRecord(today, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)
    assert _header_refresh_interval(header, aggressive=True, today=today) == cold

    header.records = ()
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)

    header.summary_period = "none"
    assert _header_refresh_interval(header, today=today) is None


def test_header_date_rollover_requests_new_current_day() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "day"]))
    header = _new_header(options, build_query_runtime())
    previous = date(2026, 3, 15)
    header.coverage = DateCoverage((DateInterval(previous.replace(day=8), previous),))
    header.records = (UsageRecord(previous, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)

    assert _header_refresh_interval(header, today=date(2026, 3, 16)) == DateInterval(
        date(2026, 3, 16), date(2026, 3, 16)
    )



def custom_summary_response(
    *,
    display: str = "68 pages",
    sequential: CustomComparison | None = None,
    year_over_year: CustomComparison | None = None,
) -> CustomSummaryResponse:
    return CustomSummaryResponse(
        CustomSummary(
            CustomSummaryMetric(
                "pages",
                LocalizedText("Pages read", "阅读页数"),
                CustomSummaryCurrent(Decimal("68"), LocalizedText(display, "68 页")),
                sequential or CustomComparison("ready", Decimal("56")),
                year_over_year or CustomComparison("unavailable"),
            )
        )
    )


def test_custom_dashboard_summary_reconfiguration_invalidates_replaced_source() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    header = _new_header(options, build_query_runtime())
    initial = CustomCommandSource("reading", ("reader", "ccuv"))
    replacement = CustomCommandSource("reading", ("reader-next", "ccuv"))
    summary = tui_module.CustomDashboardSummary(
        initial,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard:header:custom:reading"),
        response=custom_summary_response(),
        accepted_at=datetime(2026, 9, 30, tzinfo=UTC),
        accepted_period="day",
        accepted_as_of_date=date(2026, 9, 30),
    )
    header.custom_summaries[initial.dataset_id] = summary

    changed = _reconcile_custom_dashboard_summaries(
        header, (tui_module.CustomDashboardSource(replacement),), now=1
    )

    assert changed == (summary,)
    assert header.custom_summaries == {"reading": summary}
    assert summary.source == replacement
    assert summary.response is None
    assert summary.accepted_at is None
    assert summary.accepted_period is None
    assert summary.accepted_as_of_date is None
    assert summary.generation == 1


def test_header_renders_custom_metrics_without_token_summary() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    header = _new_header(options, build_query_runtime())
    source = CustomCommandSource("reading", ("reader", "ccuv"))
    summary = tui_module.CustomDashboardSummary(
        source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard:header:custom:reading"),
        response=custom_summary_response(),
    )
    header.custom_summaries[source.dataset_id] = summary

    lines = _header_lines(header, "banner", load_translator("en"), Terminal(80, 4, False, True))

    assert len(lines) == 2
    assert "Selected-range Pages read 68 pages" in lines[1]
    assert "token" not in lines[1].lower()


def test_header_keeps_summary_items_on_separate_rows() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    header = _new_header(options, build_query_runtime())
    first = CustomCommandSource("reading", ("reader", "ccuv"))
    second = CustomCommandSource("builds", ("builder", "ccuv"))
    for source in (first, second):
        header.custom_summaries[source.dataset_id] = tui_module.CustomDashboardSummary(
            source,
            FixedIntervalScheduler(60, now=0),
            LifecycleOperation(f"dashboard:header:custom:{source.dataset_id}"),
            response=custom_summary_response(),
        )

    lines = _header_lines(header, "compact", load_translator("en"), Terminal(160, 8, False, True))

    assert "Dashboard" in lines[0]
    summary_lines = [line for line in lines[1:] if "Pages read" in line]
    assert len(summary_lines) == 2
    assert all(line.count("Pages read") == 1 for line in summary_lines)


def test_header_renders_custom_metrics_against_their_accepted_scope() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    header = _new_header(options, build_query_runtime())
    header.summary_period = "month"
    source = CustomCommandSource("reading", ("reader", "ccuv"))
    header.custom_summaries[source.dataset_id] = tui_module.CustomDashboardSummary(
        source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard:header:custom:reading"),
        response=custom_summary_response(year_over_year=CustomComparison("ready", Decimal("34"))),
        accepted_period="quarter",
        accepted_as_of_date=date(2026, 10, 1),
    )

    lines = _header_lines(header, "banner", load_translator("en"), Terminal(120, 4, False, True))

    assert "vs prior quarter-to-date" in lines[1]
    assert "vs same period last year" in lines[1]
    assert "vs prior month-to-date" not in lines[1]


def test_header_none_keeps_title_without_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--header-summary", "none"]),
        explicit=frozenset(("header_summary",)),
    )
    header = _new_header(options, build_query_runtime())

    compact = _header_lines(header, "compact", load_translator("en"), Terminal(60, 4, False, True))
    banner = _header_lines(header, "banner", load_translator("en"), Terminal(60, 4, False, True))

    assert len(compact) == 1
    assert "Dashboard" in compact[0]
    assert "?" not in compact[0]
    assert len(banner) == 1


def test_header_cold_period_keeps_structure_with_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "quarter"]))
    header = _new_header(options, build_query_runtime())

    lines = _header_lines(header, "banner", load_translator("en"), Terminal(60, 4, False, True))

    assert len(lines) == 2
    assert "Dashboard" in lines[0]
    assert "Loading…" in lines[1]
    assert "?" not in lines[1]


def test_header_successful_interval_replaces_cached_rows_authoritatively() -> None:
    old = UsageRecord(date(2026, 1, 1), "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY)
    unaffected = UsageRecord(
        date(2025, 12, 31), "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY
    )
    fresh = UsageRecord(
        date(2026, 1, 1),
        "claude",
        TokenUsage(10, 10, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    snapshot = UsageSnapshot(
        (fresh,),
        (),
        0.1,
        coverage=DateCoverage((DateInterval(date(2026, 1, 1), date(2026, 1, 2)),)),
    )

    replaced = _replace_header_interval((unaffected, old), snapshot)

    assert replaced == (unaffected, fresh)


def test_header_successful_empty_interval_removes_stale_covered_rows() -> None:
    stale = UsageRecord(
        date(2026, 1, 1),
        "claude",
        TokenUsage(10, 10, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    snapshot = UsageSnapshot(
        (),
        (),
        0.1,
        coverage=DateCoverage((DateInterval(date(2026, 1, 1), date(2026, 1, 1)),)),
    )

    assert _replace_header_interval((stale,), snapshot) == ()

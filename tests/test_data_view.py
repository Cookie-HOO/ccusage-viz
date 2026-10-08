from datetime import UTC, date, datetime
from decimal import Decimal
from json import loads

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.chart_models import (
    DistributionCoverage,
    TimeOfDayBucket,
    TimeOfDayDistributionModel,
    TimeOfDaySeries,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.data_view import (
    body_view_copy_kind,
    custom_data_payload,
    cycle_body_view,
    cycle_dashboard_body_view,
    next_body_view,
    next_dashboard_body_view,
    render_current_monitor_data,
    render_custom_data,
    render_monitor_data,
    render_monitor_distribution_data,
    render_snapshot_data,
)
from ccusage_viz.domain import (
    Agent,
    SourceKind,
    TokenUsage,
    UsageRecord,
)
from ccusage_viz.historical_component import UsageSnapshot
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor_component import MonitorCompletion, MonitorComponent
from ccusage_viz.options import (
    ChartPresentation,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.processing.monitor import ObservedBucket
from ccusage_viz.project_identity import ExactProjectDisplayKey, fixed_project_ref, make_project_ref
from ccusage_viz.terminal import Terminal


def _options() -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 31)),
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
    assert cycle_body_view("chart", step=-1) == "data-json"
    assert cycle_body_view("command", step=-1) == "chart"


def test_dashboard_body_view_cycle_has_no_data_views() -> None:
    view = "chart"
    observed = [view]
    for _ in range(2):
        view = next_dashboard_body_view(view)
        observed.append(view)

    assert observed == ["chart", "full-command", "chart"]
    assert cycle_dashboard_body_view("chart", step=-1) == "full-command"


def test_project_ranking_data_expands_fixed_group_sources() -> None:
    options = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        RankingConfig("ranking", DateRange(date(2026, 10, 7), date(2026, 10, 7)), by="project"),
    )
    snapshot = UsageSnapshot(
        (
            UsageRecord(
                date(2026, 10, 7),
                "codex",
                TokenUsage(30, 0, 0, 0, 0),
                SourceKind.CODEX_SESSIONS,
                fixed_project_ref("codex", "unassigned"),
                attribution="unassigned",
                session_id="rollout-missing",
            ),
            UsageRecord(
                date(2026, 10, 7),
                "dsh",
                TokenUsage(20, 0, 0, 0, 0),
                SourceKind.UNIFIED_DAILY,
                fixed_project_ref("dsh", "unverified"),
                attribution="unverified",
                source_project="relative/project",
            ),
        ),
        (),
        0.1,
    )
    payload = loads(
        render_snapshot_data(
            options,
            snapshot,
            load_translator("en"),
            Terminal(120, 40, False, False),
            view="data-json",
        )
    )

    assert payload["rows"] == [
        {
            "rank": 1,
            "display_project": "Unassigned",
            "project": "Unassigned",
            "agent": "codex",
            "attribution": "unassigned",
            "period": "2026-10-07",
            "source_project": None,
            "session_id": "rollout-missing",
            "merge_group": None,
            "is_other": False,
            "total": 30,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
        {
            "rank": 2,
            "display_project": "Unverified",
            "project": "Unverified",
            "agent": "dsh",
            "attribution": "unverified",
            "period": "2026-10-07",
            "source_project": "relative/project",
            "session_id": None,
            "merge_group": None,
            "is_other": False,
            "total": 20,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
    ]


def test_custom_data_serializes_visible_decimal_projection() -> None:
    projection = CustomChartProjection(
        "timeline",
        (date(2026, 9, 1), date(2026, 9, 2)),
        (
            CustomProjectedSeries(
                "book-a",
                LocalizedText("Book A", "图书 A"),
                (Decimal("1.20"), Decimal("0.05")),
            ),
            CustomProjectedSeries(
                "Other",
                LocalizedText("Other", "其他"),
                (Decimal("2.75"), Decimal("0")),
                is_other=True,
            ),
        ),
        CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        "day",
    )
    translator = load_translator("en")

    table = render_custom_data(projection, language="en", translator=translator)
    payload = loads(
        render_custom_data(projection, language="zh", translator=translator, view="data-json")
    )

    assert table.splitlines()[0] == "| period | series_id | series | is_other | value |"
    assert payload == {
        "kind": "timeline",
        "range": {"start_date": "2026-09-01", "end_date": "2026-09-02"},
        "granularity": "day",
        "unit": {"id": "page", "label": "页", "placement": "suffix", "decimal_places": 2},
        "rows": [
            {
                "period": "2026-09-01",
                "series_id": "book-a",
                "series": "图书 A",
                "is_other": False,
                "value": "1.20",
            },
            {
                "period": "2026-09-02",
                "series_id": "book-a",
                "series": "图书 A",
                "is_other": False,
                "value": "0.05",
            },
            {
                "period": "2026-09-01",
                "series_id": "Other",
                "series": "其他",
                "is_other": True,
                "value": "2.75",
            },
            {
                "period": "2026-09-02",
                "series_id": "Other",
                "series": "其他",
                "is_other": True,
                "value": "0",
            },
        ],
    }
    assert custom_data_payload(projection, language="en")["rows"][0]["value"] == "1.20"


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


def test_exact_project_data_rows_have_an_explicit_agent_field() -> None:
    options = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        RankingConfig(
            "ranking",
            DateRange(date(2026, 1, 1), date(2026, 1, 1)),
            project_aggregation="exact",
        ),
    )
    snapshot = UsageSnapshot(
        records=(
            UsageRecord(
                date(2026, 1, 1),
                Agent.CLAUDE,
                TokenUsage.from_parts(
                    total=20, input=10, output=10, cache_read=0, cache_creation=0
                ),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                make_project_ref("claude", "-home-me-projects-app"),
            ),
            UsageRecord(
                date(2026, 1, 1),
                Agent.CODEX,
                TokenUsage.from_parts(total=10, input=5, output=5, cache_read=0, cache_creation=0),
                SourceKind.CODEX_SESSIONS,
                make_project_ref("codex", "/workspace/app"),
            ),
        ),
        notices=(),
        elapsed=0,
    )
    terminal = Terminal(120, 40, False, False)
    translator = load_translator("en")

    table = render_snapshot_data(options, snapshot, translator, terminal)
    payload = loads(render_snapshot_data(options, snapshot, translator, terminal, view="data-json"))

    assert table.splitlines()[0].startswith(
        "| rank | display_project | project | agent | merge_group | is_other | total |"
    )
    assert [
        (row["display_project"], row["project"], row["agent"], row["merge_group"])
        for row in payload["rows"]
    ] == [
        ("claude · -home-me-projects-app", "-home-me-projects-app", "claude", None),
        ("codex · app", "app", "codex", None),
    ]


def test_merged_project_data_rows_expose_stable_merge_group_only() -> None:
    ranking_options = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        RankingConfig("ranking", DateRange(date(2026, 1, 1), date(2026, 1, 2))),
    )
    timeline_options = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 2)),
            by="project",
        ),
    )
    snapshot = UsageSnapshot(
        records=(
            UsageRecord(
                date(2026, 1, 1),
                Agent.CLAUDE,
                TokenUsage.from_parts(
                    total=20, input=10, output=10, cache_read=0, cache_creation=0
                ),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                make_project_ref("claude", "-home-me-projects-app"),
            ),
            UsageRecord(
                date(2026, 1, 2),
                Agent.CODEX,
                TokenUsage.from_parts(total=10, input=5, output=5, cache_read=0, cache_creation=0),
                SourceKind.CODEX_SESSIONS,
                make_project_ref("codex", "/workspace/app"),
            ),
        ),
        notices=(),
        elapsed=0,
    )
    terminal = Terminal(120, 40, False, False)
    translator = load_translator("en")

    ranking = loads(
        render_snapshot_data(ranking_options, snapshot, translator, terminal, view="data-json")
    )
    timeline = loads(
        render_snapshot_data(timeline_options, snapshot, translator, terminal, view="data-json")
    )
    table = render_snapshot_data(ranking_options, snapshot, translator, terminal)

    assert ranking["rows"] == [
        {
            "rank": 1,
            "display_project": "app",
            "project": "-home-me-projects-app",
            "agent": "claude",
            "merge_group": 0,
            "is_other": False,
            "total": 20,
            "input": 10,
            "output": 10,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
        {
            "rank": 1,
            "display_project": "app",
            "project": "app",
            "agent": "codex",
            "merge_group": 0,
            "is_other": False,
            "total": 10,
            "input": 5,
            "output": 5,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
    ]
    assert {row["display_project"] for row in timeline["rows"]} == {"app"}
    assert {row["merge_group"] for row in timeline["rows"]} == {0}
    assert table.splitlines()[0].startswith(
        "| rank | display_project | project | agent | merge_group | is_other | total |"
    )


def test_exact_project_rows_keep_agent_column_for_other_rows() -> None:
    options = StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        RankingConfig(
            "ranking",
            DateRange(date(2026, 1, 1), date(2026, 1, 1)),
            top=1,
            project_aggregation="exact",
        ),
    )
    snapshot = UsageSnapshot(
        records=(
            UsageRecord(
                date(2026, 1, 1),
                Agent.CLAUDE,
                TokenUsage.from_parts(
                    total=20, input=10, output=10, cache_read=0, cache_creation=0
                ),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                make_project_ref("claude", "-home-me-projects-app"),
            ),
            UsageRecord(
                date(2026, 1, 1),
                Agent.CODEX,
                TokenUsage.from_parts(total=10, input=5, output=5, cache_read=0, cache_creation=0),
                SourceKind.CODEX_SESSIONS,
                make_project_ref("codex", "/workspace/api"),
            ),
        ),
        notices=(),
        elapsed=0,
    )
    terminal = Terminal(120, 40, False, False)
    translator = load_translator("en")

    table = render_snapshot_data(options, snapshot, translator, terminal)
    payload = loads(render_snapshot_data(options, snapshot, translator, terminal, view="data-json"))

    assert table.splitlines()[0].startswith(
        "| rank | display_project | project | agent | merge_group | is_other | total |"
    )
    assert all(line.count("|") == table.splitlines()[0].count("|") for line in table.splitlines())
    assert payload["rows"] == [
        {
            "rank": 1,
            "display_project": "claude · -home-me-projects-app",
            "project": "-home-me-projects-app",
            "agent": "claude",
            "merge_group": None,
            "is_other": False,
            "total": 20,
            "input": 10,
            "output": 10,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
        {
            "rank": 2,
            "display_project": "Other",
            "project": "Other",
            "agent": None,
            "merge_group": None,
            "is_other": True,
            "total": 10,
            "input": 5,
            "output": 5,
            "cache_read": 0,
            "cache_creation": 0,
            "other": 0,
        },
    ]


def test_data_display_keeps_the_complete_payload() -> None:
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

    assert not displayed.endswith("…")
    assert displayed == render_snapshot_data(
        _options(), snapshot, translator, Terminal(120, 100, False, False)
    )


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


def test_monitor_distribution_data_distinguishes_unobserved_and_observed_zero() -> None:
    started = datetime(2026, 1, 1, 9, 0).astimezone()
    model = TimeOfDayDistributionModel(
        (
            TimeOfDayBucket(
                started,
                started.replace(hour=10),
                DistributionCoverage.UNOBSERVED,
            ),
            TimeOfDayBucket(
                started.replace(hour=10),
                started.replace(hour=11),
                DistributionCoverage.FULL,
                {"Total": 0.0},
            ),
        ),
        (TimeOfDaySeries("Total", "Total"),),
        started,
        "today",
        "hour",
    )
    payload = loads(
        render_monitor_distribution_data(
            model,
            translator=load_translator("en"),
            terminal=Terminal(120, 40, False, False),
            view="data-json",
        )
    )

    assert payload["rows"] == [
        {
            "started_at": started.isoformat(),
            "ended_at": started.replace(hour=10).isoformat(),
            "day_window": "today",
            "granularity": "hour",
            "series": "Total",
            "is_other": False,
            "value": None,
            "unit": "tokens",
            "coverage": "unobserved",
        },
        {
            "started_at": started.replace(hour=10).isoformat(),
            "ended_at": started.replace(hour=11).isoformat(),
            "day_window": "today",
            "granularity": "hour",
            "series": "Total",
            "is_other": False,
            "value": 0.0,
            "unit": "tokens",
            "coverage": "full",
        },
    ]


def test_current_cumulative_monitor_data_uses_distribution_projection() -> None:
    chart = MonitorConfig("monitor", 3600, presentation=ChartPresentation(style="cumulative-bars"))
    options = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(interval=5), chart)
    component = MonitorComponent(options, registry=build_chart_registry())
    first = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    second = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)

    def completion(total: int) -> MonitorCompletion:
        return MonitorCompletion(
            0,
            options,
            (
                UsageRecord(
                    first.date(), "claude", TokenUsage(total, 0, 0, 0, 0), SourceKind.UNIFIED_DAILY
                ),
            ),
            0.1,
        )

    assert component.accept(completion(100), now=0, wall=first)
    assert component.accept(completion(160), now=30, wall=second)
    payload = loads(
        render_current_monitor_data(
            component,
            chart,
            translator=load_translator("en"),
            terminal=Terminal(120, 40, False, False),
            now=30,
            wall=second,
            view="data-json",
        )
    )

    assert "coverage" in payload["rows"][0]


def test_monitor_project_data_uses_safe_separated_series_label() -> None:
    buckets = (
        ObservedBucket(
            0,
            1,
            datetime(2026, 1, 1, 12, 0),
            {ExactProjectDisplayKey("claude", "/private/work/app", "app"): 42.5},
        ),
    )
    terminal = Terminal(120, 40, False, False)
    payload = loads(
        render_monitor_data(
            buckets,
            by="project",
            translator=load_translator("en"),
            terminal=terminal,
            view="data-json",
        )
    )

    assert payload["rows"][0]["series"] == "claude · app"
    assert payload["rows"][0]["display_project"] == "claude · app"
    assert payload["rows"][0]["agent"] == "claude"
    assert payload["rows"][0]["merge_group"] is None
    assert "/private" not in payload["rows"][0]["series"]

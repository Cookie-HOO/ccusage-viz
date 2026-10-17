from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.dashboard_events as tui_dashboard_events
import ccusage_viz.tui.datasets.blocking as tui_datasets_blocking
import ccusage_viz.tui.datasets.catalog as tui_datasets_catalog
import ccusage_viz.tui.datasets.chooser as tui_datasets_chooser
import ccusage_viz.tui.datasets.modal as tui_datasets_modal
import ccusage_viz.tui.events as tui_events
import ccusage_viz.tui.help as tui_help
import ccusage_viz.tui.history as tui_history
import ccusage_viz.tui.input as tui_input
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
import ccusage_viz.tui.structure as tui_structure
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomData,
    CustomDataset,
    CustomDimension,
    CustomPoint,
    CustomSeries,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.custom_protocol.requests import V2SummaryRequest
from ccusage_viz.custom_protocol.responses import CustomChartResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.render.surfaces import dashboard_pane_surface
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.custom_rendering import _custom_ranking_clipboard_text
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _local_pane_content, _pane_render
from ccusage_viz.tui_input import KeyEvent

from .custom_helpers import custom_summary_response


def test_custom_ranking_project_copy_appends_the_project_link() -> None:
    assert _custom_ranking_clipboard_text(
        "Project",
        "Read [documentation](https://example.com/docs)",
        "https://example.com/projects/project",
    ) == (
        "Project\nRead documentation https://example.com/docs\nhttps://example.com/projects/project"
    )
    assert _custom_ranking_clipboard_text("Project", None, None) == "Project"


@pytest.mark.parametrize(
    ("density", "visible"),
    (
        ("minimal", False),
        ("compact", False),
        ("normal", False),
        ("full", True),
        ("detailed", True),
    ),
)
def test_custom_ranking_description_visibility_follows_density(density: str, visible: bool) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        group_by="book",
        presentation=replace(ChartPresentation(), density=density),
    )
    text = LocalizedText("Reading", "阅读")
    unit = CustomUnit("page", text, "suffix", 0)
    component = CustomHistoricalComponent(chart)
    response = CustomChartResponse(
        CustomDataset(text, text, unit),
        CustomCapabilities(
            (CustomDimension("book", text),),
            (),
            {
                "ranking": CustomChartCapability(
                    ("day",), ("book",), (), descriptions_default="expanded"
                )
            },
        ),
        CustomData(
            (
                CustomSeries(
                    "book-1",
                    text,
                    (CustomPoint(date(2026, 9, 1), Decimal("1")),),
                    LocalizedText("Release validation", "发布验证"),
                ),
            )
        ),
    )
    assert component.accept_response(response)

    rendered = tui_custom_rendering._render_custom_projection(
        component.model,
        chart,
        load_translator("en"),
        Terminal(80, 24, color=False, ascii=True),
        accepted_at=None,
        interval=None,
        pending=False,
        surface=dashboard_pane_surface("ranking"),
    )
    assert ("Release validation" in rendered.chart) is visible
    assert "D" not in {
        action.key
        for action in tui_custom_rendering._custom_standalone_actions(
            component, load_translator("en")
        )
    }


def test_custom_ranking_pane_restores_preset_item_spacing() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=ChartPresentation(style="list"),
    )

    pane = _new_pane(
        dashboard,
        tui_models.CustomChartPaneConfig(chart, ranking_item_spacing="dashed"),
        "dashboard:pane:spacing",
        build_query_runtime(),
    )

    assert isinstance(pane, tui_models.TuiCustomPane)
    assert pane.ranking_item_spacing == "dashed"


def test_custom_dashboard_refresh_retains_accepted_ranking_with_visible_audit() -> None:
    from tests.custom_component.helpers import response

    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        group_by="book",
        presentation=replace(ChartPresentation(), density="detailed"),
    )
    component = CustomHistoricalComponent(chart)
    assert component.accept_response(response((("accepted-series-label", "10"),)))
    component.configure(
        replace(component.candidate, date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30))),
        data_affecting=True,
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard-refresh"),
        SimpleNamespace(),
        probe_complete=True,
    )

    # A periodic Router-style refresh may queue behind an active comparison or
    # configuration request. Its queued intent, not the older active trigger,
    # controls whether the accepted ranking remains visible.
    pane.lifecycle.request(
        LifecycleTrigger.CONFIGURATION,
        generation=component.generation,
        now=0,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    pane.lifecycle.request(
        LifecycleTrigger.PERIODIC,
        generation=component.generation,
        now=1,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    rendered = _pane_render(pane, load_translator("en"), Terminal(100, 24, False, True))

    assert "accepted-series-label" in rendered.chart
    assert "2026-09-01–2026-09-02" in rendered.chart
    assert "2026-09-17–2026-09-30" not in rendered.chart
    assert "??" not in rendered.chart
    assert "refreshing" in rendered.chart.lower()


def test_dashboard_subday_ranking_suppresses_summary_and_date_restore_reuses_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 10, 15), date(2026, 10, 15), relative_until=True, period="1d"),
        metric_id="requests",
        metric_periods=("10m", "1d"),
    )
    component = CustomHistoricalComponent(chart)
    from tests.custom_component.helpers import response

    assert component.accept_response(response(point_date=date(2026, 10, 15)))
    component.set_capability(CustomChartCapability((), (None,), (), periods=("10m", "1d")))
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(3600, now=tui_rendering.time.monotonic()),
        LifecycleOperation("subday-summary"),
        options.process,
        probe_complete=True,
    )
    pane.summary = tui_models.CustomDashboardSummary(
        chart.source,
        FixedIntervalScheduler(3600, now=tui_rendering.time.monotonic()),
        LifecycleOperation("subday-summary:summary"),
        response=custom_summary_response(display="STALE SUMMARY"),
        accepted_period="day",
        accepted_as_of_date=date(2026, 10, 15),
    )
    submitted: list[object] = []
    frames: list[str] = []

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, intent: object) -> FailedHandle:
            submitted.append(intent)
            return FailedHandle()

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append("\n".join(frame.rows))  # type: ignore[attr-defined]

        def finish(self) -> None:
            pass

    # Open adjustments, move 1d -> 10m, manually refresh there, restore 1d,
    # then manually refresh again so the normal date-summary route is exercised.
    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("P"),
            KeyEvent("r"),
            KeyEvent("p"),
            KeyEvent("r"),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_session, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_structure, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_history, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_input, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_catalog, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_chooser, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    summary_intents = [
        intent for intent in submitted if isinstance(intent.payload, V2SummaryRequest)
    ]
    timestamp_chart_intents = [
        intent for intent in submitted if getattr(intent.payload, "start_at", None) is not None
    ]

    assert timestamp_chart_intents
    assert len(summary_intents) == 2  # startup and restored date-range manual refresh
    subday_frames = [frame for frame in frames if "T" in frame and "[" in frame]
    assert subday_frames
    assert all("STALE SUMMARY" not in frame for frame in subday_frames)


def test_grouped_custom_ranking_dispatch_uses_grouped_viewport_and_clears_flat_state() -> None:
    from tests.ranking_scroll.helpers import grouped_projection

    model = grouped_projection()
    flat = tui_models.RankingViewport(offset=4)
    grouped = tui_models.GroupedRankingViewport()
    rendered = tui_custom_rendering._render_custom_projection(
        model,
        replace(model.config, metric_titles=("Requests", "请求")),
        load_translator("en"),
        Terminal(80, 10, color=False, ascii=True),
        accepted_at=None,
        interval=None,
        pending=False,
        surface=dashboard_pane_surface("ranking"),
        ranking_viewport=flat,
        grouped_ranking_viewport=grouped,
    )

    assert grouped.active and grouped.rows and grouped.hits
    assert not flat.active and flat.offset == 0
    assert "Coding Model" in rendered.chart


def test_custom_ranking_viewport_preserves_renderer_column_padding() -> None:
    chart = "    Centered ranking\n 1     API       ···● 10  60%\n 2     Longer API ·●··  5  40%"

    content, offset, line_count, visible_rows = _local_pane_content(
        chart,
        (),
        width=40,
        height=3,
        scrollable=True,
        preserve_layout=True,
        return_metadata=True,
    )

    assert content.splitlines() == chart.splitlines()
    assert (offset, line_count, visible_rows) == (0, 3, 3)


def test_custom_ranking_viewport_keeps_heading_search_and_columns_fixed() -> None:
    chart = "Ranking\nShowing 3 item(s)\nRank Project Current\n 1 A 10\n 2 B 8\n 3 C 5"
    fixed_rows = tui_custom_rendering._ranking_fixed_rows(chart)

    content, offset, line_count, visible_rows = _local_pane_content(
        chart,
        (),
        width=40,
        height=5,
        offset=1,
        scrollable=True,
        preserve_layout=True,
        fixed_rows=fixed_rows,
        return_metadata=True,
    )

    assert content.splitlines() == [
        "Ranking",
        "Showing 3 item(s)",
        "Rank Project Current",
        " 2 B 8",
        " 3 C 5",
    ]
    assert (offset, line_count, visible_rows) == (1, 3, 2)


def test_v2_ranking_source_limit_is_a_pane_local_notice() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("weread", ("weread",)),
            DateRange(date(2026, 1, 1), date(2026, 10, 8)),
            metric_id="reading_time",
            group_by="book",
            top=11,
        )
    )
    component.set_capability(CustomChartCapability(("day",), ("book",), (), max_items=10))
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-ranking-limit"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    assert tui_custom_adjustments._custom_top_limit_notice(pane, load_translator("en")) == (
        "This Dataset can provide at most 10 ranking items.",
    )

    pane.body_view = "command"
    assert tui_custom_adjustments._custom_top_limit_notice(pane, load_translator("en")) == ()

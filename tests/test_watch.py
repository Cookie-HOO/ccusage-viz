from __future__ import annotations

import os
import sys
from concurrent.futures import Future
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from typing import cast

import pytest

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.charts.builtins import RANKING_DEFINITION
from ccusage_viz.charts.definition import HistoricalRenderer
from ccusage_viz.charts.registry import ChartRegistry
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalPurpose,
    HistoricalSubmission,
    UsageSnapshot,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, QueryTrigger
from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.terminal import FramePainter, Terminal
from ccusage_viz.terminal_ui import controls_line, notice_lines
from ccusage_viz.watch import (
    RefreshResult,
    RuntimeAdjustmentResult,
    _paint,
    _require_complete_coverage,
    _watch_status,
    render_component,
    run_runtime_adjustment,
    run_watch,
)


def options(*, command: str = "ranking", demo: str | None = "small") -> StandaloneLaunch:
    date_range = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    presentation = ChartPresentation(theme="no-color")
    chart = (
        TimelineConfig("timeline", date_range, presentation=presentation, top=3, other="hide")
        if command == "timeline"
        else CalendarConfig("calendar", date_range, presentation=presentation)
        if command == "calendar"
        else StackConfig("stack", date_range, presentation=replace(presentation, style="stacked"))
        if command == "stack"
        else RankingConfig(
            "ranking",
            date_range,
            presentation=replace(presentation, style="bar"),
            by="project",
            top=10,
            other="hide",
        )
        if command == "ranking"
        else MonitorConfig("monitor", 3600, presentation=replace(presentation, style="bars"))
    )
    return StandaloneLaunch(
        ProcessConfig(ccusage_bin="/not/invoked", query_timeout=2),
        StandaloneHostConfig(ascii=True, demo_size=demo, watch=False),
        chart,
    )


def component(
    selected: StandaloneLaunch | None = None,
    snapshot: UsageSnapshot | None = None,
    *,
    registry: ChartRegistry | None = None,
) -> HistoricalChartComponent:
    selected = selected or options()
    chart = HistoricalChartComponent(
        selected,
        owner_id="test:watch",
        runtime=None,
        registry=registry or build_chart_registry(),
    )
    chart.seed(selected, snapshot or UsageSnapshot((), (), 0.0))
    return chart


def test_one_shot_paints_one_complete_interactive_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []

    class Screen:
        def __init__(self, stream: object) -> None:
            events.append(("init", stream))

        def paint(self, *args: object, **kwargs: object) -> None:
            events.append(("paint", *args, kwargs))

        def finish(self) -> None:
            events.append(("finish",))

    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, False, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.render_component",
        lambda *args, **kwargs: RefreshResult("complete chart", ("notice",), 0.25),
    )
    monkeypatch.setattr("ccusage_viz.watch.FramePainter", Screen)

    assert run_watch(options(), load_translator("en")) == 0
    assert [event[0] for event in events] == ["init", "paint", "finish"]
    assert events[1][1].rows[0] == "DEMO DATA · small · ccusage not invoked"
    assert "complete chart" in events[1][1].rows
    assert len(events[1][1].rows) == 30


def test_one_shot_requires_complete_atomic_coverage() -> None:
    selected = options()
    required = DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14))
    future: Future[object] = Future()
    submission = HistoricalSubmission(
        0,
        selected,
        cast(QueryHandle, QueryHandle(future, lambda: None)),
        0.0,
        requested_coverage=required,
    )

    with pytest.raises(QueryError, match="error.incomplete_coverage"):
        _require_complete_coverage(
            submission,
            UsageSnapshot(
                (),
                (),
                0.1,
                coverage=DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 14)),
            ),
        )

    _require_complete_coverage(
        submission,
        UsageSnapshot((), (), 0.1, coverage=required),
    )


def test_historical_pause_cancels_automatic_query_and_manual_refresh_remains_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = replace(options(), host=replace(options().host, watch=True))
    events: list[tuple[object, ...]] = []
    submissions: list[Submission] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Submission:
        handle: Submission

        def __init__(self, generation: int, selected: StandaloneLaunch) -> None:
            self.generation = generation
            self.options = selected
            self.handle = self
            self.cancelled = False

        def done(self) -> bool:
            return self.cancelled

        def cancel(self) -> None:
            self.cancelled = True
            events.append(("submission-cancel", self.generation))

        def result(self) -> object:
            raise RuntimeError("cancelled query must stay hidden")

    class Component:
        def __init__(self, selected: StandaloneLaunch, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.snapshot = None
            self.model = None
            self.generation = 0
            self.accepted_generation = None

        def configure(self, selected: StandaloneLaunch, *, data_affecting: bool) -> None:
            if selected != self.candidate:
                self.candidate = selected
                if data_affecting:
                    self.generation += 1

        def missing_comparison_coverage(self) -> DateCoverage:
            return DateCoverage()

        def submit(self, trigger: object, **_kwargs: object) -> Submission:
            events.append(("submit", trigger, self.generation))
            submission = Submission(self.generation, self.candidate)
            submissions.append(submission)
            return submission

        def fail(
            self,
            error: BaseException,
            *,
            generation: int,
            **_kwargs: object,
        ) -> bool:
            events.append(("fail", str(error), generation))
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            events.append(("paint", frame))

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter((" ", "r", "\x03"))
    runtime = Runtime()
    monkeypatch.setattr("ccusage_viz.watch.build_query_runtime", lambda: runtime)
    monkeypatch.setattr("ccusage_viz.watch.build_chart_registry", lambda: object())
    monkeypatch.setattr("ccusage_viz.watch.HistoricalChartComponent", Component)
    monkeypatch.setattr("ccusage_viz.watch.FramePainter", Screen)
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda _timeout: next(keys))
    monkeypatch.setattr("ccusage_viz.watch.get_terminal_size", lambda: os.terminal_size((100, 30)))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *_args, **_kwargs: Terminal(100, 30, False, True),
    )

    assert run_watch(launch, load_translator("en")) == 0
    assert [(event[1], event[2]) for event in events if event[0] == "submit"] == [
        (QueryTrigger.STARTUP, 0),
        (QueryTrigger.REFRESH, 0),
    ]
    assert len(submissions) == 2
    assert submissions[0].cancelled
    assert submissions[1].cancelled
    assert not any(event[0] == "fail" for event in events)
    assert any(event[0] == "paint" and "paused" in str(event[1]) for event in events)
    assert events[-3:] == [
        ("submission-cancel", 0),
        ("runtime-cancel",),
        ("finish",),
    ]


def test_historical_primary_completion_queues_supplement_without_moving_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = replace(options(command="timeline"), host=replace(options().host, watch=True))
    comparison = DateCoverage((DateInterval(date(2025, 12, 31), date(2025, 12, 31)),))
    events: list[tuple[object, ...]] = []
    baselines: list[tuple[float, float]] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Handle:
        def done(self) -> bool:
            return True

    class Submission:
        def __init__(self, generation: int, purpose: HistoricalPurpose) -> None:
            self.generation = generation
            self.purpose = purpose
            self.handle = Handle()

        def cancel(self) -> None:
            events.append(("submission-cancel", self.purpose))

        def result(self) -> object:
            events.append(("result", self.purpose))
            return object()

    class Component:
        def __init__(self, selected: StandaloneLaunch, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_generation = None
            self.snapshot = None
            self.model = None
            self.generation = 0
            self._missing = DateCoverage()

        def configure(self, selected: StandaloneLaunch, *, data_affecting: bool) -> None:
            self.candidate = selected
            if data_affecting:
                self.generation += 1

        def display_coverage(self) -> DateCoverage:
            chart = cast(TimelineConfig, self.candidate.chart)
            return DateCoverage.from_interval(chart.date_range.since, chart.date_range.until)

        def required_coverage(self) -> DateCoverage:
            return self.display_coverage().merge(comparison)

        def missing_comparison_coverage(self) -> DateCoverage:
            return self._missing

        def submit(
            self,
            trigger: QueryTrigger,
            **kwargs: object,
        ) -> Submission:
            purpose = cast(HistoricalPurpose, kwargs["purpose"])
            events.append(
                (
                    "submit",
                    trigger,
                    purpose,
                    kwargs.get("coverage"),
                    kwargs.get("required_coverage"),
                    self.generation,
                )
            )
            return Submission(self.generation, purpose)

        def accept(self, _completion: object) -> bool:
            if self.snapshot is None:
                self.snapshot = UsageSnapshot((), (), 0.1, coverage=self.display_coverage())
                self.accepted_generation = self.generation
                self._missing = comparison
            else:
                self.snapshot = UsageSnapshot(
                    (),
                    (),
                    0.1,
                    coverage=self.snapshot.coverage.merge(comparison),
                )
                self._missing = DateCoverage()
            return True

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            events.append(("fail",))
            return True

    class Scheduler(FixedIntervalScheduler):
        def __init__(self, interval: float, *, now: float) -> None:
            super().__init__(interval, now=now)
            baselines.append((self.baseline, self.next_opportunity))

        def due(self, *, now: float) -> bool:
            baselines.append((self.baseline, self.next_opportunity))
            return False

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter((None, None, "\x03"))
    runtime = Runtime()
    monkeypatch.setattr("ccusage_viz.watch.build_query_runtime", lambda: runtime)
    monkeypatch.setattr("ccusage_viz.watch.build_chart_registry", lambda: object())
    monkeypatch.setattr("ccusage_viz.watch.HistoricalChartComponent", Component)
    monkeypatch.setattr("ccusage_viz.watch.FixedIntervalScheduler", Scheduler)
    monkeypatch.setattr("ccusage_viz.watch.FramePainter", Screen)
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda _timeout: next(keys))
    monkeypatch.setattr("ccusage_viz.watch.get_terminal_size", lambda: os.terminal_size((100, 30)))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *_args, **_kwargs: Terminal(100, 30, False, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.render_component",
        lambda *_args, **_kwargs: RefreshResult("chart", (), 0.1),
    )

    assert run_watch(launch, load_translator("en")) == 0
    submissions = [event for event in events if event[0] == "submit"]
    assert submissions == [
        ("submit", QueryTrigger.STARTUP, HistoricalPurpose.PRIMARY, None, None, 1),
        (
            "submit",
            QueryTrigger.REFRESH,
            HistoricalPurpose.SUPPLEMENTAL,
            DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 14)),
            None,
            1,
        ),
    ]
    assert len(set(baselines)) == 1
    assert not any(event[0] == "fail" for event in events)


def test_historical_filter_commit_increments_generation_once_and_refreshes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = replace(options(command="timeline"), host=replace(options().host, watch=True))
    events: list[tuple[object, ...]] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Handle:
        def done(self) -> bool:
            return True

    class Submission:
        purpose = HistoricalPurpose.PRIMARY

        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.handle = Handle()

        def cancel(self) -> None:
            pass

        def result(self) -> object:
            return object()

    class Component:
        def __init__(self, selected: StandaloneLaunch, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.accepted_generation = None
            self.snapshot = None
            self.model = None
            self.generation = 0

        def seed(self, selected: StandaloneLaunch, snapshot: UsageSnapshot) -> None:
            self.candidate = selected
            self.accepted_options = selected
            self.snapshot = snapshot

        def configure(self, selected: StandaloneLaunch, *, data_affecting: bool) -> None:
            if selected == self.candidate:
                return
            self.candidate = selected
            if data_affecting:
                self.generation += 1
            events.append(("configure", data_affecting, self.generation))

        def display_coverage(self) -> DateCoverage:
            chart = cast(TimelineConfig, self.candidate.chart)
            return DateCoverage.from_interval(chart.date_range.since, chart.date_range.until)

        def missing_comparison_coverage(self) -> DateCoverage:
            return DateCoverage()

        def submit(self, trigger: QueryTrigger, **_kwargs: object) -> Submission:
            events.append(("submit", trigger, self.generation))
            return Submission(self.generation)

        def accept(self, _completion: object) -> bool:
            self.snapshot = UsageSnapshot((), (), 0.1, coverage=self.display_coverage())
            self.accepted_options = self.candidate
            self.accepted_generation = self.generation
            return True

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            pass

    keys = iter((None, "m", "a", "f", "\x1b", "\x03"))
    monkeypatch.setattr("ccusage_viz.watch.build_query_runtime", Runtime)
    monkeypatch.setattr("ccusage_viz.watch.build_chart_registry", lambda: object())
    monkeypatch.setattr("ccusage_viz.watch.HistoricalChartComponent", Component)
    monkeypatch.setattr("ccusage_viz.watch.FramePainter", Screen)
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda _timeout: next(keys))
    monkeypatch.setattr("ccusage_viz.watch.get_terminal_size", lambda: os.terminal_size((100, 30)))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *_args, **_kwargs: Terminal(100, 30, False, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.render_component",
        lambda *_args, **_kwargs: RefreshResult("chart", (), 0.1),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_filter_editor",
        lambda *_args, **_kwargs: Filters(agents=("Claude Code",)),
    )

    assert run_watch(launch, load_translator("en")) == 0
    assert [event for event in events if event[0] == "configure"][-1:] == [("configure", True, 1)]
    assert [event for event in events if event[0] == "submit"] == [
        ("submit", QueryTrigger.STARTUP, 0),
        ("submit", QueryTrigger.REFRESH, 1),
    ]


def test_watch_paint_places_footer_last_without_refresh_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint(
        "summary\nchart\n",
        "status",
        "r refresh · m adjust · Space pause",
        ("! warning one", "! warning two"),
    )
    assert capsys.readouterr().out == (
        "\x1b[H\x1b[2Jstatus\nsummary\nchart\n"
        "! warning one\n! warning two\nr refresh · m adjust · Space pause"
    )


def test_watch_paint_pads_controls_to_fixed_final_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint("chart", "status", ("adjustment", "controls"), ("warning",), height=6)
    assert capsys.readouterr().out == "\x1b[H\x1b[2Jstatus\nchart\n\nwarning\nadjustment\ncontrols"


def test_watch_paint_keeps_footer_visible_if_body_is_too_tall(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint("one\ntwo\nthree\nfour", "status", "controls", ("warning",), height=5)
    assert capsys.readouterr().out == "\x1b[H\x1b[2Jstatus\none\ntwo\nwarning\ncontrols"


@pytest.mark.parametrize(
    ("paused", "expected"),
    [
        (False, "ccusage 1.83s · refresh every 5s"),
        (True, "ccusage 1.83s · paused"),
    ],
)
def test_watch_status_is_derived_from_pause_state(
    paused: bool,
    expected: str,
) -> None:
    assert (
        _watch_status(
            "ccusage 1.83s",
            load_translator("en"),
            interval=5,
            paused=paused,
        )
        == expected
    )


def test_loading_status_can_show_pause_before_first_result() -> None:
    assert (
        _watch_status(
            "Loading…",
            load_translator("en"),
            interval=5,
            paused=True,
        )
        == "Loading… · paused"
    )


def test_notice_lines_use_redundant_glyph_color_and_width() -> None:
    translator = load_translator("en")
    colored = notice_lines(
        ("A warning that is intentionally much too long",),
        width=18,
        color=True,
        ascii=False,
        translator=translator,
    )[0]
    plain = notice_lines(
        ("warning",),
        width=18,
        color=False,
        ascii=True,
        translator=translator,
    )[0]

    assert strip_ansi(colored).startswith("⚠ ")
    assert "\x1b[38;5;130m" in colored
    assert "\x1b[48;" not in colored
    assert display_width(colored) <= 18
    assert plain == "! warning"
    assert "\x1b[" not in plain


def test_controls_are_dimmed_and_clipped_to_one_row() -> None:
    colored = controls_line("r refresh · m adjust · Space pause", width=20, color=True)
    plain = controls_line("r refresh · m adjust · Space pause", width=20, color=False)

    assert colored.startswith("\x1b[2m") and colored.endswith("\x1b[0m")
    assert display_width(colored) == 20
    assert plain == "r refresh · m adjust"
    assert "\x1b[" not in plain


def test_ranking_render_shows_daily_summary_and_separate_scope_warning() -> None:
    scope_notice = Notice("notice.summary_excludes_session_agent", {"agent": "Codex"})
    rendered = render_component(
        component(
            snapshot=UsageSnapshot(
                (),
                (),
                0.0,
                coverage=DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14)),
                summary_notices=(scope_notice,),
            )
        ),
        load_translator("en"),
        Terminal(100, 30, False, True),
    )

    assert rendered.chart.splitlines()[0] == (
        "Today’s tokens 0; vs yesterday = unchanged; vs last We = unchanged"
    )
    assert rendered.notices == ("Ranking includes Codex session usage; daily Summary excludes it",)
    assert rendered.notices[0] not in rendered.chart


def test_minimal_ranking_hides_summary_notice_but_keeps_correctness_notice() -> None:
    summary_notice = Notice("notice.summary_excludes_session_agent", {"agent": "Codex"})
    correctness_notice = Notice("notice.project_agent_omitted", {"agent": "Codex"})
    selected = options()
    selected = replace(
        selected,
        chart=replace(
            selected.chart,
            presentation=replace(selected.chart.presentation, density="minimal"),
        ),
    )
    rendered = render_component(
        component(
            selected,
            snapshot=UsageSnapshot(
                (),
                (correctness_notice,),
                0.0,
                coverage=DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14)),
                summary_notices=(summary_notice,),
            ),
        ),
        load_translator("en"),
        Terminal(100, 30, False, True),
    )

    assert "Today’s tokens" not in rendered.chart
    assert rendered.notices == ("Codex omitted: ccusage does not expose project data",)


def test_render_normalizes_standalone_ranking_title() -> None:
    rendered = render_component(
        component(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        normalize_titles=True,
    )

    assert "Project · Ranking · 2026-01-01–2026-01-14" in rendered.chart


def test_render_keeps_notices_separate_from_chart() -> None:
    rendered = render_component(
        component(
            snapshot=UsageSnapshot(
                (),
                (Notice("notice.project_agent_omitted", {"agent": "Codex"}),),
                0.0,
                coverage=DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14)),
            )
        ),
        load_translator("en"),
        Terminal(100, 30, False, True),
    )

    assert rendered.notices == ("Codex omitted: ccusage does not expose project data",)
    assert rendered.notices[0] not in rendered.chart
    lines = rendered.chart.splitlines()
    assert lines[0] == "Today’s tokens 0; vs yesterday = unchanged; vs last We = unchanged"
    assert lines[1].strip() == "Ranking · 2026-01-01–2026-01-14"
    assert lines[2] == "No token usage found for the selected range."


def test_one_shot_reserves_one_more_row_than_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    heights: list[int] = []

    def capture_height(model, context) -> str:
        heights.append(context.height)
        return "chart"

    registry = ChartRegistry()
    registry.register(
        replace(RANKING_DEFINITION, renderer=cast(HistoricalRenderer, capture_height))
    )
    registry.freeze()
    snapshot = UsageSnapshot((), (), 0.1)
    terminal = Terminal(100, 30, False, True)
    translator = load_translator("en")
    chart = component(snapshot=snapshot, registry=registry)

    render_component(chart, translator, terminal)
    render_component(chart, translator, terminal, reserve_prompt=True)
    render_component(chart, translator, terminal, control_rows=1)

    assert heights == [28, 27, 27]


@pytest.mark.parametrize(
    ("command", "by", "keys", "expected"),
    [
        (
            "timeline",
            "total",
            ("b", "+", "a", "o", "\n"),
            {"by": "agent", "top": 4, "other": "show"},
        ),
        (
            "ranking",
            "project",
            ("b", "+", "a", "o", "\n"),
            {"by": "agent", "top": 11, "other": "show"},
        ),
        (
            "stack",
            "total",
            ("a", "c", "\n"),
            {"cache": "split"},
        ),
        ("calendar", "total", ("a", "\n"), {}),
    ],
)
def test_runtime_adjustment_updates_display_options_from_retained_snapshot(
    command: str,
    by: str,
    keys: tuple[str, ...],
    expected: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    inputs = iter(keys)
    rendered_components: list[HistoricalChartComponent] = []
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(inputs))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )
    original_render_component = render_component

    def capture_render_component(chart, *args, **kwargs):
        rendered_components.append(chart)
        return original_render_component(chart, *args, **kwargs)

    monkeypatch.setattr("ccusage_viz.watch.render_component", capture_render_component)
    snapshot = UsageSnapshot((), (), 0.25)
    current = options(command=command)
    if command in {"timeline", "ranking"}:
        current = replace(current, chart=replace(current.chart, by=None if by == "total" else by))

    result = run_runtime_adjustment(
        current,
        load_translator("en"),
        snapshot,
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert all(getattr(result.options.chart, field) == value for field, value in expected.items())
    assert rendered_components
    assert len({id(item) for item in rendered_components}) == 1
    assert all(item.snapshot is snapshot for item in rendered_components)
    assert result.options.chart.filters.agents == current.chart.filters.agents
    assert result.options.chart.filters.models == current.chart.filters.models
    assert result.options.chart.filters.projects == current.chart.filters.projects


def test_runtime_adjustment_period_preview_hides_accepted_chart_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("P", "\x1b"))
    rendered: list[RefreshResult] = []
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, False, True),
    )
    original_render_component = render_component

    def capture_render(component, *args, **kwargs):
        result = original_render_component(component, *args, **kwargs)
        rendered.append(result)
        return result

    monkeypatch.setattr("ccusage_viz.watch.render_component", capture_render)
    current = replace(
        options(command="ranking"),
        chart=replace(
            options(command="ranking").chart,
            date_range=DateRange(
                date(2026, 1, 1), date(2026, 1, 14), None, period="14d", relative_until=True
            ),
        ),
    )
    snapshot = UsageSnapshot(
        (
            UsageRecord(
                current.chart.date_range.until,
                "claude",
                TokenUsage(100, 100, 0, 0, 0),
                SourceKind.UNIFIED_DAILY,
            ),
        ),
        (),
        0.25,
    )

    result = run_runtime_adjustment(
        current, load_translator("en"), snapshot, cast(FramePainter, Screen())
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options != current
    assert "querying" in rendered[-1].chart
    assert "??" in rendered[-1].chart
    assert "100" not in rendered[-1].chart


def test_runtime_adjustment_retains_last_chart_until_an_invalid_draft_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("s", "\x1b"))
    calls = 0
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, False, True),
    )

    def render(chart, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise UsageError("error.stack_stacked_width", width=100)
        return RefreshResult("chart", (), 0.25, chart.snapshot, chart.candidate)

    monkeypatch.setattr("ccusage_viz.watch.render_component", render)
    current = replace(
        options(command="stack"),
        chart=replace(
            options(command="stack").chart,
            date_range=DateRange(date(2026, 1, 1), date(2026, 1, 7), None),
        ),
    )
    result = run_runtime_adjustment(
        current,
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert calls == 2
    assert any("chart" in args[0].rows and "too narrow" in str(args[0].rows) for args in paints)


def test_runtime_adjustment_pages_match_dashboard_and_weekdays_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls: list[object] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            controls.append(args[0].rows[-2:])

    keys = iter(("k", "a", "k", "b", "a", "b", "\n"))
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.weekdays == "hide"
    assert result.options.chart.by == "agent"
    assert "Quick adjustment" in str(controls[0])
    assert "Advanced adjustment" in str(controls[1])
    assert "k weekdays" in str(controls[1])
    assert "WEEKDAYS hide" in str(controls[2])


def test_project_adjustment_explains_missing_retained_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("b", "b", "b", "\x1b"))
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.by == "project"
    assert any("project data is not in this preview" in str(args[0].rows) for args in paints)


def test_project_aggregation_adjustment_is_advanced_and_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("b", "b", "b", "a", "A", "\n"))
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25, includes_project_attribution=True),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.by == "project"
    assert result.options.chart.project_aggregation == "exact"
    assert any("A project aggregation" in str(args[0].rows) for args in paints)
    assert any("PROJECT AGGREGATION exact" in str(args[0].rows) for args in paints)


def test_runtime_adjustment_ignores_removed_copy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("b", "+", "a", "o", "y", "\x1b"))
    copied: list[str] = []
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.copy_command", lambda command: copied.append(command) or True
    )

    result = run_runtime_adjustment(
        replace(
            options(command="timeline"),
            chart=replace(
                options(command="timeline").chart,
                by=None,
                top=3,
                presentation=replace(
                    options(command="timeline").chart.presentation, theme="no-color"
                ),
            ),
        ),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.by == "agent"
    assert result.options.chart.top == 4
    assert result.options.chart.other == "show"
    assert copied == []


def test_runtime_adjustment_normalizes_timeline_area_when_grouping_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("b", "\n"))
    monkeypatch.setattr("ccusage_viz.watch.input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch.read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        replace(
            options(command="timeline"),
            chart=replace(
                options(command="timeline").chart,
                by=None,
                presentation=replace(options(command="timeline").chart.presentation, style="area"),
            ),
        ),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(FramePainter, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.by == "agent"
    assert result.options.chart.presentation.style == "linear"


@pytest.mark.skipif(os.name != "posix", reason="PTY smoke test is POSIX-only")
def test_demo_watch_reports_pause_immediately_and_restores_terminal() -> None:
    import pty
    import select
    import subprocess
    import termios
    import time

    master, slave = pty.openpty()
    env = {
        **os.environ,
        "COLUMNS": "100",
        "LINES": "30",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ccusage_viz",
            "ranking",
            "--demo",
            "small",
            "--interval",
            "5",
            "--ascii",
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        text=False,
        env=env,
        close_fds=True,
    )
    output = bytearray()
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline and b"Ranking" not in output:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 8192))
        assert b"Ranking" in output

        os.write(master, b" ")
        pause_deadline = time.monotonic() + 1
        while time.monotonic() < pause_deadline and b"paused" not in output:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                output.extend(os.read(master, 8192))
        assert b"paused" in output

        os.write(master, b"\x03")
        assert process.wait(timeout=3) == 0
        while True:
            readable, _, _ = select.select([master], [], [], 0.1)
            if not readable:
                break
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
        assert output.endswith((b"\n", b"\r\n"))
        after = termios.tcgetattr(slave)
        assert after[3] & termios.ICANON
        assert after[3] & termios.ECHO
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)

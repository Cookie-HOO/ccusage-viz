"""Dataset keyboard audit through dispatch_event, not just adjustment helpers.

Only terminal output and provider submission are replaced. Components, query
configuration, filter editor, history, key routing and pane rendering are real.
Regression assertions cover the previously broken controls and history paths.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.events as events
import ccusage_viz.tui.history as history
import ccusage_viz.tui.pane_events as pane_events
import ccusage_viz.tui.queries as queries
import ccusage_viz.tui.session as sessions
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomData,
    CustomDimension,
    CustomFilter,
    CustomFilterOption,
    CustomPoint,
    CustomRankingEntry,
    CustomSeries,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2MonitorCapability,
    V2ProbeDescriptor,
    V2RankingData,
    V2Runtime,
)
from ccusage_viz.custom_protocol.responses import V2ChartResponse
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.custom_adjustments import _custom_pane_adjustment_bindings
from ccusage_viz.tui.models import TuiCustomPane
from ccusage_viz.tui.rendering import _pane_render
from ccusage_viz.tui_input import InputDecoder, KeyEvent

from .custom_helpers import _custom_monitor_component

TEXT = LocalizedText("Audit", "验证")
FILTER = CustomFilter(
    "category",
    TEXT,
    (
        CustomFilterOption("a", LocalizedText("Alpha", "甲")),
        CustomFilterOption("b", LocalizedText("Beta", "乙")),
    ),
)
KINDS = ("timeline", "stack", "calendar", "ranking", "partitioned-ranking", "monitor")
MONITOR_STYLES = ("line", "step", "points", "ranking", "list", "cumulative-bars")


def _descriptor(kind, aggregation="sum"):
    capability = (
        V2MonitorCapability(60, 10, (None, "real_model", "public_model"), ("category",))
        if kind == "monitor"
        else V2HistoricalChartCapability(
            ("day", "week"),
            (None, "real_model", "public_model"),
            ("category",),
            periods=("7d", "14d"),
            partition_by=(None, "partition", "public_model") if kind == "ranking" else None,
        )
    )
    capabilities = V2MetricCapabilities(
        (CustomDimension("real_model", TEXT), CustomDimension("public_model", TEXT)),
        (FILTER,),
        {kind: capability},
    )
    metrics = tuple(
        V2MetricDescriptor(
            identifier,
            LocalizedText(identifier, identifier),
            TEXT,
            CustomUnit("count", TEXT, "suffix", 0),
            aggregation,
            capabilities,
            {},
            group_id="audit",
        )
        for identifier in ("first", "second", "third")
    )
    return V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(TEXT, TEXT),
        metrics,
        (),
        metric_groups=(V2MetricGroup("audit", TEXT),),
    )


def _accept_historical(component, descriptor):
    kind = component.request_config.kind
    if kind == "ranking":
        from ccusage_viz.custom_models import V2RankingGroup

        entries = tuple(
            CustomRankingEntry(key, label, Decimal(value))
            for key, label, value in (
                ("a", LocalizedText("Alpha", "甲"), "60"),
                ("b", LocalizedText("Beta", "乙"), "30"),
                ("c", LocalizedText("Gamma", "丙"), "10"),
            )
        )
        data = (
            V2RankingData(groups=(V2RankingGroup("p", TEXT, entries),))
            if component.request_config.partition_by
            else V2RankingData(entries)
        )
    else:
        data = CustomData(
            tuple(
                CustomSeries(
                    key,
                    label,
                    (CustomPoint(component.request_config.date_range.until, Decimal(value)),),
                )
                for key, label, value in (
                    ("a", LocalizedText("Alpha", "甲"), "60"),
                    ("b", LocalizedText("Beta", "乙"), "30"),
                    ("c", LocalizedText("Gamma", "丙"), "10"),
                )
            )
        )
    if kind == "calendar":
        data = CustomData((replace(data.series[0], id="total"),))
    assert component.apply_provider_result(
        SimpleNamespace(
            custom_response=V2ChartResponse(
                component.request_config.metric_id,
                data,
                descriptor,
                V2Runtime((FILTER,)),
            )
        ),
        accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def audit(monkeypatch):
    translator = load_translator("en")
    options = _to_options(
        build_parser(translator).parse_args(["dashboard", "--empty", "--header-style", "hidden"])
    )
    monkeypatch.setattr(sessions, "build_query_runtime", lambda: SimpleNamespace())
    session = sessions.TuiSession(options, translator)
    session.decoder = InputDecoder()
    submitted = []
    frames = []
    # Actual frame generation remains covered by _pane_render below. Suppress
    # terminal I/O and isolate provider submission while retaining real mutation.
    for module in (events, pane_events):
        monkeypatch.setattr(module, "paint", lambda *a, **k: None)
    for module in (pane_events, queries):
        monkeypatch.setattr(module, "refresh", lambda *a, **k: submitted.append(k))
    monkeypatch.setattr(queries, "sync_custom_dashboard_summaries", lambda *a: None)

    def make(kind="monitor", style="cumulative-bars", aggregation="sum", grouped=True):
        submitted.clear()
        frames.clear()
        session.custom_logs = None
        session.help_overlay = None
        session.adjustment_mode = None
        session.adjustment_timer = None
        session.focused = None
        actual_kind = "ranking" if kind == "partitioned-ranking" else kind
        descriptor = _descriptor(actual_kind, aggregation)
        if actual_kind == "monitor":
            component = _custom_monitor_component(grouped=grouped)
            component.configure(
                replace(
                    component.candidate,
                    metric_id="first",
                    top=2,
                    presentation=ChartPresentation(style=style),
                ),
                data_affecting=False,
            )
            component.v2_descriptor = descriptor
            component.set_metric(descriptor.metrics[0])
            component.runtime = V2Runtime((FILTER,))
        else:
            chart = CustomChartConfig(
                actual_kind,
                CustomCommandSource("audit", ("audit",)),
                DateRange(date(2026, 10, 2), date(2026, 10, 8), period="7d"),
                metric_id="first",
                group_by="real_model" if grouped and actual_kind != "calendar" else None,
                partition_by="partition" if kind == "partitioned-ranking" else None,
                top=2,
                presentation=ChartPresentation(
                    style="bars" if actual_kind == "ranking" else "line"
                ),
            )
            component = CustomHistoricalComponent(chart)
            _accept_historical(component, descriptor)
        pane = TuiCustomPane(
            component,
            FixedIntervalScheduler(10, now=0),
            LifecycleOperation("audit"),
            options.process,
            pane_id=0,
        )
        session.panes = [pane]
        session.history = DashboardHistory(history.capture_dashboard_state(session))

        def press(key):
            events.dispatch_event(session, KeyEvent(key), now=1)

        def complete():
            if actual_kind != "monitor":
                _accept_historical(component, descriptor)
            else:
                from ccusage_viz.custom_models import V2MetricValue, V2MonitorObservation
                from ccusage_viz.custom_monitor_models import CustomMonitorCompletion
                from ccusage_viz.custom_protocol.responses import V2MonitorResponse

                config = component.request_config
                observation = V2MonitorObservation(
                    datetime(2026, 10, 8, 12, tzinfo=UTC),
                    Decimal("90"),
                    (
                        V2MetricValue("a", LocalizedText("Alpha", "甲"), Decimal("60")),
                        V2MetricValue("b", LocalizedText("Beta", "乙"), Decimal("30")),
                    )
                    if config.group_by is not None
                    else (),
                )
                assert component.accept(
                    CustomMonitorCompletion(
                        component.generation,
                        config,
                        V2MonitorResponse(
                            config.metric_id, observation, descriptor, V2Runtime((FILTER,))
                        ),
                    ),
                    accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
                )

        def render(width=100, height=30):
            result = _pane_render(
                pane,
                translator,
                Terminal(width, height, color=False, ascii=True),
                dashboard=options,
            )
            frames.append(result.chart)
            return result.chart

        press("m")
        assert session.adjustment_mode == "pane"
        return SimpleNamespace(
            session=session,
            pane=pane,
            component=component,
            press=press,
            complete=complete,
            render=render,
            submitted=submitted,
            descriptor=descriptor,
        )

    yield make
    session.executor.shutdown(wait=True, cancel_futures=True)


# Every declared quick/advanced binding except modal controls, which have
# dedicated interaction sequences below. Both case variants are exercised.
CASES = []
for kind in KINDS:
    keys = "dDtTsSmM"
    if kind == "monitor":
        keys += "wbB+-ol"
    else:
        keys += "pP"
        if kind != "calendar":
            keys += "bB+-o"
        if kind in {"timeline", "stack"}:
            keys += "gGlk"
        if kind == "partitioned-ranking":
            keys += "gG"
    for key in keys:
        CASES.append(pytest.param(kind, key, id=f"{kind}-{key}"))


@pytest.mark.parametrize("kind,key", CASES)
def test_declared_key_changes_its_intended_state(audit, kind, key):
    a = audit(kind)
    before = a.component.candidate
    window = (
        getattr(a.component, "distribution_day_window", None),
        getattr(a.component, "display_window_seconds", None),
    )
    a.press(key)
    after = a.component.candidate
    fields = {"d": "density", "t": "theme", "s": "style"}
    lower = key.lower()
    if lower in fields:
        assert getattr(after.presentation, fields[lower]) != getattr(
            before.presentation, fields[lower]
        )
    elif lower == "m":
        target = a.component.switch_target_config
        assert target is not None and target.metric_id != before.metric_id
        assert a.submitted
    elif lower == "p":
        assert after.date_range != before.date_range
        assert a.submitted
    elif lower == "g":
        field = "partition_by" if kind == "partitioned-ranking" else "granularity"
        assert getattr(after, field) != getattr(before, field)
        assert a.submitted
    elif lower == "b":
        assert after.group_by != before.group_by
        assert a.submitted
    elif key in "+-":
        assert after.top == (
            None if key == "+" and kind == "monitor" else before.top + (1 if key == "+" else -1)
        )
    elif key == "o":
        assert after.other != before.other
    elif key == "l":
        assert after.presentation.legend != before.presentation.legend
    elif key == "k":
        assert after.weekdays != before.weekdays
    elif key == "w":
        assert window != (a.component.distribution_day_window, a.component.display_window_seconds)
        assert not a.submitted
    # Reproduce the next successful provider completion for query-changing keys.
    if a.submitted:
        a.complete()
        if lower == "m":
            assert a.component.accepted_config.metric_id != before.metric_id
    assert a.render()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("key,delta", (("=", 1), ("_", -1)))
def test_top_aliases_use_real_event_entry(audit, kind, key, delta):
    if kind == "calendar":
        pytest.skip("Calendar does not expose Top")
    a = audit(kind)
    before = a.component.candidate.top
    a.press(key)
    expected = None if key == "=" and kind == "monitor" else before + delta
    assert a.component.candidate.top == expected


@pytest.mark.parametrize("style", MONITOR_STYLES)
@pytest.mark.parametrize("aggregation", ("sum", "value"))
@pytest.mark.parametrize("grouped", (False, True))
def test_monitor_presentation_interactions_across_styles(audit, style, aggregation, grouped):
    if style == "cumulative-bars" and aggregation == "value":
        pytest.skip("Value aggregation cannot accumulate")
    a = audit(style=style, aggregation=aggregation, grouped=grouped)
    for key, field in (
        ("d", "density"),
        ("D", "density"),
        ("t", "theme"),
        ("T", "theme"),
        ("s", "style"),
        ("S", "style"),
    ):
        before = getattr(a.component.candidate.presentation, field)
        a.press(key)
        assert getattr(a.component.candidate.presentation, field) != before
        assert a.render()
    assert not a.submitted


@pytest.mark.parametrize("kind", KINDS)
def test_filter_editor_apply_and_cancel_via_keyboard(audit, monkeypatch, kind):
    a = audit(kind)
    editor_keys = iter((KeyEvent(" "), KeyEvent("\r")))
    monkeypatch.setattr(pane_events, "read_adjustment_event", lambda *args: next(editor_keys))
    a.press("f")
    assert a.component.candidate.filters
    assert a.submitted
    accepted = a.component.candidate.filters
    editor_keys = iter((KeyEvent(" "), KeyEvent("\x1b")))
    a.press("f")
    assert a.component.candidate.filters == accepted


@pytest.mark.parametrize("kind", KINDS)
def test_view_logs_help_and_exit_interactions(audit, kind):
    a = audit(kind)
    a.press("a")
    assert a.session.adjustment_page == "advanced"
    a.press("a")
    assert a.session.adjustment_page == "quick"
    a.press("v")
    assert a.pane.body_view != "chart"
    assert a.render()
    a.press("V")
    assert a.pane.body_view == "chart"
    a.press("L")
    assert a.session.custom_logs is not None
    a.press("\x1b")
    assert a.session.custom_logs is None
    a.press("h")
    assert a.session.help_overlay is not None
    a.press("\x1b")
    assert a.session.help_overlay is None
    a.press("\r")
    assert a.session.adjustment_mode is None


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize("key", ("s", "S"))
def test_ranking_advanced_spacing_and_search(audit, kind, key):
    a = audit(kind)
    a.render()
    a.press("a")
    before = a.pane.ranking_item_spacing
    a.press(key)
    assert a.pane.ranking_item_spacing != before
    assert not a.submitted
    a.press("/")
    assert a.pane.ranking_search.editing
    for character in "Alpha":
        a.press(character)
    a.press("\r")
    assert a.pane.ranking_search.query == "Alpha"
    assert not a.pane.ranking_search.editing
    rendered = a.render()
    assert "Alpha" in rendered and "Beta" not in rendered


@pytest.mark.parametrize("style", MONITOR_STYLES)
def test_monitor_other_changes_rendered_projection(audit, style):
    if style == "cumulative-bars":
        pytest.skip("Covered by the strict cumulative-bars defect test below")
    a = audit(style=style)
    a.press("-")  # Top 1, leaving Beta in Other
    visible = a.render()
    assert "Other" in visible
    a.press("o")
    assert a.component.candidate.other == "hide"
    assert "Other" not in a.render()


def test_cumulative_other_hide_after_real_key_event(audit):
    a = audit()
    a.press("-")
    assert "Other" in a.render()
    a.press("o")
    assert a.component.candidate.other == "hide"
    assert "Other" not in a.render()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("size", ((100, 30), (40, 15), (9, 8)))
def test_adjustments_still_render_at_narrow_sizes(audit, kind, size):
    a = audit(kind)
    for key in ("d", "t", "s"):
        a.press(key)
        try:
            assert isinstance(a.render(*size), str)
        except Exception as error:
            from ccusage_viz.errors import UsageError

            # The low-level renderer rejects insufficient plot geometry.
            # Actual Dashboard fallback is audited separately below.
            assert isinstance(error, UsageError) and size == (9, 8)
            assert error.key == "error.stack_stacked_width"


@pytest.mark.parametrize("kind", KINDS)
def test_theme_history_undo_redo_through_dispatch(audit, kind):
    a = audit(kind)
    before = a.component.candidate.presentation.theme
    a.press("t")
    changed = a.component.candidate.presentation.theme
    a.press("u")
    assert a.component.candidate.presentation.theme == before
    a.press("U")
    assert a.component.candidate.presentation.theme == changed
    assert not a.submitted
    assert a.render()


@pytest.mark.parametrize("style", ("line", "cumulative-bars"))
def test_monitor_window_forward_toggle_and_retention(audit, style):
    a = audit(style=style)
    before = (
        a.component.display_window_seconds
        if style == "line"
        else a.component.distribution_day_window
    )
    a.press("w")
    after = (
        a.component.display_window_seconds
        if style == "line"
        else a.component.distribution_day_window
    )
    assert before != after
    assert not a.submitted
    assert a.component.history
    assert a.render()


@pytest.mark.parametrize("key", ("t", "T", "s", "S"))
def test_monitor_advanced_attachment_controls(audit, key):
    from ccusage_viz.animation import animation_spec, new_animation_session

    a = audit(style="ranking")
    a.pane.attachment = new_animation_session(
        animation_spec("mole-cat", target="monitor"), theme="classic"
    )
    a.pane.attachment_enabled = True
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))
    a.press("a")
    before = (a.pane.attachment.theme, a.pane.attachment.spec.style, a.pane.attachment_enabled)
    chart = a.component.candidate
    a.press(key)
    after = (a.pane.attachment.theme, a.pane.attachment.spec.style, a.pane.attachment_enabled)
    assert after != before
    assert a.component.candidate == chart
    assert not a.submitted


@pytest.mark.parametrize("kind", ("timeline", "stack", "ranking", "partitioned-ranking", "monitor"))
def test_top_all_uses_monotonic_quantity_semantics(audit, kind):
    a = audit(kind)
    original = a.component.candidate
    a.component.configure(replace(original, top=None), data_affecting=False)
    assert a.component.candidate.top is None
    a.press("+")
    assert a.component.candidate.top is None
    maximum = 2 if kind == "monitor" else 3
    a.press("-")
    assert a.component.candidate.top == maximum - 1
    a.press("-")
    assert a.component.candidate.top == 1
    a.press("-")
    assert a.component.candidate.top == 1
    for expected in range(2, maximum + 1):
        a.press("+")
        assert a.component.candidate.top == expected
    a.press("+")
    assert a.component.candidate.top is None


@pytest.mark.parametrize("style", ("line", "cumulative-bars", "ranking"))
def test_monitor_top_counts_active_view_not_only_latest_sample(audit, style):
    from ccusage_viz.custom_models import V2MetricValue

    a = audit(style=style)
    response = a.component.history[-1]
    earlier = replace(
        response,
        observation=replace(
            response.observation,
            end_at=response.observation.end_at.replace(hour=11, minute=59),
            groups=tuple(V2MetricValue(str(i), TEXT, Decimal(10)) for i in range(8)),
        ),
    )
    latest = replace(
        response,
        observation=replace(
            response.observation,
            groups=(V2MetricValue("0", TEXT, Decimal(10)),),
        ),
    )
    a.component.history[:] = [earlier, latest]
    a.component.accepted_response = latest
    a.component.configure(replace(a.component.candidate, top=None), data_affecting=False)
    extent = 1 if style == "ranking" else 8
    assert a.component.top_extent() == extent
    a.press("-")
    assert a.component.candidate.top == (None if extent == 1 else 7)
    if extent > 1:
        a.press("-")
        assert a.component.candidate.top == 6
        a.press("+")
        assert a.component.candidate.top == 7
        a.press("+")
        assert a.component.candidate.top == 8
        a.press("+")
        assert a.component.candidate.top is None
    assert not a.submitted


def test_cumulative_monitor_top_counts_selected_day(audit):
    from ccusage_viz.custom_models import V2MetricValue

    a = audit(style="cumulative-bars")
    response = a.component.history[-1]
    yesterday = replace(
        response,
        observation=replace(
            response.observation,
            end_at=response.observation.end_at.replace(day=7, hour=12),
            groups=tuple(V2MetricValue(str(i), TEXT, Decimal(10)) for i in range(5)),
        ),
    )
    a.component.history.insert(0, yesterday)
    a.component.configure(replace(a.component.candidate, top=None), data_affecting=False)
    assert a.component.top_extent() == 2
    a.press("w")
    assert a.component.distribution_day_window == "yesterday"
    assert a.component.top_extent() == 5
    a.press("-")
    assert a.component.candidate.top == 4
    a.press("+")
    assert a.component.candidate.top == 5
    a.press("+")
    assert a.component.candidate.top is None
    assert not a.submitted


def test_ranking_top_increase_survives_a_full_retrieval_horizon(audit):
    """A bounded legend's …(+N) must not make Top look source-exhausted."""
    a = audit("ranking")
    response = a.component.accepted_response
    assert isinstance(response, V2ChartResponse)
    assert isinstance(response.data, V2RankingData)
    a.component.accepted_response = replace(
        response,
        data=replace(response.data, series=response.data.series[:2]),
    )
    a.component.retrieval_top = 2

    a.press("+")

    assert a.component.candidate.top == 3
    assert a.submitted


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
def test_router_list_refresh_tracks_raw_value_with_unchanged_display(audit, monkeypatch, kind):
    from concurrent.futures import Future

    from ccusage_viz.custom_models import CustomRankingEntry, V2RankingData, V2RankingGroup
    from ccusage_viz.custom_protocol.responses import V2ChartResponse
    from ccusage_viz.lifecycle import LifecycleTrigger
    from ccusage_viz.tui.completion import collect
    from ccusage_viz.tui.models import CustomOutcome

    a = audit(kind)
    a.component.configure(
        replace(
            a.component.candidate,
            presentation=replace(
                a.component.candidate.presentation, style="list", show_percentage=False
            ),
        ),
        data_affecting=False,
    )
    descriptor = replace(
        a.descriptor,
        metrics=tuple(
            replace(
                metric,
                capabilities=replace(
                    metric.capabilities,
                    charts={
                        "ranking": replace(metric.capabilities.charts["ranking"], comparison="none")
                    },
                ),
            )
            for metric in a.descriptor.metrics
        ),
    )
    monkeypatch.setattr(queries, "start_pane", lambda *args, **kwargs: None)
    monkeypatch.setattr(queries, "start_header", lambda *args, **kwargs: None)
    a.pane.summary = None

    def complete_raw(raw):
        entry = CustomRankingEntry(
            "router",
            LocalizedText("Router Token", "Router Token"),
            Decimal(raw),
            display=LocalizedText("3.6B", "3.6B"),
        )
        data = (
            V2RankingData(groups=(V2RankingGroup("p", TEXT, (entry,)),))
            if kind == "partitioned-ranking"
            else V2RankingData((entry,))
        )
        response = V2ChartResponse("first", data, descriptor, V2Runtime((FILTER,)))
        future = Future()
        future.set_result(
            CustomOutcome(a.component.generation, result=SimpleNamespace(custom_response=response))
        )
        assert a.pane.lifecycle.request(
            LifecycleTrigger.PERIODIC,
            generation=a.component.generation,
            now=1,
            start=lambda token: (future, lambda: None),
        )
        assert collect(a.session)
        return a.render()

    row = next(row for row in complete_raw("3633448769").splitlines() if "Router Token" in row)
    assert row.rstrip().endswith("3.6B")
    row = next(row for row in complete_raw("3633448770").splitlines() if "Router Token" in row)
    assert row.rstrip().endswith("3.6B ^")
    row = next(row for row in complete_raw("3633448770").splitlines() if "Router Token" in row)
    assert row.rstrip().endswith("3.6B -")
    # Beyond binary-float precision, a single raw token still must be detected.
    complete_raw("9007199254740992")
    row = next(
        row for row in complete_raw("9007199254740993").splitlines() if "Router Token" in row
    )
    assert row.rstrip().endswith("3.6B ^")
    a.press("p")
    row = next(
        row for row in complete_raw("9007199254740994").splitlines() if "Router Token" in row
    )
    assert row.rstrip().endswith("3.6B")


def test_native_ranking_percentage_keyboard_history(audit):
    from ccusage_viz.options import ChartPaneConfig, RankingConfig
    from ccusage_viz.tui.pane_lifecycle import _new_pane

    a = audit()
    chart = RankingConfig("ranking", DateRange(date(2026, 10, 2), date(2026, 10, 8)))
    pane = _new_pane(a.session.options, ChartPaneConfig(chart), "audit-native", None)
    pane.pane_id = 0
    a.session.panes = [pane]
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))
    a.press("%")
    assert a.session.adjustment_page == "advanced"
    assert pane.component.candidate.chart.presentation.show_percentage is False
    a.press("u")
    assert pane.component.candidate.chart.presentation.show_percentage is None
    a.press("U")
    assert pane.component.candidate.chart.presentation.show_percentage is False
    assert not a.submitted


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize("source_visible", (True, False))
@pytest.mark.parametrize("style", ("dot", "list"))
def test_ranking_percentage_keyboard_toggle_and_history(audit, kind, source_visible, style):
    a = audit(kind)
    a.component.configure(
        replace(
            a.component.candidate,
            presentation=replace(a.component.candidate.presentation, style=style),
        ),
        data_affecting=False,
    )
    metric = a.descriptor.metrics[0]
    caps = metric.capabilities
    chart_cap = replace(caps.charts["ranking"], show_percentage=source_visible)
    descriptor = replace(
        a.descriptor,
        metrics=(
            replace(metric, capabilities=replace(caps, charts={"ranking": chart_cap})),
            *a.descriptor.metrics[1:],
        ),
    )
    _accept_historical(a.component, descriptor)
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))
    assert a.component.model.show_percentage == source_visible
    assert ("%" in a.render()) == source_visible
    a.press("%")
    assert a.session.adjustment_page == "advanced"
    assert a.component.model.show_percentage == (not source_visible)
    output = a.render()
    assert ("%" in output) == (not source_visible)
    from ccusage_viz.formatting import display_width, strip_ansi

    primary_rows = [
        strip_ansi(row) for row in output.splitlines() if "Alpha" in row or "Beta" in row
    ]
    # The viewport reserves the final cell for its scrollbar.
    assert all(display_width(row) == 99 for row in primary_rows)
    a.press("u")
    assert a.component.model.show_percentage == source_visible
    a.press("U")
    assert a.component.model.show_percentage == (not source_visible)
    assert not a.submitted


@pytest.mark.parametrize("kind", KINDS)
def test_data_and_command_views_copy_actual_payload(audit, monkeypatch, kind):
    captured = []
    monkeypatch.setattr(pane_events, "copy_command", lambda text: captured.append(text) or True)
    a = audit(kind)
    for _ in range(4):
        a.press("v")
        assert a.render()
        a.press("y")
        assert captured[-1]
    assert not a.submitted


@pytest.mark.parametrize("kind", KINDS)
def test_declared_bindings_have_audited_controls(audit, kind):
    a = audit(kind)
    bindings = (
        *_custom_pane_adjustment_bindings(a.pane, "quick"),
        *_custom_pane_adjustment_bindings(a.pane, "advanced"),
    )
    tested = set("dDtTsSmMpPgGbB+-olkwfL%C")
    assert all(
        character in tested for binding, _ in bindings for character in binding if character != "/"
    )


@pytest.mark.parametrize("style", ("line", "cumulative-bars"))
def test_monitor_window_can_be_undone(audit, style):
    a = audit(style=style)
    before = (a.component.display_window_seconds, a.component.distribution_day_window)
    a.press("w")
    changed = (a.component.display_window_seconds, a.component.distribution_day_window)
    assert before != changed
    a.press("u")
    assert before == (a.component.display_window_seconds, a.component.distribution_day_window)
    a.press("U")
    assert changed == (a.component.display_window_seconds, a.component.distribution_day_window)
    assert not a.submitted


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
def test_ranking_spacing_can_be_undone(audit, kind):
    a = audit(kind)
    a.press("a")
    before = a.pane.ranking_item_spacing
    a.press("s")
    changed = a.pane.ranking_item_spacing
    assert changed != before
    a.press("u")
    assert a.pane.ranking_item_spacing == before
    a.press("U")
    assert a.pane.ranking_item_spacing == changed
    assert not a.submitted


@pytest.mark.parametrize("style", MONITOR_STYLES)
@pytest.mark.parametrize("aggregation", ("sum", "value"))
def test_monitor_top_and_group_interactions_across_styles(audit, style, aggregation):
    if aggregation == "value" and style == "cumulative-bars":
        pytest.skip("Value aggregation cannot accumulate")
    a = audit(style=style, aggregation=aggregation)
    for key in ("-", "+", "b", "B"):
        before = a.component.candidate
        a.press(key)
        assert a.component.candidate != before
        if key in ("b", "B"):
            assert not a.component.history  # old grouped facts must be discarded
            a.complete()
            assert a.component.history
        assert a.render()


@pytest.mark.parametrize(
    "kind,size",
    [
        pytest.param(
            kind,
            size,
        )
        for kind in KINDS
        for size in ((100, 30), (40, 15), (9, 8))
    ],
)
def test_actual_dashboard_frames_after_keyboard_events(audit, monkeypatch, kind, size):
    import os

    import ccusage_viz.tui.painting as painting

    a = audit(kind)
    painted = []
    a.session.screen = SimpleNamespace(paint=lambda frame, **kwargs: painted.append(frame))
    monkeypatch.setattr(painting, "get_terminal_size", lambda: os.terminal_size(size))
    for key in ("d", "t", "s"):
        a.press(key)
        painting.paint(a.session, force=True)
        assert painted[-1].rows
    # A failed small plot must not poison the render cache after resizing.
    monkeypatch.setattr(painting, "get_terminal_size", lambda: os.terminal_size((100, 40)))
    painting.paint(a.session, force=True)
    assert "Pane too small" not in "\n".join(painted[-1].rows)


@pytest.mark.parametrize(
    "style,expected",
    (
        ("line", ("inside", "hidden", "below-title")),
        ("cumulative-bars", ("inside", "values", "hidden", "below-title")),
    ),
)
def test_monitor_legend_cycles_and_survives_style_switch(audit, style, expected):
    a = audit(style=style)
    for legend in expected:
        a.press("l")
        assert a.component.candidate.presentation.legend == legend
        assert a.render()
    if style == "cumulative-bars":
        a.press("l")
        a.press("l")
        assert a.component.candidate.presentation.legend == "values"
        a.press("s")
        a.press("l")
        assert a.component.candidate.presentation.legend in {"below-title", "inside", "hidden"}
        assert a.render()
    assert not a.submitted

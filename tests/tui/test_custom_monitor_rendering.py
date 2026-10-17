


from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    custom_monitor_y_axis_max,
)
from ccusage_viz.custom_protocol.responses import V2MonitorResponse
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.render import RenderContext
from ccusage_viz.render.custom_monitor import render_custom_monitor
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.rendering import _pane_render

from .custom_helpers import _custom_monitor_component, _dashboard_help_frames


def test_dashboard_help_overlay_omits_monitor_metric_after_descriptorless_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Router", "路由")
    unit = CustomUnit("count", text, "suffix", 0)
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        metric_id="tokens",
    )
    component = CustomMonitorComponent(chart)
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            V2MetricDescriptor(
                "tokens",
                LocalizedText("Tokens", "令牌"),
                LocalizedText("Current token rate", "当前令牌速率"),
                unit,
                "sum",
                V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
                {},
            ),
        ),
        (),
    )
    observation = V2MonitorObservation(datetime(2026, 10, 8, 12, tzinfo=UTC), Decimal("1"), ())
    assert component.accept(
        CustomMonitorCompletion(0, chart, V2MonitorResponse("tokens", observation, descriptor)),
        accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )
    assert component.accept(
        CustomMonitorCompletion(0, chart, V2MonitorResponse("tokens", observation)),
        accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )
    assert component.v2_descriptor is None
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("monitor-v1-metric-help"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    help_overlay = _dashboard_help_frames(monkeypatch, pane, language="en", width=80)

    assert "CURRENT METRIC" not in help_overlay
    assert "Tokens" not in help_overlay

def test_custom_monitor_renders_source_owned_monitor_presentations_without_shares() -> None:
    component = _custom_monitor_component()
    terminal = Terminal(80, 16, color=False, ascii=True)
    translated = load_translator("en")

    bars = tui_custom_rendering._render_custom_monitor(component, translated, terminal, interval=10).chart
    component.configure(
        tui_module._adjust_custom_monitor_chart(component.candidate, "s"), data_affecting=False
    )
    line = tui_custom_rendering._render_custom_monitor(component, translated, terminal, interval=10).chart
    component.configure(
        tui_module._adjust_custom_monitor_chart(component.candidate, "s"), data_affecting=False
    )
    step = tui_custom_rendering._render_custom_monitor(component, translated, terminal, interval=10).chart

    assert "Alpha" in bars and "Beta" in bars
    assert "Other" not in bars
    assert "%" not in bars and "%" not in line and "%" not in step
    assert "Requests · Trend · by real_model · 1m window" in bars
    assert "view 1h" not in bars
    assert "data window" not in bars

def test_custom_monitor_retains_accepted_values_only_for_refreshes() -> None:
    component = _custom_monitor_component()
    terminal = Terminal(80, 16, color=False, ascii=True)

    periodic = tui_custom_rendering._render_custom_monitor(
        component,
        load_translator("en"),
        terminal,
        interval=10,
        refreshing=True,
    ).chart
    assert "Alpha" in periodic
    assert "querying" in periodic

    component.configure(replace(component.candidate, group_by=None), data_affecting=True)
    switched = tui_custom_rendering._render_custom_monitor(
        component,
        load_translator("en"),
        terminal,
        interval=10,
    ).chart
    assert "Loading…" in switched
    assert "Alpha" not in switched

@pytest.mark.parametrize(
    ("style", "view"),
    (
        ("line", "Trend"),
        ("ranking", "Ranking"),
        ("list", "List"),
        ("cumulative-bars", "Cumulative bars"),
    ),
)
@pytest.mark.parametrize("failed", (False, True), ids=("pending", "error"))
def test_custom_monitor_transient_states_use_canonical_heading(
    style: str, view: str, failed: bool
) -> None:
    component = _custom_monitor_component()
    component.accepted_response = None
    component.accepted_config = None
    component.configure(
        replace(
            component.candidate, presentation=replace(component.candidate.presentation, style=style)
        ),
        data_affecting=False,
    )
    component.error = RuntimeError("source failed") if failed else None

    rendered = tui_custom_rendering._render_custom_monitor(
        component,
        load_translator("en"),
        Terminal(80, 16, color=False, ascii=True),
        interval=10,
    )
    heading = rendered.chart.splitlines()[0].strip()

    expected = f"Requests · {view} · by real_model · 1m window"
    assert heading == (expected if failed else f"{expected} · querying")
    assert rendered.error_body is failed
    assert ("source failed" in rendered.chart) is failed
    for excluded in ("view", "data window", "router-dataset", "token"):
        assert excluded not in heading.lower()
    assert all(display_width(line) <= 80 for line in rendered.chart.splitlines())

@pytest.mark.parametrize("failed", (False, True), ids=("pending", "error"))
def test_custom_monitor_unresolved_transient_state_omits_unfactual_heading(
    failed: bool,
) -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("private-dataset-id", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="private-metric-id",
    )
    component = CustomMonitorComponent(chart)
    component.error = RuntimeError("probe failed") if failed else None

    rendered = tui_custom_rendering._render_custom_monitor(
        component,
        load_translator("en"),
        Terminal(24, 10, color=False, ascii=True),
        interval=10,
    )

    assert rendered.chart == ("probe failed" if failed else "Loading…")
    assert "private-dataset-id" not in rendered.chart
    assert "private-metric-id" not in rendered.chart
    assert rendered.error_body is failed

def test_custom_monitor_pane_preserves_probe_error_body() -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="tokens",
    )
    component = CustomMonitorComponent(chart)
    assert component.fail(RuntimeError("probe failed"), generation=component.generation)
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-monitor-probe-error"),
        SimpleNamespace(),
    )

    rendered = _pane_render(pane, load_translator("en"), Terminal(80, 16, color=False, ascii=True))

    assert rendered.error_body
    assert rendered.chart == "probe failed"

def test_custom_monitor_ranking_and_list_keep_native_row_geometry() -> None:
    component = _custom_monitor_component()
    translator = load_translator("en")

    for style in ("ranking", "list"):
        config = replace(
            component.candidate, presentation=replace(component.candidate.presentation, style=style)
        )
        component.configure(config, data_affecting=False)
        context = RenderContext(80, 16, translator, color=False, ascii=True, style=style)

        native_rows = render_ranking(component.ranking_model(language="en"), context).splitlines()[
            1:
        ]
        custom_rows = render_custom_monitor(component, context).splitlines()[1:]

        assert custom_rows == native_rows
        assert all(display_width(row) <= context.width for row in custom_rows)
        assert "%" not in "\n".join(custom_rows)

def test_custom_monitor_cycles_only_native_compatible_presentations() -> None:
    chart = _custom_monitor_component().candidate
    styles = []
    for _ in range(4):
        chart = tui_module._adjust_custom_monitor_chart(chart, "s")
        styles.append(chart.presentation.style)

    assert styles == ["step", "points", "line-points", "ranking"]

def test_custom_monitor_dashboard_context_hides_upper_right_axes_and_stabilizes_zero_values() -> (
    None
):
    component = _custom_monitor_component(total="0")
    terminal = Terminal(80, 16, color=False, ascii=False)

    rendered = tui_custom_rendering._render_custom_monitor(
        component, load_translator("en"), terminal, interval=10
    )

    assert "plotext.figure" not in rendered.chart
    assert "┐" not in rendered.chart
    assert "┘" not in rendered.chart
    assert component.timeline_model(language="en").y_axis_max == 1.0
    assert custom_monitor_y_axis_max([4.2, 4.2]) == 4.2

def test_custom_value_monitor_excludes_cumulative_bars() -> None:
    chart = _custom_monitor_component().candidate
    styles = []
    for _ in range(4):
        chart = tui_module._adjust_custom_monitor_chart(chart, "s", aggregation="value")
        styles.append(chart.presentation.style)

    assert styles == ["step", "points", "line-points", "ranking"]

def test_custom_monitor_window_control_reprojects_without_query_configuration() -> None:
    component = _custom_monitor_component()
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-monitor-window"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    assert ("w", "window") in tui_custom_adjustments._custom_pane_adjustment_bindings(pane, "quick")
    assert tui_module._cycle_custom_monitor_window(3600) == 21600
    candidate = component.candidate
    component.configure_display_window(tui_module._cycle_custom_monitor_window(3600))

    assert component.candidate == candidate

@pytest.mark.parametrize("group_by", (None, "model"))
@pytest.mark.parametrize("step", (1, -1))
@pytest.mark.parametrize("top", (None, 6))
def test_custom_monitor_grouping_cycles_preserve_top_at_group_boundaries(
    group_by, step, top
) -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by=group_by,
        top=top,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "model"), step=step)

    assert (updated.group_by, updated.top) == (
        "model" if group_by is None else None,
        top,
    )

def test_custom_monitor_grouping_cycles_from_total_in_declared_order() -> None:
    component = _custom_monitor_component(grouped=False)
    capability = tui_custom_adjustments._custom_capability_for_component(component)
    assert isinstance(capability, V2MonitorCapability)

    forward = tui_module._cycle_custom_grouping(component.candidate, capability.group_by)
    second = tui_module._cycle_custom_grouping(forward, capability.group_by)
    reverse = tui_module._cycle_custom_grouping(component.candidate, capability.group_by, step=-1)

    assert forward.group_by == "public_model"
    assert second.group_by == "real_model"
    assert reverse.group_by == "real_model"

def test_custom_monitor_attachment_activity_uses_dataset_observation_total() -> None:
    component = _custom_monitor_component(total="90")
    attachment = tui_pane_lifecycle.new_animation_session(
        tui_module.default_animation_spec("monitor"), theme="classic"
    )
    attachment.set_visible(True, 0)
    attachment.set_viable(True, 0)

    tui_module._update_custom_monitor_attachment_activity(
        component,
        attachment,
        now=1,
        wall=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert attachment.playback_requested

    component.accepted_response = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(datetime(2026, 10, 8, 12, 1, tzinfo=UTC), Decimal(), ()),
    )
    tui_module._update_custom_monitor_attachment_activity(
        component,
        attachment,
        now=2,
        wall=datetime(2026, 10, 8, 12, 1, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert not attachment.playback_requested

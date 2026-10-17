from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
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
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomChartCapability,
    CustomFilter,
    CustomFilterOption,
    LocalizedText,
    V2Runtime,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.tui_input import KeyEvent


def test_grouped_ranking_bindings_scope_partition_spacing_and_filters() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        partition_by="logical",
        group_by="real",
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(
            ("day",),
            ("logical", "real", "provider"),
            (),
            partition_by=(None, "logical", "real"),
        )
    )
    component.runtime = V2Runtime(
        filters=(
            CustomFilter(
                "provider",
                LocalizedText("Provider", "提供商"),
                (CustomFilterOption("all", LocalizedText("All", "全部")),),
            ),
        )
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("grouped-controls"),
        SimpleNamespace(),
    )

    quick = dict(tui_custom_adjustments._custom_pane_adjustment_bindings(pane, "quick"))
    advanced = dict(tui_custom_adjustments._custom_pane_adjustment_bindings(pane, "advanced"))
    assert quick["g/G"] == "partition"
    assert quick["s/S"] == "style"
    assert "f" not in quick
    assert advanced["s/S"] == "spacing"
    assert advanced["f"] == "filters"


def test_partition_and_group_cycles_skip_each_other_in_both_directions() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        partition_by="logical",
        group_by="real",
    )
    forward_partition = tui_custom_adjustments._cycle_custom_partitioning(
        chart, (None, "logical", "real"), ("logical", "real", "provider"), step=1
    )
    reverse_partition = tui_custom_adjustments._cycle_custom_partitioning(
        chart, (None, "logical", "real"), ("logical", "real", "provider"), step=-1
    )
    assert (forward_partition.partition_by, forward_partition.group_by) == (None, "real")
    assert (reverse_partition.partition_by, reverse_partition.group_by) == (None, "real")
    assert (
        tui_custom_adjustments._cycle_custom_grouping(
            chart, ("logical", "real", "provider"), step=1
        ).group_by
        == "provider"
    )
    assert (
        tui_custom_adjustments._cycle_custom_grouping(
            chart, ("logical", "real", "provider"), step=-1
        ).group_by
        == "provider"
    )
    assert tui_custom_adjustments._cycle_custom_grouping(chart, ("logical", "real")) == chart
    skipped = tui_custom_adjustments._cycle_custom_partitioning(
        chart, ("logical", "real", "provider"), ("logical", "real", "provider")
    )
    restricted = tui_custom_adjustments._cycle_custom_partitioning(
        chart, ("logical", "real"), ("logical", "real")
    )
    assert (skipped.partition_by, skipped.group_by) == ("provider", "real")
    assert restricted == chart


def test_partition_cycle_atomically_groups_a_flat_ranking_in_both_directions() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )

    forward = tui_custom_adjustments._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "real", "provider"),
        step=1,
    )
    reverse = tui_custom_adjustments._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "real", "provider"),
        step=-1,
    )

    assert (forward.partition_by, forward.group_by, forward.top) == ("logical", "real", 3)
    assert (reverse.partition_by, reverse.group_by, reverse.top) == (
        "real",
        "provider",
        3,
    )


def test_partition_cycle_supports_required_partitions_and_retains_no_legal_pair() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )

    required = tui_custom_adjustments._cycle_custom_partitioning(
        chart, ("logical", "real"), ("logical", "real"), step=1
    )
    restricted = tui_custom_adjustments._cycle_custom_partitioning(
        chart, ("logical",), (None, "logical"), step=1
    )

    assert (required.partition_by, required.group_by) == ("logical", "real")
    assert restricted == chart


def test_partition_cycle_skips_choice_matching_existing_group() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="logical",
    )

    updated = tui_custom_adjustments._cycle_custom_partitioning(
        chart, (None, "logical"), ("logical", "real"), step=1
    )

    assert updated == chart


@pytest.mark.parametrize(
    ("step", "expected"),
    (
        (1, ("logical", "real")),
        (-1, ("real", "logical")),
    ),
    ids=("forward", "reverse"),
)
def test_partition_cycle_recovers_from_stale_non_null_grouping(
    step: int, expected: tuple[str, str]
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="stale",
    )

    updated = tui_custom_adjustments._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "logical", "real"),
        step=step,
    )

    assert (updated.partition_by, updated.group_by) == expected


def test_partition_cycle_preserves_a_legal_current_group_before_catalog_fallback() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="provider",
    )

    updated = tui_custom_adjustments._cycle_custom_partitioning(
        chart, (None, "logical"), ("real", "provider"), step=1
    )

    assert (updated.partition_by, updated.group_by) == ("logical", "provider")


@pytest.mark.parametrize(
    ("key", "partitions", "groupings", "expected", "restricted"),
    (
        ("g", (None, "logical", "real"), (None, "real", "provider"), ("logical", "real"), False),
        ("G", (None, "logical", "real"), (None, "real", "provider"), ("real", "provider"), False),
        ("g", (None, "logical"), (None, "logical"), (None, None), True),
        ("G", (None, "logical"), (None, "logical"), (None, None), True),
    ),
    ids=("forward-refresh", "reverse-refresh", "forward-restricted", "reverse-restricted"),
)
def test_dashboard_partition_interaction_refreshes_or_reports_restriction(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    partitions: tuple[str | None, ...],
    groupings: tuple[str | None, ...],
    expected: tuple[str | None, str | None],
    restricted: bool,
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        metric_titles=("Router", "路由"),
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(("day",), groupings, (), partition_by=partitions)
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(3600, now=tui_rendering.time.monotonic()),
        LifecycleOperation("partition-interaction"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
        probe_complete=True,
    )
    submitted: list[object] = []
    frames: list[str] = []

    class Runtime:
        def submit(self, intent: object) -> object:
            submitted.append(intent)
            raise RuntimeError("stop test submission")

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append("\n".join(frame.rows))  # type: ignore[attr-defined]

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent(key), KeyEvent("\x03")))
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
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
    assert (component.candidate.partition_by, component.candidate.group_by) == expected
    configuration_submissions = [
        intent
        for intent in submitted
        if intent.trigger.value == "refresh"  # type: ignore[attr-defined]
    ]
    assert bool(configuration_submissions) is not restricted
    if restricted:
        message = load_translator("en").text("status.custom_partition_restricted")
        assert any(message in frame for frame in frames)
        assert "Quick settings" in frames[-1]
        assert "Advanced settings" not in frames[-1]


def test_partition_binding_requires_multiple_effective_choices() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="logical",
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(("day",), ("logical",), (), partition_by=(None, "logical"))
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("restricted-partition"),
        SimpleNamespace(),
    )
    assert ("g/G", "partition") not in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "quick"
    )

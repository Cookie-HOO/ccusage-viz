from contextlib import nullcontext
from dataclasses import replace
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
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
import ccusage_viz.tui.structure as tui_structure
from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomData,
    CustomDataset,
    CustomFilter,
    CustomFilterOption,
    CustomUnit,
    LocalizedText,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_protocol.responses import CustomChartResponse
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.tui_input import KeyEvent

from .custom_helpers import _accepted_metric_help_pane, _dashboard_help_frames


@pytest.mark.parametrize("edited", (None, (("source", ("app",)),)), ids=("cancel", "apply"))
def test_dashboard_custom_filter_modal_forces_entry_and_restoration(
    monkeypatch: pytest.MonkeyPatch, edited: object
) -> None:
    pane = _accepted_metric_help_pane()
    choice = CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    )
    pane.component.runtime = V2Runtime((choice,))
    force_flags: list[bool] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, *, force: bool = False, **_kwargs: object) -> None:
            force_flags.append(force)

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))

    def editor(*_args: object, **kwargs: object) -> object:
        kwargs["paint"]("filter body", "filter controls")  # type: ignore[index,operator]
        return edited

    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_structure, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_history, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_input, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pane_events, 'run_custom_filter_editor', editor)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert any(pair == (True, True) for pair in zip(force_flags, force_flags[1:], strict=False)), (
        force_flags
    )

def test_dashboard_custom_filter_timeout_forces_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = _accepted_metric_help_pane()
    choice = CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    )
    pane.component.runtime = V2Runtime((choice,))
    force_flags: list[bool] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, *, force: bool = False, **_kwargs: object) -> None:
            force_flags.append(force)

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_structure, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_history, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_input, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pane_events, 'run_custom_filter_editor', lambda *_args, **_kwargs: (_ for _ in ()).throw(AdjustmentTimeout()))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert force_flags[-1] is True

def test_accepted_custom_metric_help_uses_only_committed_v2_metric() -> None:
    pane = _accepted_metric_help_pane()
    translator = load_translator("en")

    assert tui_custom_adjustments._accepted_custom_metric_help_node(pane, translator) == (
        translator.text("status.tui_help_current_metric"),
        (("Stars", (("Total GitHub stars", ()),)),),
    )

@pytest.mark.parametrize("missing", ("accepted_config", "v1", "metric"))
def test_accepted_custom_metric_help_omits_unusable_metadata(missing: str) -> None:
    pane = _accepted_metric_help_pane()
    if missing == "accepted_config":
        pane.component.accepted_config = None
    elif missing == "v1":
        pane.component.v2_descriptor = SimpleNamespace(metrics=())
    else:
        assert pane.component.accepted_config is not None
        pane.component.accepted_config = replace(
            pane.component.accepted_config, metric_id="missing"
        )

    assert tui_custom_adjustments._accepted_custom_metric_help_node(pane, load_translator("en")) is None

def test_accepted_custom_metric_help_is_localized() -> None:
    assert tui_custom_adjustments._accepted_custom_metric_help_node(
        _accepted_metric_help_pane(), load_translator("zh")
    ) == ("当前指标", (("星标", (("GitHub 星标总数", ()),)),))

def test_dashboard_help_overlay_shows_committed_localized_v2_metric_and_omits_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v2_help = _dashboard_help_frames(
        monkeypatch, _accepted_metric_help_pane(), language="zh", width=80
    )

    assert "当前指标" in v2_help
    assert "星标" in v2_help
    assert "GitHub 星标总数" in v2_help
    visible_lines = [strip_ansi(line) for line in v2_help.splitlines()]
    current_metric_index = next(
        index for index, line in enumerate(visible_lines) if line.strip(" |") == "当前指标"
    )
    controls_index = next(
        index for index, line in enumerate(visible_lines) if line.strip(" |") == "操作"
    )
    assert current_metric_index < controls_index
    assert "当前 Pane 没有可调整参数" not in v2_help

    pane = _accepted_metric_help_pane()
    assert pane.component.apply_provider_result(
        SimpleNamespace(
            custom_response=CustomChartResponse(
                CustomDataset(
                    LocalizedText("Dataset", "数据集"),
                    LocalizedText("Daily", "每日"),
                    CustomUnit("count", LocalizedText("Dataset", "数据集"), "suffix", 0),
                ),
                CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
                CustomData(()),
            )
        )
    )
    assert pane.component.v2_descriptor is None
    v1_help = _dashboard_help_frames(monkeypatch, pane, language="zh", width=80)

    assert "当前指标" not in v1_help
    assert "星标" not in v1_help

def test_dashboard_help_overlay_wraps_metric_description_at_tree_continuation_indent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = _accepted_metric_help_pane()
    assert isinstance(pane.component.v2_descriptor, V2ProbeDescriptor)
    metric = pane.component.v2_descriptor.metrics[0]
    pane.component.v2_descriptor = replace(
        pane.component.v2_descriptor,
        metrics=(
            replace(
                metric,
                description=LocalizedText(
                    "A description long enough to wrap through the current Metric tree node.",
                    "A description long enough to wrap through the current Metric tree node.",
                ),
            ),
            *pane.component.v2_descriptor.metrics[1:],
        ),
    )
    lines = [
        strip_ansi(line)
        for line in _dashboard_help_frames(monkeypatch, pane, language="en", width=44).splitlines()
    ]
    first = next(index for index, line in enumerate(lines) if "A description long" in line)

    assert "└─ A description long" in lines[first]
    continuation = next(line for line in lines[first + 1 :] if "through the" in line)
    assert continuation.index("through the") == lines[first].index("A description long") + 3

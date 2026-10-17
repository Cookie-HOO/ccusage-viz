import os
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
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
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import EmptyPaneConfig
from ccusage_viz.tui_input import KeyEvent


@pytest.mark.parametrize("ordinary_paint", ["none", "interaction", "resize"])
def test_animation_ticks_reuse_static_pane(
    monkeypatch: pytest.MonkeyPatch,
    ordinary_paint: str,
) -> None:
    translator = load_translator("en")
    launch = _to_options(
        build_parser(translator).parse_args(
            [
                "dashboard",
                "--demo",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
                "--pane",
                "animate rain",
                "--pane",
                "animate rain",
            ]
        )
    )
    launch = replace(launch, panes=(*launch.panes, EmptyPaneConfig()))
    now = [100.0]
    calls: list[list[float]] = [[], [], []]
    frames: list[object] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    def render(pane: tui_rendering.TuiPane, *_args: object, **_kwargs: object) -> tui_models.PaneRender:
        index = pane.pane_id
        calls[index].append(now[0])
        if isinstance(pane, tui_models.TuiAnimationPane):
            # One animation is fast, the other is not due during the test.
            pane.session.next_deadline = now[0] + (1 if index == 0 else 60)
        return tui_models.PaneRender(f"pane {index} at {now[0]}")

    reads = [0]

    def read(_decoder: object, _timeout: float) -> KeyEvent | None:
        reads[0] += 1
        now[0] += 1
        if reads[0] == 3 and ordinary_paint == "interaction":
            return KeyEvent("m")
        if reads[0] == 5:
            return KeyEvent("\x03")
        return None

    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', read)
    monkeypatch.setattr(tui_input, 'read_event', read)
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', read)
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', read)
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: os.terminal_size((180 if ordinary_paint == 'resize' and reads[0] >= 3 else 160, 40)))
    monkeypatch.setattr(tui_rendering.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tui_rendering, '_pane_render', render)
    monkeypatch.setattr(tui_painting, '_pane_render', render)

    assert tui_runtime.run_tui(launch, translator) == 0
    assert len(calls[0]) >= 4
    assert len(calls[1]) == len(calls[2]) == (1 if ordinary_paint == "none" else 2)
    assert len(frames) >= 4


@pytest.mark.parametrize("kind", [tui_models.TuiChartPane, tui_models.TuiCustomPane])
def test_attachment_deadline_respects_pane_body_view(kind: type) -> None:
    # Isolate scheduling from query-backed component construction.
    pane = object.__new__(kind)
    pane.body_view = "chart"
    pane.attachment = SimpleNamespace(next_deadline=123.0)
    assert tui_rendering._pane_animation_deadline(pane) == 123.0
    pane.body_view = "command"
    assert tui_rendering._pane_animation_deadline(pane) is None
    pane.body_view = "chart"
    pane.attachment = None
    assert tui_rendering._pane_animation_deadline(pane) is None


def test_animation_overlay_can_wake_before_next_scene_frame() -> None:
    pane = object.__new__(tui_models.TuiAnimationPane)
    pane.body_view = "chart"
    pane.session = SimpleNamespace(next_deadline=200.0)
    pane.overlay = SimpleNamespace(next_due=150.0)
    assert tui_rendering._pane_animation_deadline(pane) == 150.0
    pane.body_view = "command"
    assert tui_rendering._pane_animation_deadline(pane) is None

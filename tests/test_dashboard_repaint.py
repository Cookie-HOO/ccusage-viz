import os
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

import ccusage_viz.tui as tui
from ccusage_viz.cli import _to_options, build_parser
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

    def render(pane: tui.TuiPane, *_args: object, **_kwargs: object) -> tui.PaneRender:
        index = pane.pane_id
        calls[index].append(now[0])
        if isinstance(pane, tui.TuiAnimationPane):
            # One animation is fast, the other is not due during the test.
            pane.session.next_deadline = now[0] + (1 if index == 0 else 60)
        return tui.PaneRender(f"pane {index} at {now[0]}")

    reads = [0]

    def read(_decoder: object, _timeout: float) -> KeyEvent | None:
        reads[0] += 1
        now[0] += 1
        if reads[0] == 3 and ordinary_paint == "interaction":
            return KeyEvent("m")
        if reads[0] == 5:
            return KeyEvent("\x03")
        return None

    monkeypatch.setattr(tui, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui, "FramePainter", Screen)
    monkeypatch.setattr(tui, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui, "read_event", read)
    monkeypatch.setattr(
        tui,
        "get_terminal_size",
        lambda: os.terminal_size(
            (180 if ordinary_paint == "resize" and reads[0] >= 3 else 160, 40)
        ),
    )
    monkeypatch.setattr(tui.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tui, "_pane_render", render)

    assert tui.run_tui(launch, translator) == 0
    assert len(calls[0]) >= 4
    assert len(calls[1]) == len(calls[2]) == (1 if ordinary_paint == "none" else 2)
    assert len(frames) >= 4


@pytest.mark.parametrize("kind", [tui.TuiChartPane, tui.TuiCustomPane])
def test_attachment_deadline_respects_pane_body_view(kind: type) -> None:
    # Isolate scheduling from query-backed component construction.
    pane = object.__new__(kind)
    pane.body_view = "chart"
    pane.attachment = SimpleNamespace(next_deadline=123.0)
    assert tui._pane_animation_deadline(pane) == 123.0
    pane.body_view = "command"
    assert tui._pane_animation_deadline(pane) is None
    pane.body_view = "chart"
    pane.attachment = None
    assert tui._pane_animation_deadline(pane) is None


def test_animation_overlay_can_wake_before_next_scene_frame() -> None:
    pane = object.__new__(tui.TuiAnimationPane)
    pane.body_view = "chart"
    pane.session = SimpleNamespace(next_deadline=200.0)
    pane.overlay = SimpleNamespace(next_due=150.0)
    assert tui._pane_animation_deadline(pane) == 150.0
    pane.body_view = "command"
    assert tui._pane_animation_deadline(pane) is None

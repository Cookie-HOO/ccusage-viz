from contextlib import nullcontext
from dataclasses import replace
from os import terminal_size
from time import monotonic

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
import ccusage_viz.tui.layout as tui_layout
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
import ccusage_viz.tui.structure as tui_structure
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import ProcessConfig
from ccusage_viz.tui_input import InputDecoder
from tests.ranking_scroll.helpers import projection


@pytest.fixture
def dashboard(monkeypatch):
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            [
                "dashboard",
                "--empty",
                "--grid",
                "1x2",
                "--pane",
                "empty",
                "--pane",
                "empty",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
            ]
        )
    )
    panes = []
    for index in range(2):
        model = projection(100)
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        component = CustomHistoricalComponent(config)
        component.model = replace(model, config=config)
        component.accepted_config = config
        component.pending_generation = None
        pane = tui_models.TuiCustomPane(
            component,
            FixedIntervalScheduler(3600, now=monotonic()),
            LifecycleOperation(f"scroll-test-{index}"),
            ProcessConfig(),
            probe_complete=True,
        )
        panes.append(pane)
    frames = []
    focuses = []
    geometries = []
    requests = []
    copied = []
    opened = []
    decoder = InputDecoder()
    size = [160, 30]

    class Screen:
        def __init__(self, stream):
            pass

        def paint(self, frame, **kwargs):
            frames.append(frame)

        def finish(self):
            pass

    def request(self, trigger, **kwargs):
        requests.append((self, trigger))
        # Accept data before entering the loop; only startup is stubbed.
        assert trigger == LifecycleTrigger.STARTUP, "wheel input must not request work"
        return False

    original_compose = tui_painting._compose_resolved_panes

    def compose(contents, layout, **kwargs):
        focuses.append(kwargs["focused"])
        geometries.append(layout)
        return original_compose(contents, layout, **kwargs)

    original_new_pane = tui_session._new_pane
    supplied = iter(panes)
    monkeypatch.setattr(tui_pane_lifecycle, '_new_pane', lambda *args, **kwargs: next(supplied))
    monkeypatch.setattr(tui_session, '_new_pane', lambda *args, **kwargs: next(supplied))
    monkeypatch.setattr(tui_structure, '_new_pane', lambda *args, **kwargs: next(supplied))
    monkeypatch.setattr(tui_history, '_new_pane', lambda *args, **kwargs: next(supplied))
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_layout, '_compose_resolved_panes', compose)
    monkeypatch.setattr(tui_painting, '_compose_resolved_panes', compose)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', lambda: nullcontext(decoder))
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: terminal_size(size))
    monkeypatch.setattr(LifecycleOperation, "request", request)
    monkeypatch.setattr(tui_events, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_pointer, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_pane_events, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_datasets_chooser, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_datasets_modal, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_pointer, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_datasets_chooser, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_datasets_modal, 'copy_command', lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui_pointer.webbrowser, "open", lambda url: opened.append(url) or True)

    def run(events):
        turns = iter(events)

        def read(decoder, timeout):
            event = next(turns)
            return event() if callable(event) else event

        monkeypatch.setattr(tui_adjustments, 'read_event', read)
        monkeypatch.setattr(tui_input, 'read_event', read)
        monkeypatch.setattr(tui_datasets_catalog, 'read_event', read)
        monkeypatch.setattr(tui_datasets_chooser, 'read_event', read)
        assert tui_runtime.run_tui(run.options, load_translator("en")) == 0
        assert len(requests) == run.expected_requests

    run.options = options
    run.expected_requests = 2
    run.monkeypatch = monkeypatch
    run.new_pane = original_new_pane
    return run, panes, frames, focuses, geometries, decoder, copied, opened, size

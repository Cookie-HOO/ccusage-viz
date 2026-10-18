from concurrent.futures import Future
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
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2ProbeDescriptor,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.tui.header import _custom_dashboard_sources
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui_input import KeyEvent


def test_dashboard_dataset_availability_names_missing_environment() -> None:
    status = SimpleNamespace(
        availability="setup_required",
        missing_environment=(SimpleNamespace(name="WEREAD_COOKIE"),),
    )

    assert (
        tui_datasets_modal._dataset_registration_availability(status, load_translator("en"))
        == "Setup required: WEREAD_COOKIE"
    )
    assert (
        tui_datasets_modal._dataset_registration_availability(status, load_translator("zh"))
        == "需要配置：WEREAD_COOKIE"
    )


def test_run_tui_dashboard_dataset_entry_keeps_installed_titles_in_source_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_title = "Fake Installed Dataset"
    text = LocalizedText(fake_title, "伪安装数据集")
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (), ())
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="fake-installed", probe=SimpleNamespace(descriptor=descriptor)
        )
    )
    frames_by_stage: dict[str, str] = {}
    modals: list[object] = []
    original_modal = tui_datasets_modal.DashboardDatasetModalState

    def record_modal(*args: object, **kwargs: object) -> object:
        modal = original_modal(*args, **kwargs)
        modals.append(modal)
        return modal

    class Runtime:
        def cancel(self) -> None:
            pass

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            if modals:
                stage = str(modals[-1].stage)  # type: ignore[union-attr]
                rendered = "\n".join(frame.rows)  # type: ignore[union-attr]
                if (
                    stage == "pane"
                    and all(heading in rendered for heading in ("ccusage", "Custom", "Other"))
                ) or (stage == "source" and fake_title in rendered):
                    frames_by_stage.setdefault(stage, rendered)

        def finish(self) -> None:
            pass

    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            *(KeyEvent("j") for _ in range(5)),
            KeyEvent("\r"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--grid", "1x1", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_models, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_session, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_datasets_modal, "DashboardDatasetModalState", record_modal)
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
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0

    pane_frame = frames_by_stage["pane"]
    headings = ("ccusage", "Custom", "Other")
    assert tuple(sorted(headings, key=pane_frame.index)) == headings
    assert all(pane_frame.count(heading) == 1 for heading in headings)
    assert (
        pane_frame.index("Timeline") < pane_frame.index("Datasets…") < pane_frame.index("Animation")
    )
    assert fake_title not in pane_frame

    source_frame = frames_by_stage["source"]
    assert fake_title in source_frame


def test_dashboard_custom_sources_choose_first_pane_for_each_dataset_id() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    source = CustomCommandSource("reading", ("reader", "ccuv"))
    panes = [
        _new_pane(
            dashboard,
            default_custom_pane("timeline", source=source, dashboard=dashboard),
            f"dashboard:pane:{index}",
            build_query_runtime(),
        )
        for index in range(2)
    ]

    assert _custom_dashboard_sources(panes) == (tui_models.CustomDashboardSource(source),)

    panes[1].component.configure(
        replace(panes[1].component.candidate, source=CustomCommandSource("reading", ("other",))),
        data_affecting=True,
    )

    assert _custom_dashboard_sources(panes) == (tui_models.CustomDashboardSource(source),)


def test_dashboard_dataset_chooser_keeps_empty_v2_metric_list_in_source_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a V2 Dataset without Metrics must not open an invalid chooser."""

    text = LocalizedText("Dataset", "数据集")
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (), ())
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )
    frames: list[object] = []

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, _intent: object) -> FailedHandle:
            return FailedHandle()

        def cancel(self) -> None:
            pass

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def refresh(self, _dataset_id: str) -> object:
            return status

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    class ImmediateExecutor:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def submit(self, function: object, *args: object) -> Future[object]:
            future: Future[object] = Future()
            try:
                future.set_result(function(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future

        def shutdown(self, **_kwargs: object) -> None:
            pass

    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            *(KeyEvent("j") for _ in range(5)),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("j"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_session, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_datasets_catalog, "ThreadPoolExecutor", ImmediateExecutor)
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
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert "Unavailable" in rendered
    assert "Choose a metric" not in rendered


@pytest.mark.parametrize(
    ("terminal_height", "up_keys"),
    ((20, 2), (40, 1)),
    ids=("hidden_heading_revealed_before_wrap", "visible_heading_wraps_immediately"),
)
def test_dashboard_metric_chooser_up_reveals_hidden_group_heading_before_wrapping(
    monkeypatch: pytest.MonkeyPatch,
    terminal_height: int,
    up_keys: int,
) -> None:
    """Up reveals a clipped first group heading before wrapping Metric selection."""

    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier.title(), identifier),
            LocalizedText(
                "A deliberately long description that wraps onto multiple chooser rows.",
                "description",
            ),
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"ranking": tui_models.V2HistoricalChartCapability(("day",), (None,), ())}
            ),
            {},
            group_id="github",
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric("stars"), metric("forks")),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )
    frames: list[object] = []

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, _intent: object) -> FailedHandle:
            return FailedHandle()

        def cancel(self) -> None:
            pass

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def refresh(self, _dataset_id: str) -> object:
            return status

    class ImmediateExecutor:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def submit(self, function: object, *args: object) -> Future[object]:
            future: Future[object] = Future()
            try:
                future.set_result(function(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future

        def shutdown(self, **_kwargs: object) -> None:
            pass

    original_modal = tui_datasets_modal.DashboardDatasetModalState
    modals: list[object] = []
    boundaries: list[tuple[str, tuple[str, int, int], str]] = []

    def record_modal(*args: object, **kwargs: object) -> object:
        modal = original_modal(*args, **kwargs)
        modals.append(modal)
        return modal

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            *(KeyEvent("j") for _ in range(5)),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("j"),
            KeyEvent("k"),
            *(KeyEvent("\x1b[A") for _ in range(up_keys)),
            KeyEvent(" "),
            KeyEvent("\x03"),
        )
    )

    def read_dashboard_event(_decoder: object, _timeout: object) -> KeyEvent:
        event = next(events)
        modal = modals[-1] if modals else None
        if modal is not None and modal.stage == "metric":
            boundaries.append(
                (event.value, (modal.stage, modal.index, modal.offset), "\n".join(frames[-1].rows))
            )
        return event

    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_session, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_datasets_catalog, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_models, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_session, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_datasets_modal, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", read_dashboard_event)
    monkeypatch.setattr(tui_input, "read_event", read_dashboard_event)
    monkeypatch.setattr(tui_datasets_catalog, "read_event", read_dashboard_event)
    monkeypatch.setattr(tui_datasets_chooser, "read_event", read_dashboard_event)
    monkeypatch.setattr(
        tui_events,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_runtime,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_painting,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_dashboard_events,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_pointer,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_pane_events,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, terminal_height))
    )
    monkeypatch.setattr(
        tui_history,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_catalog,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_chooser,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_modal,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_painting,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_pointer,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, terminal_height))
    )
    monkeypatch.setattr(
        tui_history,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_catalog,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_chooser,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr(
        tui_datasets_modal,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((80, terminal_height)),
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    up_boundaries = [boundary for boundary in boundaries if boundary[0] == "\x1b[A"][-up_keys:]
    assert up_boundaries

    if terminal_height == 20:
        _first_key, initial_state, _initial_frame = up_boundaries[0]
        _second_key, revealed_state, revealed_frame = up_boundaries[1]
        assert initial_state == ("metric", 0, 1)
        assert revealed_state == ("metric", 0, 0)
        assert "GitHub" in revealed_frame
        assert "› ├─ Stars" in revealed_frame
        assert boundaries[-1][1][0:2] == ("metric", 1)
    else:
        _key, initial_state, _frame = up_boundaries[0]
        assert initial_state == ("metric", 0, 0)
        assert boundaries[-1][1][0:2] == ("metric", 1)


def test_dashboard_dataset_chooser_refreshed_v1_without_chart_kinds_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    dataset = CustomDataset(text, text, CustomUnit("count", text, "suffix", 0))
    stale_descriptor = CustomProbeDescriptor(
        "revision",
        "1",
        dataset,
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        {},
        (),
    )
    refreshed_descriptor = CustomProbeDescriptor(
        "revision", "2", dataset, CustomCapabilities((), (), {}), {}, ()
    )
    stale = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=stale_descriptor)
        )
    )
    refreshed = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=refreshed_descriptor)
        )
    )
    frames: list[object] = []
    modals: list[object] = []
    original_modal = tui_datasets_modal.DashboardDatasetModalState

    def record_modal(*args: object, **kwargs: object) -> object:
        modal = original_modal(*args, **kwargs)
        modals.append(modal)
        return modal

    class Runtime:
        def submit(self, _intent: object) -> object:
            return SimpleNamespace(result=lambda: None, cancel=lambda: None)

        def cancel(self) -> None:
            pass

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (stale,)

        def refresh(self, _dataset_id: str) -> object:
            return refreshed

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    class ImmediateExecutor:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def submit(self, function: object, *args: object) -> Future[object]:
            future: Future[object] = Future()
            future.set_result(function(*args))
            return future

        def shutdown(self, **_kwargs: object) -> None:
            pass

    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            *(KeyEvent("j") for _ in range(5)),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("j"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_models, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_session, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_datasets_modal, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_session, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_datasets_catalog, "ThreadPoolExecutor", ImmediateExecutor)
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
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert "Unavailable" in rendered
    assert modals[-1].stage == "source"
    assert modals[-1].chart_kinds == ()
    assert modals[-1].statuses == (refreshed,)

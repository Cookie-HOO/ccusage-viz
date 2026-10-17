


from concurrent.futures import Future
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
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
    V2ProbeDescriptor,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.tui_input import KeyEvent


def test_dashboard_dataset_chooser_hot_probes_fresh_v2_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def descriptor(*metric_ids: str) -> V2ProbeDescriptor:
        metrics = tuple(
            V2MetricDescriptor(
                metric_id,
                LocalizedText(metric_id, metric_id),
                text,
                unit,
                "sum",
                V2MetricCapabilities((), (), {}),
                {},
            )
            for metric_id in metric_ids
        )
        return V2ProbeDescriptor("revision", "1", V2Dataset(text, text), metrics, ())

    stale = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor("old"))
        )
    )
    refreshed = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor("old", "new"))
        )
    )
    refresh_calls: list[str] = []
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
            return (stale,)

        def refresh(self, dataset_id: str) -> object:
            refresh_calls.append(dataset_id)
            return refreshed

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
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert refresh_calls == ["dataset"]
    assert "old" in rendered
    assert "new" in rendered

def test_dashboard_dataset_chooser_hot_probe_failure_stays_in_source_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (), ())
    status = SimpleNamespace(
        registration=SimpleNamespace(dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor))
    )
    refresh_calls: list[str] = []
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

        def refresh(self, dataset_id: str) -> object:
            refresh_calls.append(dataset_id)
            raise QueryError("error.custom_command_protocol", detail="bad response")

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
            KeyEvent("j"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert refresh_calls == ["dataset"]
    assert "bad response" in rendered
    assert "error.custom_command_protocol" not in rendered
    assert "Choose a metric" not in rendered

def test_dashboard_dataset_chooser_rejects_hot_probe_with_mismatched_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (), ())
    selected = SimpleNamespace(
        registration=SimpleNamespace(dataset_id="selected", probe=SimpleNamespace(descriptor=descriptor))
    )
    mismatched = SimpleNamespace(
        registration=SimpleNamespace(dataset_id="other", probe=SimpleNamespace(descriptor=descriptor))
    )
    frames: list[object] = []
    modals: list[object] = []
    original_modal = tui_module.DashboardDatasetModalState

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
            return (selected,)

        def refresh(self, _dataset_id: str) -> object:
            return mismatched

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
            KeyEvent("j"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_module, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert modals[-1].stage == "source"
    assert modals[-1].error == "Dataset selected is corrupt and cannot be executed."
    assert "Choose a metric" not in rendered

def test_dashboard_dataset_chooser_v1_hot_probe_enters_kind_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    dataset = CustomDataset(text, text, CustomUnit("count", text, "suffix", 0))
    descriptor = CustomProbeDescriptor(
        "revision", "1", dataset, CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}), {}, ()
    )
    status = SimpleNamespace(registration=SimpleNamespace(dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)))
    frames: list[object] = []

    class Runtime:
        def submit(self, _intent: object) -> object:
            return SimpleNamespace(result=lambda: None, cancel=lambda: None)

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
            KeyEvent("j"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert "Timeline" in "\n".join("\n".join(frame.rows) for frame in frames)

def test_dashboard_dataset_hot_probe_escape_ignores_stale_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def descriptor(metric_id: str) -> V2ProbeDescriptor:
        metric = V2MetricDescriptor(
            metric_id, LocalizedText(metric_id, metric_id), text, unit, "sum",
            V2MetricCapabilities((), (), {}), {},
        )
        return V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (metric,), ())

    original = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor("old"))
        )
    )
    stale = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor("new"))
        )
    )
    modals: list[object] = []
    original_modal = tui_module.DashboardDatasetModalState

    def record_modal(*args: object, **kwargs: object) -> object:
        modal = original_modal(*args, **kwargs)
        modals.append(modal)
        return modal

    class PendingFuture:
        def __init__(self) -> None:
            self.complete = False
            self.cancelled = False

        def done(self) -> bool:
            return self.complete

        def result(self) -> object:
            return stale

        def cancel(self) -> None:
            self.cancelled = True

    pending = PendingFuture()

    class Runtime:
        def submit(self, _intent: object) -> object:
            return SimpleNamespace(result=lambda: None, cancel=lambda: None)

        def cancel(self) -> None:
            pass

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (original,)

        def refresh(self, _dataset_id: str) -> object:
            return stale

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            pass

    class PendingExecutor:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def submit(self, _function: object, *_args: object) -> PendingFuture:
            return pending

        def shutdown(self, **_kwargs: object) -> None:
            pass

    events = iter((
        KeyEvent("m"), KeyEvent("r"), *(KeyEvent("j") for _ in range(5)), KeyEvent("\r"), KeyEvent("\r"),
        KeyEvent("\x1b"), KeyEvent("j"), KeyEvent("\x03"),
    ))

    def read_event(_decoder: object, _timeout: object) -> object:
        event = next(events)
        if (
            event == KeyEvent("j")
            and modals
            and modals[-1].stage == "source"
        ):
            pending.complete = True
        return event

    options = _to_options(build_parser(load_translator("en")).parse_args(
        ["dashboard", "--empty", "--header-style", "hidden"]
    ))
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_module, "ThreadPoolExecutor", PendingExecutor)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_event)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert pending.cancelled
    assert modals[-1].stage == "source"
    assert modals[-1].statuses == (original,)
    assert modals[-1].future is None

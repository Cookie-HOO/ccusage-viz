
from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.datasets.chooser as tui_chooser
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.custom_models import (
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2ProbeDescriptor,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.tui_input import InputDecoder, KeyEvent


def test_metric_chooser_previous_offset_reveals_hidden_first_group_heading() -> None:
    rows = (
        tui_models.MetricChooserRow("group", "GitHub"),
        tui_models.MetricChooserRow("metric", "├─ Stars", 0),
        tui_models.MetricChooserRow("description", "│  └─ Star count"),
        tui_models.MetricChooserRow("metric", "└─ Forks", 1),
    )

    assert tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=1) == 0
    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=0) is None
    )
    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=1, offset=1) is None
    )

def test_metric_chooser_previous_offset_requires_immediate_predecessor_hidden() -> None:
    rows = (
        tui_models.MetricChooserRow("group", "GitHub"),
        tui_models.MetricChooserRow("description", "Repository metrics"),
        tui_models.MetricChooserRow("metric", "├─ Stars", 0),
        tui_models.MetricChooserRow("description", "│  └─ Star count"),
        tui_models.MetricChooserRow("metric", "└─ Forks", 1),
    )

    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=1) is None
    )

def test_metric_chooser_display_rows_use_ascii_connectors_and_wrap_descriptions() -> None:
    rows = (
        tui_models.MetricChooserRow("group", "GitHub"),
        tui_models.MetricChooserRow("metric", "├─ Stars", 0),
        tui_models.MetricChooserRow(
            "description", "│  └─ A deliberately long metric description for narrow terminals"
        ),
        tui_models.MetricChooserRow("metric", "└─ Forks", 1),
        tui_models.MetricChooserRow(
            "description", "   └─ Another deliberately long description for the viewport"
        ),
    )

    displayed = tui_module._metric_chooser_display_rows(rows, width=20, ascii=True)
    choices = [f"{'>' if row.metric_index == 1 else ' '} {row.text}" for row in displayed]
    body, offset = tui_module._chooser_viewport(
        choices,
        index=next(index for index, row in enumerate(displayed) if row.metric_index == 1),
        offset=0,
        height=5,
        reserved_rows=2,
    )

    assert all(display_width(row.text) <= 18 for row in displayed)
    assert all(display_width(choice) <= 20 for choice in choices)
    assert any("|- Stars" in choice for choice in choices)
    assert "|  \\- " in "\n".join(choices)
    assert "   \\- " in "\n".join(choices)
    assert "├" not in "\n".join(choices)
    assert body.splitlines()[-1].startswith("> \\- Forks")
    assert offset == next(index for index, row in enumerate(displayed) if row.metric_index == 1) - 2

def test_standalone_metric_chooser_uses_ascii_host_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    metric = V2MetricDescriptor(
        "stars",
        LocalizedText("Stars", "星标"),
        LocalizedText("Long description for ASCII chooser output", "描述"),
        CustomUnit("count", text, "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (), (), {"ranking": tui_models.V2HistoricalChartCapability(("day",), (None,), ())}
        ),
        {},
        group_id="github",
    )
    forks = replace(metric, id="forks", title=LocalizedText("Forks", "分支"))
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric, forks),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    bodies: list[str] = []
    events = iter((KeyEvent("\r"), KeyEvent("j"), KeyEvent("\r"), KeyEvent("\r")))

    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty", "--ascii"])
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(
        tui_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((20, 24))
    )

    config = tui_module._choose_dataset_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=8,
        dashboard=dashboard,
        paint_choices=lambda body, *_args: bodies.append(body),
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.metric_id == "forks"
    metric_body = next(body for body in bodies if "Stars" in body)
    assert "\\- Long" in metric_body
    assert "└" not in metric_body
    assert "\x1b[1mGitHub\x1b[0m" in metric_body
    assert "\x1b[2m|  \\- Long descrip\x1b[0m" in metric_body

@pytest.mark.parametrize(
    ("height", "up_keys"),
    ((6, 2), (20, 1)),
    ids=("hidden_heading_revealed_before_wrap", "visible_heading_wraps_immediately"),
)
def test_standalone_metric_chooser_up_reveals_hidden_group_heading_before_wrapping(
    monkeypatch: pytest.MonkeyPatch, height: int, up_keys: int
) -> None:
    """The blocking chooser reveals its clipped heading before it wraps selection."""

    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier.title(), identifier),
            text,
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

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    bodies: list[str] = []
    navigation = (KeyEvent("j"), KeyEvent("k")) if height == 6 else ()
    events = iter(
        (
            KeyEvent("\r"),
            *navigation,
            *(KeyEvent("\x1b[A") for _ in range(up_keys)),
            KeyEvent("\r"),
            KeyEvent("\r"),
        )
    )
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )

    config = tui_module._choose_dataset_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=height,
        dashboard=dashboard,
        paint_choices=lambda body, *_args: bodies.append(body),
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.metric_id == "forks"
    metric_bodies = [body for body in bodies if "Choose a metric" in body]
    if height == 6:
        # Down then Up leaves the first Metric selected while its heading is clipped.
        assert "› ├─ Stars" in metric_bodies[2]
        assert "GitHub" not in metric_bodies[2]
        # The first Up is viewport-only; the second wraps to the final Metric.
        assert "GitHub" in metric_bodies[3]
        assert "› ├─ Stars" in metric_bodies[3]
        assert "› └─ Forks" in metric_bodies[4]
    else:
        assert "GitHub" in metric_bodies[0]
        assert "› ├─ Stars" in metric_bodies[0]
        assert "› └─ Forks" in metric_bodies[1]

def test_dashboard_metric_modal_wraps_to_target_pane_and_submits_selected_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live Dashboard modal uses its pane width and navigates metric rows only."""

    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, description: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier.title(), identifier),
            LocalizedText(description, description),
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
        (
            metric(
                "stars", "A deliberately long description that must wrap inside this narrow pane."
            ),
            metric(
                "forks", "Another deliberately long description that must not become selectable."
            ),
        ),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )
    submitted: list[str | None] = []
    frames: list[object] = []

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def refresh(self, _dataset_id: str) -> object:
            return status

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

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

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    original_default_custom_pane = tui_module.default_custom_pane

    def record_default_custom_pane(*args: object, **kwargs: object) -> object:
        submitted.append(kwargs.get("metric_id"))
        return original_default_custom_pane(*args, **kwargs)

    # Enter pane management, open Dataset chooser, select Datasets, then drive
    # the live metric modal with j/Enter before accepting its chart kind.
    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            KeyEvent("k"),
            KeyEvent("k"),
            KeyEvent("k"),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("j"),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(tui_module, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", __import__("contextlib").nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((44, 20))
    )
    monkeypatch.setattr(tui_module, "default_custom_pane", record_default_custom_pane)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert submitted == ["forks"]

    metric_frames = [
        "\n".join(frame.rows) for frame in frames if "rrow pane." in "\n".join(frame.rows)
    ]
    assert metric_frames
    # Pane zero is framed and its interior is 20 columns wide at this terminal
    # size.  The visible wrapped description reaches its frame boundary without
    # leaking into the adjacent pane.
    metric_lines = [
        strip_ansi(line)
        for line in metric_frames[-1].splitlines()
        if "rrow pane." in strip_ansi(line)
    ]
    assert metric_lines
    assert all(display_width(line[:22]) == 22 and line[21] == "│" for line in metric_lines)

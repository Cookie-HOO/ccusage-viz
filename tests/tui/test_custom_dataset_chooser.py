











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
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.tui.datasets.chooser import _choose_custom_pane_config
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent


def test_dataset_metric_chooser_groups_declared_metrics_and_keeps_ungrouped_flat() -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, group_id: str | None = None) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier, f"{identifier}-zh"),
            text,
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"ranking": tui_models.V2HistoricalChartCapability(("day",), (None,), ())}
            ),
            {},
            group_id=group_id,
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric("stars", "github"), metric("updated", "github"), metric("legacy")),
        (),
        metric_groups=(
            V2MetricGroup("github", LocalizedText("GitHub tools", "GitHub 工具")),
            V2MetricGroup("empty", LocalizedText("Empty", "空")),
        ),
    )

    rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("en"))

    assert [(row.kind, row.text, row.metric_index) for row in rows] == [
        ("group", "GitHub tools", None),
        ("metric", "├─ stars", 0),
        ("description", "│  └─ Dataset", None),
        ("metric", "└─ updated", 1),
        ("description", "   └─ Dataset", None),
        ("metric", "legacy", 2),
        ("description", "  └─ Dataset", None),
    ]

    chinese_rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("zh"))
    assert [(row.text, row.metric_index) for row in chinese_rows] == [
        ("GitHub 工具", None),
        ("├─ stars-zh", 0),
        ("│  └─ 数据集", None),
        ("└─ updated-zh", 1),
        ("   └─ 数据集", None),
        ("legacy-zh", 2),
        ("  └─ 数据集", None),
    ]

def test_dataset_metric_chooser_keeps_legacy_descriptor_flat() -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)
    metric = V2MetricDescriptor(
        "stars",
        LocalizedText("Stars", "Star"),
        text,
        unit,
        "sum",
        V2MetricCapabilities(
            (), (), {"ranking": tui_models.V2HistoricalChartCapability(("day",), (None,), ())}
        ),
        {},
    )
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (metric,), ())

    rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("en"))

    assert [(row.kind, row.text, row.metric_index) for row in rows] == [
        ("metric", "Stars", 0),
        ("description", "  └─ Dataset", None),
    ]

def test_dataset_metric_chooser_titles_the_selected_dataset() -> None:
    text = LocalizedText("Large Model Routing", "大模型路由")
    metric = V2MetricDescriptor(
        "tokens",
        LocalizedText("TPM", "TPM"),
        text,
        CustomUnit("token", text, "suffix", 0),
        "sum",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
        {},
    )
    descriptor = V2ProbeDescriptor("router-live-v1", "0.1.0", V2Dataset(text, text), (metric,), ())

    chrome = tui_module._dataset_metric_chooser_chrome(descriptor, load_translator("zh"))

    assert chrome == ("数据集：大模型路由 · 0.1.0", "选择一个指标")

def test_dataset_source_chooser_uses_the_non_parameterized_title() -> None:
    assert load_translator("zh").text("status.dataset_chooser_title") == "数据集"

def test_custom_pane_chooser_builds_a_source_config_and_rejects_invalid_drafts() -> None:
    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    events = iter(
        (
            KeyEvent("\t"),
            PasteEvent("reading"),
            KeyEvent("\t"),
            PasteEvent("reader ccuv"),
            KeyEvent("\r"),
        )
    )
    config = _choose_custom_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=20,
        dashboard=dashboard,
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.kind == "timeline"
    assert config.chart.source == CustomCommandSource("reading", ("reader", "ccuv"))

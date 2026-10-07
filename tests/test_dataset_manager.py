from __future__ import annotations

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.datasets.manager import format_dataset_list, render_dataset_manager
from ccusage_viz.datasets.models import (
    DatasetProbeSnapshot,
    DatasetRegistration,
    DatasetRegistrationStatus,
    LocalDatasetSource,
)
from ccusage_viz.i18n import load_translator


def status(*, availability: str = "ready") -> DatasetRegistrationStatus:
    text = LocalizedText("WeRead", "微信读书")
    descriptor = CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(text, LocalizedText("Daily reading time", "每日阅读时长"), CustomUnit("minute", text, "suffix", 2)),
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        {"timeline": CustomChartDefaults("14d", None, None)},
        (),
        "Asia/Shanghai",
    )
    registration = DatasetRegistration(
        "weread",
        LocalDatasetSource(("weread", "ccuv")),
        availability != "disabled",
        "2026-10-07T00:00:00+00:00",
        "2026-10-07T00:00:00+00:00",
        DatasetProbeSnapshot("weread", descriptor, "2026-10-07T00:00:00+00:00"),
    )
    return DatasetRegistrationStatus(registration, availability)  # type: ignore[arg-type]


def test_manager_renders_grouped_list_and_toggleable_details() -> None:
    translator = load_translator("en")

    compact = render_dataset_manager((status(),), translator, width=80, height=24)
    detail = render_dataset_manager((status(),), translator, details=True, width=80, height=24)

    assert "WeRead" in "\n".join(compact.frame.rows)
    assert "Daily reading time" not in "\n".join(compact.frame.rows)
    assert "Daily reading time" in "\n".join(detail.frame.rows)
    assert compact.selected_id == "weread"


def test_manager_uses_side_by_side_details_on_wide_terminals() -> None:
    translator = load_translator("en")
    statuses = (status(), status(availability="disabled"))

    rendered = render_dataset_manager(statuses, translator, selected=1, details=True, width=120, height=24)
    body = "\n".join(rendered.frame.rows)

    assert "│" in body
    assert "Disabled" in body
    assert "Daily reading time" in body


def test_manager_uses_a_separate_detail_page_on_narrow_terminals() -> None:
    rendered = render_dataset_manager((status(),), load_translator("en"), details=True, width=80, height=24)
    body = "\n".join(rendered.frame.rows)

    assert "Daily reading time" in body
    assert "local command · Ready" not in body
    assert rendered.frame.rows[-1] == "i details · Esc back"


def test_dataset_list_formats_local_records_without_running_commands() -> None:
    output = format_dataset_list((status(), status(availability="disabled")), load_translator("en"))

    assert "weread 0.1.0 · Ready" in output
    assert "Disabled" in output

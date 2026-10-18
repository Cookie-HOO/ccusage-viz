from __future__ import annotations

from types import SimpleNamespace

import pytest

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomEnvironmentDeclaration,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.datasets.manager_installation import (
    _official_catalog_rows,
    _read_github_repository,
    _register_official,
)
from ccusage_viz.datasets.manager_rendering import format_dataset_list, render_dataset_manager
from ccusage_viz.datasets.manager_runtime import (
    _choose_dataset_source,
    _manager_help_frame,
    _manager_help_lines,
    _upgrade_all,
)
from ccusage_viz.datasets.models import (
    DatasetProbeSnapshot,
    DatasetRegistration,
    DatasetRegistrationStatus,
    DatasetUpdateCandidate,
    LocalDatasetSource,
    ManagedDatasetSource,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Frame
from ccusage_viz.tui_input import InputDecoder, KeyEvent


def status(*, availability: str = "ready", update: bool = False) -> DatasetRegistrationStatus:
    text = LocalizedText("WeRead", "微信读书")
    descriptor = CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(
            text,
            LocalizedText("Daily reading time", "每日阅读时长"),
            CustomUnit("minute", text, "suffix", 2),
        ),
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        {"timeline": CustomChartDefaults("14d", None, None)},
        (
            CustomEnvironmentDeclaration(
                "WEREAD_API_KEY",
                True,
                True,
                LocalizedText("WeRead API key", "微信读书 API 密钥"),
                LocalizedText("Follow the authorization guide.", "请按授权指南操作。"),
                "https://weread.qq.com/r/weread-skills",
            ),
        ),
        "Asia/Shanghai",
    )
    registration = DatasetRegistration(
        "weread",
        (
            ManagedDatasetSource(
                "official",
                "Cookie-HOO/ccuv-dataset-weread",
                "v0.1.0",
                "weread.tar.gz",
                "a" * 64,
            )
            if update
            else LocalDatasetSource(("weread", "ccuv"))
        ),
        availability != "disabled",
        "2026-10-07T00:00:00+00:00",
        "2026-10-07T00:00:00+00:00",
        DatasetProbeSnapshot("weread", descriptor, "2026-10-07T00:00:00+00:00"),
        DatasetUpdateCandidate("v0.1.1", "weread.tar.gz", "b" * 64) if update else None,
    )
    return DatasetRegistrationStatus(registration, availability)  # type: ignore[arg-type]


def test_manager_renders_grouped_list_and_toggleable_details() -> None:
    translator = load_translator("en")

    compact = render_dataset_manager((status(),), translator, width=80, height=24)
    detail = render_dataset_manager((status(),), translator, details=True, width=80, height=24)

    assert "WeRead" in "\n".join(compact.frame.rows)
    assert "Name" in "\n".join(compact.frame.rows)
    assert "Version" in "\n".join(compact.frame.rows)
    assert "Daily reading time" not in "\n".join(compact.frame.rows)
    assert "Daily reading time" in "\n".join(detail.frame.rows)
    assert compact.selected_id == "weread"


def test_manager_uses_side_by_side_details_on_wide_terminals() -> None:
    translator = load_translator("en")
    statuses = (status(), status(availability="disabled"))

    rendered = render_dataset_manager(
        statuses, translator, selected=1, details=True, width=120, height=24
    )
    body = "\n".join(rendered.frame.rows)

    assert "│" in body
    assert "Disabled" in body
    assert "Daily reading time" in body


def test_manager_uses_a_separate_detail_page_on_narrow_terminals() -> None:
    rendered = render_dataset_manager(
        (status(),), load_translator("en"), details=True, width=80, height=24
    )
    body = "\n".join(rendered.frame.rows)

    assert "Daily reading time" in body
    assert "local command · Ready" not in body
    assert rendered.frame.rows[-1] == "Enter / Esc back · h help"


def test_dataset_setup_help_expands_environment_instructions() -> None:
    record = status().registration
    setup = DatasetRegistrationStatus(
        record,
        "setup_required",
        record.probe.descriptor.environment,
    )
    translator = load_translator("en")
    detail = render_dataset_manager((setup,), translator, details=True, width=80, height=24)
    help_lines = _manager_help_lines(setup, translator, details=True, width=80)
    frame = _manager_help_frame(help_lines, translator, width=100, height=24)

    assert "WEREAD_API_KEY · missing" in "\n".join(detail.frame.rows)
    assert "Follow the authorization guide." not in "\n".join(detail.frame.rows)
    assert "Follow the authorization guide." in "\n".join(frame.rows)
    assert "https://weread.qq.com/r/weread-skills" in "\n".join(frame.rows)


def test_manager_help_uses_dashboard_style_highlight_for_section_titles() -> None:
    lines = _manager_help_lines(status(), load_translator("en"), details=False, width=80)
    frame = _manager_help_frame(lines, load_translator("en"), width=100, height=24, color=True)

    assert "\x1b[" in "\n".join(frame.rows)


def test_manager_general_help_does_not_repeat_a_second_heading() -> None:
    lines = _manager_help_lines(status(), load_translator("en"), details=False, width=80)

    assert "Dataset manager help" not in lines


def test_manager_help_highlights_sections_for_interactive_manager_default() -> None:
    lines = _manager_help_lines(status(), load_translator("en"), details=False, width=80)
    frame = _manager_help_frame(lines, load_translator("en"), width=100, height=24, color=True)

    assert f"\x1b[38;5;{get_color_scheme('classic').highlight}m" in "\n".join(frame.rows)


def test_manager_general_help_explains_the_dynamic_dataset_list() -> None:
    selected = status()
    lines = _manager_help_lines(
        selected,
        load_translator("en"),
        details=False,
        width=80,
    )

    assert "This list contains your registered Datasets." in "\n".join(lines)
    assert "Available: enabled, last probe succeeded" in "\n".join(lines)
    assert "Ready: enabled" not in "\n".join(lines)


def test_manager_footer_follows_dashboard_browse_order_without_quit() -> None:
    rendered = render_dataset_manager((status(),), load_translator("en"), width=100, height=24)

    assert rendered.frame.rows[-2:] == (
        "r refresh all · Enter details · j/k or ↑/↓ select · h help",
        "+ add · d disable · x remove",
    )
    assert "q quit" not in "\n".join(rendered.frame.rows[-2:])
    assert "i details" not in "\n".join(rendered.frame.rows[-2:])


def test_manager_shows_detected_update_in_list_details_and_controls() -> None:
    rendered = render_dataset_manager(
        (status(update=True),), load_translator("en"), width=80, height=28
    )
    details = render_dataset_manager(
        (status(update=True),), load_translator("en"), details=True, width=80, height=28
    )

    assert "0.1.0 → 0.1.1" in "\n".join(rendered.frame.rows)
    assert rendered.frame.rows[-2:] == (
        "r refresh all · Enter details · j/k or ↑/↓ select · h help",
        "+ add · u upgrade current · U upgrade all · d disable · x remove",
    )
    assert "Current version: 0.1.0" in "\n".join(details.frame.rows)
    assert "Update available: v0.1.0 → v0.1.1" in "\n".join(details.frame.rows)
    assert details.frame.rows[-2:] == (
        "Enter / Esc back · h help",
        "u upgrade current · U upgrade all",
    )


def test_upgrade_all_continues_after_an_individual_failure() -> None:
    statuses = (status(update=True), status(update=True))

    class Service:
        calls: list[str] = []

        def upgrade(self, dataset_id: str) -> None:
            self.calls.append(dataset_id)
            if len(self.calls) == 1:
                raise RuntimeError("failed")

    service = Service()

    assert _upgrade_all(service, statuses) == (1, 1)  # type: ignore[arg-type]
    assert service.calls == ["weread", "weread"]


def test_dataset_list_formats_local_records_without_running_commands() -> None:
    output = format_dataset_list((status(), status(availability="disabled")), load_translator("en"))

    assert "weread 0.1.0 · Ready" in output
    assert "Disabled" in output


def test_official_catalog_description_reuses_custom_ranking_muted_style() -> None:
    entry = SimpleNamespace(
        id="weread",
        title=LocalizedText("WeRead", "微信读书"),
        summary=LocalizedText(
            "Visualize reading activity", "将微信读书的阅读时长和书籍活动可视化。"
        ),
    )

    rows = _official_catalog_rows((entry,), load_translator("zh"), selected=0, width=80, color=True)

    assert rows[0] == "› 微信读书 · weread"
    assert "\x1b[" not in rows[0]
    assert f"\x1b[38;5;{get_color_scheme('classic').muted}m\x1b[2m" in rows[1]
    assert "将微信读书的阅读时长和书籍活动可视化。" in rows[1]


def test_official_catalog_ctrl_c_interrupts_nested_browser() -> None:
    entry = SimpleNamespace(
        id="weread",
        title=LocalizedText("WeRead", "微信读书"),
        summary=LocalizedText("Visualize reading activity", "阅读活动"),
    )

    class Service:
        def official_entries(self):
            return (entry,)

    class Screen:
        def paint(self, _frame: Frame, **_kwargs: object) -> None:
            pass

    with pytest.raises(KeyboardInterrupt):
        _register_official(
            Service(),  # type: ignore[arg-type]
            Screen(),  # type: ignore[arg-type]
            load_translator("en"),
            InputDecoder(),
            read_input=lambda: KeyEvent("\x03"),
        )


def test_add_source_chooser_lists_three_sources_and_selects_local() -> None:
    frames: list[Frame] = []

    class Screen:
        def paint(self, frame: Frame, **_kwargs: object) -> None:
            frames.append(frame)

    events = iter((KeyEvent("j"), KeyEvent("j"), KeyEvent("\r")))
    selected = _choose_dataset_source(
        Screen(),  # type: ignore[arg-type]
        load_translator("en"),
        InputDecoder(),
        read_input=lambda: next(events),
    )

    assert selected == "local"
    output = "\n".join(frames[0].rows)
    assert "Browse official datasets" in output
    assert "Install from GitHub" in output
    assert "Local command" in output


def test_github_prompt_accepts_h_as_repository_input() -> None:
    class Screen:
        def paint(self, _frame: Frame, **_kwargs: object) -> None:
            pass

    events = iter((KeyEvent("h"), KeyEvent("\r")))

    repository = _read_github_repository(
        Screen(),  # type: ignore[arg-type]
        load_translator("en"),
        InputDecoder(),
        read_input=lambda: next(events),
    )

    assert repository == "h"


def test_github_prompt_is_rendered_separately_from_controls() -> None:
    frames: list[Frame] = []

    class Screen:
        def paint(self, frame: Frame, **_kwargs: object) -> None:
            frames.append(frame)

    events = iter((KeyEvent("\x1b"),))
    _read_github_repository(
        Screen(),  # type: ignore[arg-type]
        load_translator("en"),
        InputDecoder(),
        read_input=lambda: next(events),
    )

    assert "Enter OWNER/REPOSITORY" in "\n".join(frames[0].rows[:-1])
    assert frames[0].rows[-1] == ("Type · DEL delete · Ctrl-H help · Enter discover · Esc back")

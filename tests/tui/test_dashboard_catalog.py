






























from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.tui.datasets.catalog import _official_catalog_rows, _official_catalog_viewport
from ccusage_viz.tui.datasets.chooser import _choose_pane_type
from ccusage_viz.tui_input import KeyEvent

from .dashboard_helpers import _catalog_entries


def test_official_catalog_items_separate_identity_from_description() -> None:
    rows = _official_catalog_rows(
        _catalog_entries(), load_translator("en"), index=0, width=48
    )

    assert rows[0] == "› Dataset 0 · dataset-0"
    assert all(row.startswith("  ") for row in rows[1:])
    assert rows[-1].endswith("…")
    assert len(rows) == 3
    assert not any("Name" in row or "Summary" in row for row in rows)
    assert all(display_width(row) <= 48 for row in rows)

def test_official_catalog_description_uses_muted_dim_theme_style() -> None:
    rows = _official_catalog_rows(
        _catalog_entries(),
        load_translator("en"),
        index=0,
        width=48,
        color=True,
        color_scheme="classic",
    )

    assert "\x1b[" not in rows[0]
    assert all("\x1b[" in row for row in rows[1:])
    assert all(strip_ansi(row).startswith("  ") for row in rows[1:])

def test_official_catalog_items_align_chinese_description_at_narrow_width() -> None:
    rows = _official_catalog_rows(
        _catalog_entries(), load_translator("zh"), index=0, width=18
    )

    assert rows[0].startswith("› 数据集 0 ·")
    assert all(row.startswith("  ") for row in rows[1:])
    assert all(display_width(row) <= 18 for row in rows)
    assert len(rows) <= 3

def test_official_catalog_viewport_keeps_selected_variable_height_item_visible() -> None:
    choices, offset = _official_catalog_viewport(
        _catalog_entries(5),
        load_translator("en"),
        index=4,
        offset=0,
        width=72,
        height=5,
    )

    rows = choices.splitlines()
    assert rows[0].startswith("› Dataset 4 · dataset-4")
    assert len(rows) == 3
    assert rows[-1].startswith("  ")
    assert offset > 0

def test_pane_chooser_groups_sources_in_command_order() -> None:
    frames: list[object] = []

    class Screen:
        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

    events = iter((KeyEvent("\x1b"),))
    assert _choose_pane_type(
        Screen(),  # type: ignore[arg-type]
        load_translator("en"),
        object(),  # type: ignore[arg-type]
        height=24,
        read_input=lambda: next(events),
    ) is None

    output = "\n".join(frames[0].rows)  # type: ignore[union-attr]
    expected = (
        "ccusage",
        "Timeline",
        "Calendar",
        "Stack",
        "Ranking",
        "Monitor",
        "Custom",
        "Datasets…",
        "Other",
        "Animation",
        "Empty",
    )
    positions = [output.index(value) for value in expected]
    assert positions == sorted(positions)

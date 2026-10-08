from __future__ import annotations

from ccusage_viz.i18n import load_translator
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui_input import KeyEvent, PasteEvent
from ccusage_viz.tui_preset_manager import (
    ClosePresetManager,
    DeletePreset,
    LoadPreset,
    PresetCatalogEntry,
    PresetCatalogSnapshot,
    PresetManagerState,
    SavePreset,
    reconcile_preset_manager,
    reduce_preset_manager,
    render_preset_manager,
)


def catalog(*entries: PresetCatalogEntry, current: str | None = None) -> PresetCatalogSnapshot:
    return PresetCatalogSnapshot(entries, current_source_key=current)


def test_catalog_keeps_source_qualified_shadow_rows_and_relationships() -> None:
    entries = catalog(
        PresetCatalogEntry("builtin:daily", "daily", "builtin"),
        PresetCatalogEntry("user:daily", "daily", "user"),
        PresetCatalogEntry("user:weekly", "weekly", "user"),
        current="user:daily",
    )

    assert [entry.key for entry in entries.ordered_entries] == [
        "builtin:daily",
        "user:daily",
        "user:weekly",
    ]
    assert entries.relationship(entries.entry("builtin:daily")) == "builtin-overridden"  # type: ignore[arg-type]
    assert entries.relationship(entries.entry("user:daily")) == "user-override"  # type: ignore[arg-type]
    assert entries.relationship(entries.entry("user:weekly")) == "user"  # type: ignore[arg-type]


def test_reconcile_preserves_selection_and_clamps_scroll_after_refresh() -> None:
    entries = catalog(
        PresetCatalogEntry("builtin:a", "a", "builtin"),
        PresetCatalogEntry("builtin:b", "b", "builtin"),
        PresetCatalogEntry("builtin:c", "c", "builtin"),
        PresetCatalogEntry("builtin:d", "d", "builtin"),
    )

    reconciled = reconcile_preset_manager(
        PresetManagerState(selected_key="builtin:d", scroll_offset=99), entries, visible_rows=2
    )
    assert reconciled.selected_key == "builtin:d"
    assert reconciled.scroll_offset == 2

    refreshed = catalog(PresetCatalogEntry("builtin:b", "b", "builtin"))
    reconciled = reconcile_preset_manager(reconciled, refreshed, visible_rows=2)
    assert reconciled.selected_key == "builtin:b"
    assert reconciled.scroll_offset == 0


def test_list_navigation_wraps_and_emits_source_qualified_load_command() -> None:
    entries = catalog(
        PresetCatalogEntry("builtin:daily", "daily", "builtin"),
        PresetCatalogEntry("user:daily", "daily", "user"),
    )
    state = PresetManagerState(selected_key="builtin:daily")

    moved = reduce_preset_manager(state, entries, KeyEvent("j"), visible_rows=1)
    assert moved.state.selected_key == "user:daily"
    wrapped = reduce_preset_manager(moved.state, entries, KeyEvent("j"), visible_rows=1)
    assert wrapped.state.selected_key == "builtin:daily"

    loaded = reduce_preset_manager(moved.state, entries, KeyEvent("\r"))
    assert loaded.command == LoadPreset("user:daily")


def test_save_draft_supports_paste_editing_validation_and_new_save() -> None:
    entries = catalog(PresetCatalogEntry("builtin:daily", "daily", "builtin"))
    state = reduce_preset_manager(PresetManagerState(), entries, KeyEvent("s")).state

    state = reduce_preset_manager(state, entries, PasteEvent("Daily")).state
    invalid = reduce_preset_manager(state, entries, KeyEvent("\r"))
    assert invalid.state.notice == "preset-invalid-name"

    state = reduce_preset_manager(invalid.state, entries, KeyEvent("\x15")).state
    state = reduce_preset_manager(state, entries, PasteEvent("daily-review")).state
    saved = reduce_preset_manager(state, entries, KeyEvent("\r"))
    assert saved.command == SavePreset("daily-review", False)
    assert saved.state.mode == "list"


def test_save_same_user_name_requires_explicit_overwrite_and_can_cancel() -> None:
    entries = catalog(PresetCatalogEntry("user:daily", "daily", "user"))
    state = PresetManagerState(mode="save", draft_name="daily")

    requested = reduce_preset_manager(state, entries, KeyEvent("\r"))
    assert requested.state.mode == "overwrite"
    cancelled = reduce_preset_manager(requested.state, entries, KeyEvent("\x1b"))
    assert cancelled.state.mode == "save"
    assert cancelled.state.draft_name == "daily"

    confirmed = reduce_preset_manager(requested.state, entries, KeyEvent("y"))
    assert confirmed.command == SavePreset("daily", True)


def test_save_builtin_shadow_is_first_save_not_overwrite() -> None:
    entries = catalog(PresetCatalogEntry("builtin:daily", "daily", "builtin"))

    saved = reduce_preset_manager(
        PresetManagerState(mode="save", draft_name="daily"), entries, KeyEvent("\r")
    )

    assert saved.command == SavePreset("daily", False)


def test_delete_only_confirms_available_user_entries() -> None:
    builtin = catalog(PresetCatalogEntry("builtin:daily", "daily", "builtin"))
    builtin_attempt = reduce_preset_manager(
        PresetManagerState(selected_key="builtin:daily"), builtin, KeyEvent("x")
    )
    assert builtin_attempt.state.mode == "list"

    unavailable = catalog(PresetCatalogEntry("user:damaged", "damaged", "user", available=False))
    unavailable_attempt = reduce_preset_manager(
        PresetManagerState(selected_key="user:damaged"), unavailable, KeyEvent("x")
    )
    assert unavailable_attempt.state.mode == "list"

    user = catalog(PresetCatalogEntry("user:daily", "daily", "user"))
    requested = reduce_preset_manager(
        PresetManagerState(selected_key="user:daily"), user, KeyEvent("x")
    )
    assert requested.state.mode == "delete"
    assert requested.state.target_key == "user:daily"
    cancelled = reduce_preset_manager(requested.state, user, KeyEvent("\x1b"))
    assert cancelled.state.mode == "list"
    assert cancelled.state.target_key is None

    confirmed = reduce_preset_manager(requested.state, user, KeyEvent("\r"))
    assert confirmed.command == DeletePreset("user:daily")


def test_escape_closes_list_manager() -> None:
    closed = reduce_preset_manager(PresetManagerState(), catalog(), KeyEvent("\x1b"))

    assert closed.command == ClosePresetManager()


def test_render_marks_relationship_and_provenance_with_ascii_fallback() -> None:
    entries = catalog(
        PresetCatalogEntry("builtin:daily", "daily", "builtin"),
        PresetCatalogEntry("user:daily", "daily", "user"),
        current="user:daily",
    )
    rendered = render_preset_manager(
        PresetManagerState(selected_key="user:daily"),
        entries,
        load_translator("en"),
        Terminal(width=100, height=10, color=False, ascii=False),
    )
    text = "\n".join(rendered.rows)
    assert "BUILT-IN PRESETS" in text
    assert "YOUR PRESETS" in text
    assert "daily · overridden" in text
    assert "› daily · overrides built-in · started here" in text

    ascii_rendered = render_preset_manager(
        PresetManagerState(selected_key="user:daily"),
        entries,
        load_translator("en"),
        Terminal(width=100, height=10, color=False, ascii=True),
    )
    ascii_text = "\n".join(ascii_rendered.rows)
    assert "> daily" in ascii_text
    assert "Enter load | s save current" in ascii_text


def test_render_translates_invalid_name_notice_and_clips_narrow_rows() -> None:
    entries = catalog(
        PresetCatalogEntry("user:long", "long-dashboard-preset-name", "user"),
        current="user:long",
    )
    rendered = render_preset_manager(
        PresetManagerState(selected_key="user:long", notice="preset-invalid-name"),
        entries,
        load_translator("en"),
        Terminal(width=24, height=7, color=False, ascii=True),
    )

    assert all(len(row) <= 24 for row in rendered.rows)
    assert "Preset names start" in "\n".join(rendered.rows)

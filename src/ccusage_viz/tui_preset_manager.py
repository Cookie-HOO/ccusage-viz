"""Pure state and rendering boundary for the Dashboard preset manager.

The Dashboard controller supplies a catalog and executes emitted commands.  This
module deliberately has no knowledge of preset storage, Dataset resolution,
history, or live panes, so it can be tested without starting the TUI.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, TypeAlias

from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.presets.values import DashboardPresetValidationError, validate_preset_name
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Frame, Terminal, compose_frame, emphasize
from ccusage_viz.terminal_ui import controls_line, notice_lines
from ccusage_viz.tui_input import KeyEvent, PasteEvent

PresetSource: TypeAlias = Literal["builtin", "user", "unavailable"]
PresetManagerMode: TypeAlias = Literal["list", "save", "overwrite", "delete"]


@dataclass(frozen=True, slots=True)
class PresetCatalogEntry:
    """One source-qualified preset record suitable for manager presentation."""

    key: str
    name: str
    source: PresetSource
    available: bool = True

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("preset catalog key must not be empty")
        if not self.name:
            raise ValueError("preset catalog name must not be empty")
        if self.source == "unavailable" and self.available:
            raise ValueError("unavailable catalog entries must not be loadable")


@dataclass(frozen=True, slots=True)
class PresetCatalogSnapshot:
    """Stable, source-qualified manager input supplied by the controller."""

    entries: tuple[PresetCatalogEntry, ...]
    current_source_key: str | None = None
    warning: str | None = None

    def __post_init__(self) -> None:
        keys = tuple(entry.key for entry in self.entries)
        if len(keys) != len(set(keys)):
            raise ValueError("preset catalog keys must be unique")
        if self.current_source_key is not None and self.current_source_key not in keys:
            raise ValueError("current preset source must identify a catalog entry")

    @property
    def ordered_entries(self) -> tuple[PresetCatalogEntry, ...]:
        source_order = {"builtin": 0, "user": 1, "unavailable": 2}
        return tuple(
            sorted(
                self.entries,
                key=lambda entry: (source_order[entry.source], entry.name.casefold(), entry.key),
            )
        )

    def entry(self, key: str | None) -> PresetCatalogEntry | None:
        if key is None:
            return None
        return next((entry for entry in self.entries if entry.key == key), None)

    def has_user_named(self, name: str) -> bool:
        return any(entry.source == "user" and entry.name == name for entry in self.entries)

    def relationship(self, entry: PresetCatalogEntry) -> str:
        if not entry.available or entry.source == "unavailable":
            return "unavailable"
        shares_name = any(
            other.name == entry.name and other.source != entry.source and other.available
            for other in self.entries
        )
        if entry.source == "builtin":
            return "builtin-overridden" if shares_name else "builtin"
        return "user-override" if shares_name else "user"


@dataclass(frozen=True, slots=True)
class PresetManagerState:
    """Ephemeral manager state; all persistence effects are emitted as commands."""

    selected_key: str | None = None
    scroll_offset: int = 0
    mode: PresetManagerMode = "list"
    draft_name: str = ""
    target_key: str | None = None
    notice: str | None = None


@dataclass(frozen=True, slots=True)
class LoadPreset:
    key: str


@dataclass(frozen=True, slots=True)
class SavePreset:
    name: str
    overwrite: bool


@dataclass(frozen=True, slots=True)
class DeletePreset:
    key: str


@dataclass(frozen=True, slots=True)
class ClosePresetManager:
    pass


PresetManagerCommand: TypeAlias = LoadPreset | SavePreset | DeletePreset | ClosePresetManager


@dataclass(frozen=True, slots=True)
class PresetManagerUpdate:
    state: PresetManagerState
    command: PresetManagerCommand | None = None


def reconcile_preset_manager(
    state: PresetManagerState,
    catalog: PresetCatalogSnapshot,
    *,
    visible_rows: int = 10,
) -> PresetManagerState:
    """Keep selection and scrolling valid after a controller catalog refresh."""

    entries = catalog.ordered_entries
    selected_key = state.selected_key
    if not entries:
        selected_key = None
    elif catalog.entry(selected_key) is None:
        selected_key = entries[0].key
    index = next((index for index, entry in enumerate(entries) if entry.key == selected_key), 0)
    scroll_offset = _scroll_for(index, state.scroll_offset, len(entries), visible_rows)
    target_key = state.target_key if catalog.entry(state.target_key) is not None else None
    mode: PresetManagerMode = state.mode
    if mode == "delete" and target_key is None:
        mode = "list"
    return replace(
        state,
        selected_key=selected_key,
        scroll_offset=scroll_offset,
        target_key=target_key,
        mode=mode,
    )


def reduce_preset_manager(
    state: PresetManagerState,
    catalog: PresetCatalogSnapshot,
    event: KeyEvent | PasteEvent,
    *,
    visible_rows: int = 10,
) -> PresetManagerUpdate:
    """Reduce one input event into manager state and an optional controller command."""

    state = reconcile_preset_manager(state, catalog, visible_rows=visible_rows)
    if isinstance(event, PasteEvent):
        if state.mode == "save":
            return PresetManagerUpdate(
                replace(state, draft_name=state.draft_name + event.value, notice=None)
            )
        return PresetManagerUpdate(state)

    key = event.value
    if state.mode == "save":
        return _reduce_save(state, catalog, key)
    if state.mode == "overwrite":
        return _reduce_overwrite(state, key)
    if state.mode == "delete":
        return _reduce_delete(state, key)
    return _reduce_list(state, catalog, key, visible_rows=visible_rows)


def render_preset_manager(
    state: PresetManagerState,
    catalog: PresetCatalogSnapshot,
    translator: Translator,
    terminal: Terminal,
) -> Frame:
    """Render a full-screen manager frame using only neutral catalog input."""

    list_rows = max(1, terminal.height - 4)
    state = reconcile_preset_manager(state, catalog, visible_rows=list_rows)
    missing_name = "-" if terminal.ascii else "—"
    if state.mode == "save":
        body = translator.text(
            "status.tui_preset_save_prompt", name=state.draft_name or missing_name
        )
        controls = translator.text("status.tui_preset_save_controls")
    elif state.mode == "overwrite":
        body = translator.text("status.tui_preset_overwrite_prompt", name=state.draft_name)
        controls = translator.text("status.tui_preset_confirm_controls")
    elif state.mode == "delete":
        target = catalog.entry(state.target_key)
        name = target.name if target is not None else missing_name
        body = translator.text("status.tui_preset_delete_prompt", name=name)
        controls = translator.text("status.tui_preset_confirm_controls")
    else:
        body = _catalog_body(
            state, catalog, translator, terminal.width, list_rows, terminal.color, terminal.ascii
        )
        controls = translator.text("status.tui_preset_manager_controls")

    if terminal.ascii:
        controls = controls.replace(" · ", " | ")
    notices = tuple(
        item
        for item in (catalog.warning, _render_notice(state.notice, translator))
        if item is not None
    )
    return compose_frame(
        body,
        translator.text("status.tui_preset_manager_title", count=len(catalog.entries)),
        controls_line(controls, width=terminal.width, color=terminal.color),
        notice_lines(
            notices,
            width=terminal.width,
            color=terminal.color,
            ascii=terminal.ascii,
            translator=translator,
        ),
        height=terminal.height,
    )


def _reduce_list(
    state: PresetManagerState,
    catalog: PresetCatalogSnapshot,
    key: str,
    *,
    visible_rows: int,
) -> PresetManagerUpdate:
    entries = catalog.ordered_entries
    if key in {"\x1b", "q"}:
        return PresetManagerUpdate(state, ClosePresetManager())
    if key == "s":
        return PresetManagerUpdate(replace(state, mode="save", draft_name="", notice=None))
    if key in {"j", "\x1b[B"}:
        return PresetManagerUpdate(_move_selection(state, entries, 1, visible_rows))
    if key in {"k", "\x1b[A"}:
        return PresetManagerUpdate(_move_selection(state, entries, -1, visible_rows))
    selected = catalog.entry(state.selected_key)
    if key == "x" and selected is not None and selected.source == "user" and selected.available:
        return PresetManagerUpdate(
            replace(state, mode="delete", target_key=selected.key, notice=None)
        )
    if key in {"\r", "\n"} and selected is not None and selected.available:
        return PresetManagerUpdate(state, LoadPreset(selected.key))
    return PresetManagerUpdate(state)


def _reduce_save(
    state: PresetManagerState, catalog: PresetCatalogSnapshot, key: str
) -> PresetManagerUpdate:
    if key == "\x1b":
        return PresetManagerUpdate(replace(state, mode="list", notice=None))
    if key in {"\x7f", "\b"}:
        return PresetManagerUpdate(replace(state, draft_name=state.draft_name[:-1], notice=None))
    if key == "\x15":
        return PresetManagerUpdate(replace(state, draft_name="", notice=None))
    if key in {"\r", "\n"}:
        try:
            name = validate_preset_name(state.draft_name)
        except DashboardPresetValidationError:
            return PresetManagerUpdate(replace(state, notice="preset-invalid-name"))
        if catalog.has_user_named(name):
            return PresetManagerUpdate(replace(state, mode="overwrite", notice=None))
        return PresetManagerUpdate(
            replace(state, mode="list", notice=None), SavePreset(name, False)
        )
    if len(key) == 1 and key.isprintable():
        return PresetManagerUpdate(replace(state, draft_name=state.draft_name + key, notice=None))
    return PresetManagerUpdate(state)


def _reduce_overwrite(state: PresetManagerState, key: str) -> PresetManagerUpdate:
    if key == "\x1b":
        return PresetManagerUpdate(replace(state, mode="save", notice=None))
    if key in {"\r", "\n", "y", "Y"}:
        return PresetManagerUpdate(
            replace(state, mode="list", notice=None), SavePreset(state.draft_name, True)
        )
    return PresetManagerUpdate(state)


def _reduce_delete(state: PresetManagerState, key: str) -> PresetManagerUpdate:
    if key == "\x1b":
        return PresetManagerUpdate(replace(state, mode="list", target_key=None, notice=None))
    if key in {"\r", "\n", "y", "Y"} and state.target_key is not None:
        return PresetManagerUpdate(
            replace(state, mode="list", target_key=None, notice=None),
            DeletePreset(state.target_key),
        )
    return PresetManagerUpdate(state)


def _move_selection(
    state: PresetManagerState,
    entries: tuple[PresetCatalogEntry, ...],
    step: int,
    visible_rows: int,
) -> PresetManagerState:
    if not entries:
        return state
    selected_index = next(
        (index for index, entry in enumerate(entries) if entry.key == state.selected_key), 0
    )
    index = (selected_index + step) % len(entries)
    return replace(
        state,
        selected_key=entries[index].key,
        scroll_offset=_scroll_for(index, state.scroll_offset, len(entries), visible_rows),
    )


def _scroll_for(index: int, current: int, count: int, visible_rows: int) -> int:
    capacity = max(1, visible_rows)
    maximum = max(0, count - capacity)
    offset = min(max(current, 0), maximum)
    if index < offset:
        return index
    if index >= offset + capacity:
        return index - capacity + 1
    return offset


def _render_notice(notice: str | None, translator: Translator) -> str | None:
    if notice is None:
        return None
    # Controller-originated validation can include concrete, multiline source
    # details; reducer notices remain stable translation keys.
    if "\n" in notice:
        return notice
    return translator.text(f"status.tui_{notice.replace('-', '_')}")


def _catalog_body(
    state: PresetManagerState,
    catalog: PresetCatalogSnapshot,
    translator: Translator,
    width: int,
    visible_rows: int,
    color: bool,
    ascii_only: bool,
) -> str:
    entries = catalog.ordered_entries
    if not entries:
        return translator.text("status.tui_preset_empty")
    marker = ">" if ascii_only else "›"
    rows: list[str] = []
    visible = entries[state.scroll_offset : state.scroll_offset + visible_rows]
    previous_source: PresetSource | None = None
    for entry in visible:
        if entry.source != previous_source:
            rows.append(
                _section_heading(
                    translator.text(f"status.tui_preset_section_{entry.source}"),
                    width=width,
                    color=color,
                )
            )
            previous_source = entry.source
        selected = marker if entry.key == state.selected_key else " "
        relationship = catalog.relationship(entry)
        metadata = (
            []
            if relationship in {"builtin", "user"}
            else [translator.text(f"status.tui_preset_relationship_{relationship}")]
        )
        if entry.key == catalog.current_source_key:
            metadata.append(translator.text("status.tui_preset_started_here"))
        suffix = f" · {' · '.join(metadata)}" if metadata else ""
        rows.append(
            clip_width(
                f"{selected} {entry.name}{suffix}",
                width,
            )
        )
    return "\n".join(rows)


def _section_heading(value: str, *, width: int, color: bool) -> str:
    return clip_width(
        emphasize(value, color=get_color_scheme("classic").highlight, enabled=color), width
    )

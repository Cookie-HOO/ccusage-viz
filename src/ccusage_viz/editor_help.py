"""Shared, localized content structure for overlay-editor Help."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditorHelpGroup:
    """One named group of localized overlay-editor Help items."""

    heading_key: str
    item_keys: tuple[str, ...]


def editor_help_groups(*, dashboard: bool = False) -> tuple[EditorHelpGroup, ...]:
    """Return shared editor Help groups, plus Dashboard Pane controls when needed."""

    groups = (
        EditorHelpGroup(
            "status.tui_help_editor_source",
            (
                "status.tui_help_editor_source_text",
                "status.tui_help_editor_source_command",
                "status.tui_help_editor_source_switch",
            ),
        ),
        EditorHelpGroup(
            "status.tui_help_editor_navigation",
            ("status.tui_help_editor_navigation_detail",),
        ),
        EditorHelpGroup(
            "status.tui_help_editor_draft",
            ("status.tui_help_editor_draft_detail",),
        ),
        EditorHelpGroup(
            "status.tui_help_editor_complete",
            ("status.tui_help_editor_complete_detail",),
        ),
    )
    if not dashboard:
        return groups
    return (
        *groups,
        EditorHelpGroup(
            "status.tui_help_editor_dashboard", ("status.tui_help_editor_dashboard_height",)
        ),
    )

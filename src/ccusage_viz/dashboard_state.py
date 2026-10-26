"""Immutable Dashboard declarations shared by history and preset boundaries.

These values deliberately contain only declarative Dashboard state. Runtime panes,
query handles, modal state, terminal geometry, and lifecycle resources remain owned
by the Dashboard TUI controller.
"""

from __future__ import annotations

from dataclasses import dataclass

from ccusage_viz.data_view import BodyView, DashboardBodyView
from ccusage_viz.options import PaneConfig


@dataclass(frozen=True, slots=True)
class DashboardPaneState:
    """Declarative pane state suitable for history restoration."""

    pane_id: int
    config: PaneConfig
    body_view: BodyView
    attachment_style: str | None = None
    attachment_theme: str | None = None
    attachment_enabled: bool = False
    animation_theme: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardState:
    """Dashboard presentation state without runtime resources."""

    panes: tuple[DashboardPaneState, ...]
    columns: int
    spotlight: int
    column_weights: tuple[int, ...] | None
    row_weights: tuple[int, ...] | None
    theme: str
    style: str
    header_style: str
    header_summary: str
    body_view: DashboardBodyView

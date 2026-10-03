"""Product presentation surfaces for historical chart renderers.

A surface is deliberately selected by the host product boundary.  It is not a
chart option: native and command-backed domains adapt their own semantics into
:class:`SurfacePresentation`, then the matching standalone or Dashboard-pane
implementation owns viewport, axes, chrome, and control-row policy.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ccusage_viz.i18n import Translator
from ccusage_viz.options import Density
from ccusage_viz.render.base import RenderAudit, RenderContext, audit_row_visible
from ccusage_viz.terminal import Terminal

HistoricalKind = Literal["timeline", "calendar", "stack", "ranking"]
SurfaceName = Literal["standalone", "dashboard_pane"]


@dataclass(frozen=True, slots=True)
class SurfaceControls:
    """Controls owned by one kind-specific product presentation surface.

    Hosts may render these rows and route their actions, but must not turn them
    back into an unstructured ``control_rows`` rendering argument.
    """

    rows: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    focused: bool = False
    reserves_prompt: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


EMPTY_SURFACE_CONTROLS = SurfaceControls()


@dataclass(frozen=True, slots=True)
class SurfacePresentation:
    """Domain-neutral display inputs consumed by a concrete surface."""

    kind: HistoricalKind
    color_scheme: str
    style: str | None
    legend_position: str
    density: Density
    weekday_mode: str
    period: str | None
    title_content: str | None
    filter_summary: str | None
    accepted_at: datetime | None
    query_elapsed: float | None
    interval: float | None
    refreshing: bool = False
    querying: bool = False
    pending: bool = False
    deltas: Mapping[Hashable, float] | None = None
    rank_deltas: Mapping[Hashable, int] | None = None

    @property
    def audit(self) -> RenderAudit:
        return RenderAudit(
            self.accepted_at,
            self.query_elapsed,
            self.interval,
            refreshing=self.refreshing,
            querying=self.querying,
        )

    @property
    def audit_row_visible(self) -> bool:
        return audit_row_visible(self.density, self.audit)


class HistoricalPresentationSurface(Protocol):
    """One concrete, kind-specific chart presentation implementation."""

    def context(
        self,
        terminal: Terminal,
        translator: Translator,
        presentation: SurfacePresentation,
        *,
        notices: int = 0,
        controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
        reserved_summary_rows: int = 0,
    ) -> RenderContext: ...


def _context(
    terminal: Terminal,
    translator: Translator,
    presentation: SurfacePresentation,
    *,
    height: int,
    hide_upper_right_axes: bool,
) -> RenderContext:
    return RenderContext(
        terminal.width,
        max(1, height),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=presentation.color_scheme,
        style=presentation.style,
        legend_position=presentation.legend_position,
        hide_upper_right_axes=hide_upper_right_axes,
        deltas=presentation.deltas,
        rank_deltas=presentation.rank_deltas,
        weekday_mode=presentation.weekday_mode,
        period=presentation.period,
        title_content=presentation.title_content,
        filter_summary=presentation.filter_summary,
        density=presentation.density,
        pending=presentation.pending,
        audit=presentation.audit,
    )


@dataclass(frozen=True, slots=True)
class _StandaloneSurface:
    """Base for a standalone kind presentation (surface A)."""

    kind: HistoricalKind
    name: SurfaceName = "standalone"

    def context(
        self,
        terminal: Terminal,
        translator: Translator,
        presentation: SurfacePresentation,
        *,
        notices: int = 0,
        controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
        reserved_summary_rows: int = 0,
    ) -> RenderContext:
        del reserved_summary_rows
        if presentation.kind != self.kind:
            raise ValueError(f"{self.kind} standalone surface cannot render {presentation.kind}")
        # Status/footer belongs to the standalone surface. Its operation bar and
        # optional prompt are independently budgeted before chart-body rendering.
        height = (
            terminal.height
            - 1
            - notices
            - controls.row_count
            - int(controls.reserves_prompt)
            - int(presentation.audit_row_visible)
        )
        return _context(
            terminal,
            translator,
            presentation,
            height=height,
            hide_upper_right_axes=False,
        )


@dataclass(frozen=True, slots=True)
class _DashboardPaneSurface:
    """Base for a Dashboard-pane kind presentation (surface B)."""

    kind: HistoricalKind
    name: SurfaceName = "dashboard_pane"

    def context(
        self,
        terminal: Terminal,
        translator: Translator,
        presentation: SurfacePresentation,
        *,
        notices: int = 0,
        controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
        reserved_summary_rows: int = 0,
    ) -> RenderContext:
        if presentation.kind != self.kind:
            raise ValueError(f"{self.kind} Dashboard surface cannot render {presentation.kind}")
        # Dashboard header, dividers, and outer framing are compositor-owned;
        # this surface only reserves its pane-local controls/notices/audit rows.
        height = (
            terminal.height
            - notices
            - controls.row_count
            - int(presentation.audit_row_visible)
            - reserved_summary_rows
        )
        return _context(
            terminal,
            translator,
            presentation,
            height=height,
            hide_upper_right_axes=True,
        )


class StandaloneTimelinePresentation(_StandaloneSurface):
    def __init__(self) -> None:
        super().__init__("timeline")


class StandaloneCalendarPresentation(_StandaloneSurface):
    def __init__(self) -> None:
        super().__init__("calendar")


class StandaloneStackPresentation(_StandaloneSurface):
    def __init__(self) -> None:
        super().__init__("stack")


class StandaloneRankingPresentation(_StandaloneSurface):
    def __init__(self) -> None:
        super().__init__("ranking")


class DashboardPaneTimelinePresentation(_DashboardPaneSurface):
    def __init__(self) -> None:
        super().__init__("timeline")


class DashboardPaneCalendarPresentation(_DashboardPaneSurface):
    def __init__(self) -> None:
        super().__init__("calendar")


class DashboardPaneStackPresentation(_DashboardPaneSurface):
    def __init__(self) -> None:
        super().__init__("stack")


class DashboardPaneRankingPresentation(_DashboardPaneSurface):
    def __init__(self) -> None:
        super().__init__("ranking")


STANDALONE_SURFACES: Mapping[HistoricalKind, HistoricalPresentationSurface] = {
    "timeline": StandaloneTimelinePresentation(),
    "calendar": StandaloneCalendarPresentation(),
    "stack": StandaloneStackPresentation(),
    "ranking": StandaloneRankingPresentation(),
}
DASHBOARD_PANE_SURFACES: Mapping[HistoricalKind, HistoricalPresentationSurface] = {
    "timeline": DashboardPaneTimelinePresentation(),
    "calendar": DashboardPaneCalendarPresentation(),
    "stack": DashboardPaneStackPresentation(),
    "ranking": DashboardPaneRankingPresentation(),
}


def standalone_surface(kind: HistoricalKind) -> HistoricalPresentationSurface:
    """Return the standalone presentation implementation for ``kind``."""
    return STANDALONE_SURFACES[kind]


def dashboard_pane_surface(kind: HistoricalKind) -> HistoricalPresentationSurface:
    """Return the Dashboard-pane presentation implementation for ``kind``."""
    return DASHBOARD_PANE_SURFACES[kind]

from __future__ import annotations

from shutil import get_terminal_size  # noqa: F401 - retained test injection seam

from ccusage_viz.core.time import local_today
from ccusage_viz.dashboard_layout import layout_bands
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.options import DASHBOARD_STYLES
from ccusage_viz.processing import required_summary_coverage
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.tui.controls import _cycle
from ccusage_viz.tui.header import (
    _cycle_header_summary,
    _invalidate_custom_dashboard_summaries,
    _set_header_theme,
)
from ccusage_viz.tui.history import record_mutation
from ccusage_viz.tui.input import end_adjustment
from ccusage_viz.tui.layout import _dashboard_structure
from ccusage_viz.tui.painting import paint
from ccusage_viz.tui.queries import refresh_custom_summaries, refresh_header
from ccusage_viz.tui.session import LayoutDraft, TuiSession


def _commit_layout_draft(session: TuiSession) -> None:
    draft = session.layout_draft
    if draft is None:
        return
    old = layout_bands(
        columns=session.columns, spotlight=session.spotlight, pane_count=len(session.panes)
    )
    new = layout_bands(
        columns=draft.columns, spotlight=draft.spotlight, pane_count=len(session.panes)
    )

    def commit() -> None:
        session.columns = draft.columns
        session.spotlight = draft.spotlight
        if old.columns != new.columns:
            session.column_weights = None
        if old.rows != new.rows:
            session.row_weights = None

    record_mutation(session, ("layout", "topology"), commit)
    session.layout_draft = None


def handle_dashboard_adjustment(session: TuiSession, event: object, key: object) -> None:
    if session.layout_draft is not None:
        draft = session.layout_draft
        if key == "\x1b":
            session.layout_draft = None
        elif key in {"\r", "\n"}:
            _commit_layout_draft(session)
        elif key in {"\x1b[A", "\x1b[B", "j", "k", "\t"}:
            draft.selected = "columns" if draft.selected == "spotlight" else "spotlight"
        elif key in {"\x1b[D", "-", "\x1b[C", "+"}:
            delta = -1 if key in {"\x1b[D", "-"} else 1
            if draft.selected == "spotlight":
                draft.spotlight = min(len(session.panes), max(0, draft.spotlight + delta))
            else:
                draft.columns = min(len(session.panes), max(1, draft.columns + delta))
        paint(session)
        return
    if key in {"\r", "\n", "\x1b"}:
        end_adjustment(session)
    elif key in {"t", "T"}:

        def cycle_theme() -> None:
            session.dashboard_theme = _cycle(
                COLOR_SCHEMES, session.dashboard_theme, 1 if key == "t" else -1
            )
            _set_header_theme(session.header, session.dashboard_theme)

        record_mutation(session, ("dashboard", "theme"), cycle_theme)
    elif key in {"s", "S"}:

        def cycle_style() -> None:
            session.dashboard_style = _cycle(
                DASHBOARD_STYLES, session.dashboard_style, 1 if key == "s" else -1
            )
            session.divider_style, session.frame_style = _dashboard_structure(
                session.dashboard_style
            )

        record_mutation(session, ("dashboard", "style"), cycle_style)
    elif key == "H":

        def cycle_header() -> None:
            session.header_style = _cycle(
                ("hidden", "compact", "banner", "panel"), session.header_style, 1
            )
            if session.header_style != "hidden" and session.header.summary_period != "none":
                required = required_summary_coverage(local_today(), session.header.summary_period)
                if session.header.token_enabled and any(
                    not session.header.coverage.covers(item) for item in required.intervals
                ):
                    refresh_header(session, trigger=LifecycleTrigger.CONFIGURATION)
                refresh_custom_summaries(session, trigger=LifecycleTrigger.CONFIGURATION)

        record_mutation(session, ("header", "style"), cycle_header)
    elif key in {"p", "P"}:

        def cycle_summary() -> None:
            next_summary = _cycle_header_summary(
                session.header.summary_period, step=1 if key == "p" else -1
            )
            session.header.summary_period = next_summary
            session.header.generation += 1
            session.header.lifecycle.detach_active()
            _invalidate_custom_dashboard_summaries(session.header)
            if session.header_style != "hidden" and next_summary != "none":
                required = required_summary_coverage(local_today(), next_summary)
                if session.header.token_enabled and any(
                    not session.header.coverage.covers(item) for item in required.intervals
                ):
                    refresh_header(session, trigger=LifecycleTrigger.CONFIGURATION)
                refresh_custom_summaries(session, trigger=LifecycleTrigger.CONFIGURATION)

        record_mutation(session, ("header", "summary"), cycle_summary)
    elif key == "z":
        session.layout_draft = LayoutDraft(session.columns, session.spotlight)
    else:
        return
    paint(session)

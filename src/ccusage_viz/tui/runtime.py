from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
import time
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.options import (
    DashboardLaunch,
)
from ccusage_viz.tui.custom_adjustments import (
    _finish_ranking_search_editing,
)
from ccusage_viz.tui.models import (
    TuiChartPane,
    TuiCustomPane,
)
from ccusage_viz.tui.pane_lifecycle import _shutdown_pane
from ccusage_viz.tui_input import (
    tui_input_mode,
)


def run_tui(options: DashboardLaunch, translator: Translator) -> int:
    from ccusage_viz.tui.completion import collect
    from ccusage_viz.tui.datasets.modal import (
        collect_dataset_modal,
    )
    from ccusage_viz.tui.events import dispatch_event
    from ccusage_viz.tui.input import (
        animation_deadline,
        end_adjustment,
        raise_if_interrupt,
        read_adjustment_event,
        set_screen_cursor_visible,
    )
    from ccusage_viz.tui.painting import paint
    from ccusage_viz.tui.queries import (
        refresh,
        refresh_custom_summaries,
        refresh_header,
    )
    from ccusage_viz.tui.session import TuiSession

    session = TuiSession(options, translator)
    try:
        set_screen_cursor_visible(session, False)
        with tui_input_mode() as session.decoder:
            for index in range(len(session.panes)):
                refresh(session, index, trigger=LifecycleTrigger.STARTUP)
            if session.header_style != "hidden":
                refresh_header(session, trigger=LifecycleTrigger.STARTUP)
                refresh_custom_summaries(session, trigger=LifecycleTrigger.STARTUP)
            paint(session)
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != session.last_size:
                    paint(session, force=True)
                changed = collect(session)
                if session.dataset_modal is not None:
                    changed = collect_dataset_modal(session) or changed
                now = time.monotonic()
                refresh_requested = False
                if session.header_style != "hidden" and session.header.scheduler.due(now=now):
                    refresh_requested = True
                    refresh_header(session, trigger=LifecycleTrigger.PERIODIC)
                    refresh_custom_summaries(session, trigger=LifecycleTrigger.PERIODIC)
                for index, pane in enumerate(session.panes):
                    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and pane.scheduler.due(
                        now=now
                    ):
                        refresh_requested = True
                        refresh(session, index, trigger=LifecycleTrigger.PERIODIC)
                deadline = animation_deadline(session)
                feedback_expired = (
                    session.copy_feedback.message is not None
                    and now >= session.copy_feedback.expires_at
                )
                copied_ranking_icon_expired = any(
                    isinstance(pane, TuiCustomPane)
                    and (
                        pane.copied_ranking_entry_id is not None
                        and now >= pane.copied_ranking_until
                        or (
                            pane.copied_ranking_all_until > 0
                            and now >= pane.copied_ranking_all_until
                        )
                    )
                    for pane in session.panes
                )
                if copied_ranking_icon_expired:
                    for pane in session.panes:
                        if not isinstance(pane, TuiCustomPane):
                            continue
                        if (
                            pane.copied_ranking_entry_id is not None
                            and now >= pane.copied_ranking_until
                        ):
                            pane.copied_ranking_entry_id = None
                        if (
                            pane.copied_ranking_all_until > 0
                            and now >= pane.copied_ranking_all_until
                        ):
                            pane.copied_ranking_all_until = 0.0
                cursor_tick = session.overlay_editor is not None and int(now * 2) != int(
                    (now - 0.1) * 2
                )
                if (
                    changed
                    or refresh_requested
                    or feedback_expired
                    or copied_ranking_icon_expired
                    or cursor_tick
                    or (deadline is not None and now >= deadline)
                ):
                    paint(
                        session,
                        animation_only=not (
                            changed
                            or refresh_requested
                            or feedback_expired
                            or copied_ranking_icon_expired
                            or cursor_tick
                        ),
                    )
                try:
                    event = raise_if_interrupt(
                        session, read_adjustment_event(session, session.decoder)
                    )
                except AdjustmentTimeout:
                    if session.help_overlay is not None:
                        session.help_overlay = None
                    _finish_ranking_search_editing(
                        session.panes[session.focused] if session.focused is not None else None
                    )
                    end_adjustment(session)
                    paint(session)
                    continue
                dispatch_event(session, event, now=now)
    except KeyboardInterrupt:
        return 0
    finally:
        for pane in session.panes:
            _shutdown_pane(pane)
        for summary in tuple(session.header.custom_summaries.values()):
            summary.scheduler.shutdown()
            summary.lifecycle.shutdown()
        session.header.scheduler.shutdown()
        session.header.lifecycle.shutdown()
        session.runtime.cancel()
        session.executor.shutdown(wait=False, cancel_futures=True)
        session.screen.finish()
        set_screen_cursor_visible(session, True)

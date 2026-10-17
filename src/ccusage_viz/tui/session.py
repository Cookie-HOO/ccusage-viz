from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.dashboard_layout import PaneLayout as ResolvedPaneLayout
from ccusage_viz.data_view import DashboardBodyView
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import OperationToken
from ccusage_viz.options import ChartPaneConfig, CustomChartPaneConfig, DashboardLaunch
from ccusage_viz.terminal import FramePainter
from ccusage_viz.terminal_ui import TransientFeedback
from ccusage_viz.tui.header import (
    _custom_dashboard_sources,
    _new_header,
    _reconcile_custom_dashboard_summaries,
)
from ccusage_viz.tui.layout import _dashboard_structure
from ccusage_viz.tui.models import (
    DashboardDatasetModalState,
    DashboardOverlayPlacement,
    HelpOverlayState,
    OverlayEditorState,
    OverlayHistoryState,
)
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui_input import InputDecoder
from ccusage_viz.tui_preset_manager import PresetManagerState


class TuiSession:
    def __init__(self, options: DashboardLaunch, translator: Translator) -> None:
        from ccusage_viz.tui.history import capture_dashboard_state

        self.options = options
        self.translator = translator
        self.runtime = build_query_runtime()
        self.panes = [
            _new_pane(
                self.options,
                pane_config,
                f"dashboard:pane:{index}"
                if isinstance(pane_config, (ChartPaneConfig, CustomChartPaneConfig))
                else None,
                self.runtime,
            )
            for index, pane_config in enumerate(self.options.panes)
        ]
        for index, pane in enumerate(self.panes):
            pane.pane_id = index
        self.next_pane_id = len(self.panes)
        self.header = _new_header(self.options, self.runtime)
        _reconcile_custom_dashboard_summaries(
            self.header, _custom_dashboard_sources(self.panes), now=time.monotonic()
        )
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ccusage-viz-tui")
        self.focused: int | None = None
        self.active_grid = self.options.host.grid
        self.active_layout = self.options.host.layout
        self.column_weights = self.options.host.column_weights
        self.row_weights = self.options.host.row_weights
        self.header_style = self.options.host.header_style
        self.dashboard_style = self.options.host.style
        self.dashboard_theme = self.options.host.theme
        self.divider_style, self.frame_style = _dashboard_structure(self.dashboard_style)
        self.grid_draft: str | None = None
        self.grid_error: str | None = None
        self.adjustment_mode: str | None = None
        self.adjustment_page = "quick"
        self.adjustment_timer: AdjustmentIdleTimer | None = None
        self.controls_hidden = False
        self.body_view: DashboardBodyView = "chart"
        self.dashboard_text_offset = 0
        self.dashboard_text_line_count = 0
        self.dashboard_text_visible_rows = 0
        self.chooser_overlay: tuple[int, str] | None = None
        self.dataset_modal: DashboardDatasetModalState | None = None
        self.preset_manager: PresetManagerState | None = None
        self.current_preset_key: str | None = None
        self.overlay_editor: OverlayEditorState | None = None
        self.overlay_history: OverlayHistoryState | None = None
        self.custom_logs_pane: int | None = None
        self.help_overlay: HelpOverlayState | None = None
        self.help_was_active = False
        self.last_click: tuple[int, float] | None = None
        self.scrollbar_drag: tuple[int, int] | None = None
        self.scrollbar_hovered_pane: int | None = None
        self.copy_feedback = TransientFeedback()
        self.manual_refresh_operations: set[OperationToken] = set()
        self.displayed_custom_warnings: set[tuple[str, str]] = set()
        self.last_successful_update: datetime | None = None
        self.last_size: tuple[int, int] | None = None
        self.pane_render_cache: dict[
            int, tuple[tuple[object, ...], str, tuple[DashboardOverlayPlacement, ...]]
        ] = {}
        self.screen = FramePainter(sys.stdout)
        self.decoder: InputDecoder
        self.history = DashboardHistory(capture_dashboard_state(self))
        self.displayed_layout: ResolvedPaneLayout | None = None
        self.displayed_header_rows = 0

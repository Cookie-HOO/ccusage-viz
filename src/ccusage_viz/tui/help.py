from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
from shutil import get_terminal_size
from typing import cast

from ccusage_viz.adjustment_timeout import HELP_IDLE_TIMEOUT_SECONDS, AdjustmentIdleTimer
from ccusage_viz.dashboard_layout import MIN_PANE_HEIGHT
from ccusage_viz.data_view import body_view_copy_kind
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.formatting import clip_width, display_width, pad_width, wrap_width
from ccusage_viz.options import MonitorConfig, is_monitor_ranking_style
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Frame, emphasize
from ccusage_viz.terminal_ui import controls_line, feedback_lines
from ccusage_viz.text_viewport import text_viewport_overflows
from ccusage_viz.tui.adjustments import (
    _adjustment_footer,
    _animation_adjustment_footer,
    _empty_pane_adjustment_footer,
    _global_adjustment_footer,
    _pane_adjustment_state,
    _pane_help_action_text,
    _pane_help_settings_actions,
    _text_view_footer,
)
from ccusage_viz.tui.custom_adjustments import (
    _accepted_custom_metric_help_node,
    _custom_adjustment_footer,
    _custom_pane_adjustment_actions,
)
from ccusage_viz.tui.datasets.chooser import _PANE_COMMANDS, _dataset_title
from ccusage_viz.tui.models import (
    HelpOverlayState,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    _pane_display_options,
)
from ccusage_viz.tui_input import KeyEvent, MouseEvent


def open_help(
    session: TuiSession,
    *,
    context: str = "dashboard",
    action: str | None = None,
    selected: str | None = None,
    dataset_id: str | None = None,
    chart_kind: str | None = None,
) -> None:
    from ccusage_viz.tui.painting import paint

    session.help_overlay = HelpOverlayState(
        AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS),
        session.adjustment_timer.remaining() if session.adjustment_timer is not None else None,
        context=context,
        action=action,
        selected=selected,
        dataset_id=dataset_id,
        chart_kind=chart_kind,
    )
    paint(session)


def close_help(session: TuiSession) -> None:
    assert session.help_overlay is not None
    remaining = session.help_overlay.adjustment_remaining
    session.help_overlay = None
    if session.adjustment_mode is not None and remaining is not None:
        session.adjustment_timer = AdjustmentIdleTimer.from_remaining(remaining)


def global_operations(session: TuiSession, width: int) -> str:
    return controls_line(
        session.translator.text("status.tui_global_operations"),
        width=width,
        color=session.dashboard_theme != "no-color",
    )


def preset_operations(session: TuiSession, width: int) -> str:
    return clip_width(session.translator.text("status.tui_preset_operations"), width)


def help_lines(session: TuiSession, width: int) -> tuple[str, ...]:
    mode = (
        "pane"
        if session.adjustment_mode == "pane"
        else "global"
        if session.adjustment_mode == "global"
        else "browse"
    )
    page = "quick" if session.adjustment_page == "quick" else "advanced"
    scheme = get_color_scheme(session.dashboard_theme)
    branch, last, pipe = (
        ("|- ", "\\- ", "|  ") if session.options.host.ascii else ("├─ ", "└─ ", "│  ")
    )
    active_icon = "* " if session.options.host.ascii else "● "
    selected_page_icon = "[x] " if session.options.host.ascii else "● "
    unselected_page_icon = "[ ] " if session.options.host.ascii else "○ "

    def tree_rows(prefix: str, continuation: str, value: str) -> tuple[str, ...]:
        available = max(1, width - display_width(prefix))
        wrapped = wrap_width(value, available)
        return tuple(
            (
                f"{(prefix if row_index == 0 else continuation)}{row}"
                for row_index, row in enumerate(wrapped)
            )
        )

    def tree_node(
        prefix: str, value: str, children: tuple[tuple[str, object], ...], *, is_last: bool
    ) -> tuple[str, ...]:
        connector = last if is_last else branch
        child_prefix = prefix + ("   " if is_last else pipe)
        rows = list(tree_rows(prefix + connector, child_prefix + "   ", value))
        for index, (child_value, child_children) in enumerate(children):
            rows.extend(
                tree_node(
                    child_prefix,
                    child_value,
                    cast(tuple[tuple[str, object], ...], child_children),
                    is_last=index == len(children) - 1,
                )
            )
        return tuple(rows)

    def mode_node(
        name: str, *, active: bool, enter: str, exit: str
    ) -> tuple[str, tuple[object, ...]]:
        return (
            f"{(active_icon if active else '')}{session.translator.text(name)}",
            ((enter, ()), (exit, ())),
        )

    def mode_pages() -> tuple[tuple[str, tuple[object, ...]], ...]:
        active_page = session.translator.text(f"status.tui_help_page_{page}")
        other_page = session.translator.text(
            f"status.tui_help_page_{('advanced' if page == 'quick' else 'quick')}"
        )
        return (
            (
                session.translator.text(
                    "status.tui_help_mode_pages",
                    active=selected_page_icon.rstrip(),
                    page=active_page,
                    other=unselected_page_icon.rstrip(),
                    other_page=other_page,
                ),
                (),
            ),
            (session.translator.text("status.tui_help_mode_pages_detail"), ()),
        )

    def help_heading(value: str) -> str:
        return emphasize(
            value, color=scheme.highlight, enabled=session.dashboard_theme != "no-color"
        )

    if session.help_overlay is not None and session.help_overlay.context != "dashboard":
        if session.help_overlay.context == "chooser":
            assert session.help_overlay.action is not None
            assert session.help_overlay.selected is not None
            sections = (
                (
                    "status.tui_help_section_selecting",
                    (
                        session.translator.text(f"status.tui_{session.help_overlay.action}_title"),
                        session.translator.text("status.tui_help_chooser_detail"),
                    ),
                ),
                (
                    "status.tui_help_section_options",
                    tuple(
                        session.translator.text(
                            "status.tui_help_labeled_option",
                            option=f"{('*' if session.options.host.ascii else '●')} {session.translator.text(f'label.pane_{item}')}"
                            if item == session.help_overlay.selected
                            else session.translator.text(f"label.pane_{item}"),
                            detail=session.translator.text(
                                f"status.tui_help_chooser_option_{item}"
                            ),
                        )
                        for item in _PANE_COMMANDS
                    ),
                ),
            )
            rows: list[str] = []
            for heading, values in sections:
                if rows:
                    rows.append("")
                rows.append(help_heading(session.translator.text(heading)))
                for index, value in enumerate(values):
                    rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
            return tuple(clip_width(line, width) for line in rows)
        elif session.help_overlay.context == "dataset-chooser":
            assert session.dataset_modal is not None
            modal = session.dataset_modal
            if modal.stage == "source" and modal.statuses:
                status = modal.statuses[modal.index]
                descriptor = status.registration.probe.descriptor
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (session.translator.text("status.tui_help_dataset_chooser"),),
                    ),
                    (
                        "status.tui_help_section_options",
                        (session.translator.text("status.tui_help_dataset_chooser_manage"),),
                    ),
                    (
                        "status.tui_help_section_selected",
                        (
                            session.translator.text(
                                "status.tui_help_dataset_chooser_selected",
                                name=_dataset_title(descriptor.dataset.title, session.translator),
                                version=descriptor.version,
                            ),
                            descriptor.dataset.description.zh_cn
                            if session.translator.language == "zh"
                            else descriptor.dataset.description.en,
                        ),
                    ),
                )
            else:
                assert modal.chart_kinds
                chart_kind = modal.chart_kinds[modal.index]
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (session.translator.text("status.tui_help_dataset_chart_chooser"),),
                    ),
                    (
                        "status.tui_help_section_options",
                        tuple(
                            session.translator.text(
                                "status.tui_help_labeled_option",
                                option=f"{('*' if session.options.host.ascii else '●')} {session.translator.text(f'label.pane_{item}')}"
                                if item == chart_kind
                                else session.translator.text(f"label.pane_{item}"),
                                detail=session.translator.text(
                                    f"status.tui_help_chooser_option_{item}"
                                ),
                            )
                            for item in modal.chart_kinds
                        ),
                    ),
                )
            rows = []
            for heading, values in sections:
                if rows:
                    rows.append("")
                rows.append(help_heading(session.translator.text(heading)))
                for index, value in enumerate(values):
                    rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
            rows.append("")
            rows.append(help_heading(session.translator.text("status.tui_help_section_policy")))
            policy = (
                session.translator.text("status.tui_help_dataset_policy"),
                session.translator.text("status.tui_help_idle_close"),
            )
            for index, value in enumerate(policy):
                rows.extend(tree_node("", value, (), is_last=index == len(policy) - 1))
            return tuple(clip_width(line, width) for line in rows)
        elif session.help_overlay.context == "catalog-browser":
            sections = (
                (
                    "status.tui_help_section_selecting",
                    (session.translator.text("status.tui_help_catalog_browser"),),
                ),
                (
                    "status.tui_help_section_options",
                    (session.translator.text("status.tui_help_catalog_columns"),),
                ),
                (
                    "status.tui_help_section_selected",
                    (session.translator.text("status.tui_help_catalog_selected"),),
                ),
            )
            rows = []
            for heading, values in sections:
                if rows:
                    rows.append("")
                rows.append(help_heading(session.translator.text(heading)))
                for index, value in enumerate(values):
                    rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
            rows.append("")
            rows.append(help_heading(session.translator.text("status.tui_help_section_policy")))
            rows.extend(
                tree_node(
                    "", session.translator.text("status.tui_help_idle_close"), (), is_last=True
                )
            )
            return tuple(clip_width(line, width) for line in rows)
        elif session.help_overlay.context == "editor":
            rows = [help_heading(session.translator.text("status.tui_help_section_controls"))]
            groups = editor_help_groups(dashboard=True)
            for index, group in enumerate(groups):
                rows.extend(
                    tree_node(
                        "",
                        session.translator.text(group.heading_key),
                        tuple(
                            (session.translator.text(item_key), ()) for item_key in group.item_keys
                        ),
                        is_last=index == len(groups) - 1,
                    )
                )
            return tuple(clip_width(line, width) for line in rows)
        else:
            context_nodes = (
                (
                    session.translator.text("status.tui_help_history_overlay"),
                    ((session.translator.text("status.tui_help_history_overlay_detail"), ()),),
                ),
            )
        rows = [help_heading(session.translator.text("status.tui_help_section_controls"))]
        for value, children in context_nodes:
            rows.extend(tree_node("", value, children, is_last=False))
        policy_children = [
            (
                session.translator.text(
                    "status.tui_help_tip_ascii"
                    if session.options.host.ascii
                    else "status.tui_help_tip"
                ),
                (),
            )
        ]
        if session.help_overlay.context in {"editor", "history"}:
            policy_children.append((session.translator.text("status.tui_help_animation_hint"), ()))
        policy_children.append((session.translator.text("status.tui_help_idle_close"), ()))
        rows.append("")
        rows.append(help_heading(session.translator.text("status.tui_help_section_policy")))
        for index, (value, children) in enumerate(policy_children):
            rows.extend(tree_node("", value, children, is_last=index == len(policy_children) - 1))
        return tuple(clip_width(line, width) for line in rows)
    text_navigation: tuple[tuple[str, tuple[object, ...]], ...] = ()
    if mode == "browse" and session.body_view != "chart":
        text_children: list[tuple[str, tuple[object, ...]]] = []
        if text_viewport_overflows(
            line_count=session.dashboard_text_line_count,
            visible_rows=session.dashboard_text_visible_rows,
        ):
            text_children.append((session.translator.text("status.tui_help_text_scroll"), ()))
        text_children.append((session.translator.text("status.tui_help_text_copy"), ()))
        text_navigation = (
            (session.translator.text("status.tui_help_text_navigation"), tuple(text_children)),
        )
    elif mode == "pane" and session.focused is not None:
        focused_pane = session.panes[session.focused]
        if (
            isinstance(focused_pane, (TuiChartPane, TuiCustomPane))
            and focused_pane.body_view != "chart"
        ):
            text_children = [(session.translator.text("status.tui_help_content_view"), ())]
            if text_viewport_overflows(
                line_count=focused_pane.text_line_counts.get(focused_pane.body_view, 0),
                visible_rows=focused_pane.text_visible_rows.get(focused_pane.body_view, 0),
            ):
                text_children.append((session.translator.text("status.tui_help_text_scroll"), ()))
            if body_view_copy_kind(focused_pane.body_view) is not None:
                text_children.append((session.translator.text("status.tui_help_text_copy"), ()))
            text_navigation = (
                (session.translator.text("status.tui_help_text_navigation"), tuple(text_children)),
            )
    current_metric_node = None
    common_children = [
        (session.translator.text("status.tui_help_history"), ()),
        (session.translator.text("status.tui_help_help"), ()),
    ]
    structure_children = [
        (session.translator.text("status.tui_help_content_view"), ()),
        (session.translator.text("status.tui_help_content_replace"), ()),
        (session.translator.text("status.tui_help_content_insert"), ()),
        (session.translator.text("status.tui_help_structure_move"), ()),
        (session.translator.text("status.tui_help_structure_select"), ()),
        (session.translator.text("status.tui_help_structure_width"), ()),
        (session.translator.text("status.tui_help_structure_height"), ()),
    ]
    if mode == "browse":
        browse_children = [
            (session.translator.text("status.tui_help_browse_view"), ()),
            (session.translator.text("status.tui_help_browse_pane"), ()),
            (session.translator.text("status.tui_help_browse_dashboard"), ()),
            (session.translator.text("status.tui_help_browse_presets"), ()),
        ]
        if session.body_view == "chart":
            browse_children[:0] = [
                (session.translator.text("status.tui_help_browse_refresh"), ()),
                (session.translator.text("status.tui_help_controls"), ()),
                (
                    session.translator.text("status.tui_help_intervals_dashboard"),
                    (
                        (session.translator.text("status.tui_help_interval_historical"), ()),
                        (session.translator.text("status.tui_help_interval_monitor_dashboard"), ()),
                        (session.translator.text("status.tui_help_interval_header"), ()),
                    ),
                ),
            ]
        control_nodes = (
            (session.translator.text("status.tui_help_browse"), tuple(browse_children)),
            (session.translator.text("status.tui_help_common"), tuple(common_children)),
            *text_navigation,
        )
    elif mode == "pane":
        assert session.focused is not None
        focused_pane = session.panes[session.focused]
        if len(session.panes) > 1:
            structure_children.insert(
                3, (session.translator.text("status.tui_help_content_delete"), ())
            )
        parameter_children: list[tuple[str, tuple[object, ...]]] = []
        if isinstance(focused_pane, TuiChartPane) and focused_pane.body_view == "chart":
            chart = _pane_display_options(focused_pane).chart
            parameter_children.extend(
                (
                    (_pane_help_action_text(page_name, action, session.translator), ())
                    for page_name, action in _pane_help_settings_actions(
                        chart.kind,
                        session.translator,
                        chart=chart,
                        attachment_available=isinstance(chart, MonitorConfig)
                        and is_monitor_ranking_style(chart.presentation.style)
                        and (focused_pane.attachment is not None),
                    )
                )
            )
            if isinstance(chart, MonitorConfig):
                parameter_children.append(
                    (session.translator.text("status.tui_help_interval_monitor"), ())
                )
        elif isinstance(focused_pane, TuiCustomPane) and focused_pane.body_view == "chart":
            parameter_children.extend(
                (_pane_help_action_text(page_name, action, session.translator), ())
                for page_name in ("quick", "advanced")
                for action in _custom_pane_adjustment_actions(
                    focused_pane, page_name, session.translator
                )
            )
        elif isinstance(focused_pane, TuiAnimationPane):
            parameter_children.extend(
                (
                    (session.translator.text("status.tui_help_animation_position"), ()),
                    (session.translator.text("status.tui_help_animation_theme"), ()),
                    (session.translator.text("status.tui_help_animation_style"), ()),
                    (session.translator.text("status.tui_help_animation_move"), ()),
                    (session.translator.text("status.tui_help_animation_reset"), ()),
                    (session.translator.text("status.tui_help_animation_edit"), ()),
                    (session.translator.text("status.tui_help_animation_interval"), ()),
                    (
                        session.translator.text("status.tui_help_animation_history"),
                        ((session.translator.text("status.tui_help_history_overlay_detail"), ()),),
                    ),
                    (session.translator.text("status.tui_help_animation_schedule"), ()),
                )
            )
            structure_children.pop(0)
        current_metric_node = (
            _accepted_custom_metric_help_node(focused_pane, session.translator)
            if isinstance(focused_pane, TuiCustomPane)
            else None
        )
        if not parameter_children:
            parameter_children.append(
                (session.translator.text("status.tui_help_pane_settings_empty"), ())
            )
        control_nodes = (
            (session.translator.text("status.tui_help_mode"), mode_pages()),
            (session.translator.text("status.tui_help_pane_settings"), tuple(parameter_children)),
            (session.translator.text("status.tui_help_pane_structure"), tuple(structure_children)),
            (session.translator.text("status.tui_help_common"), tuple(common_children)),
            *text_navigation,
        )
    else:
        control_nodes = (
            (session.translator.text("status.tui_help_mode"), ()),
            (
                session.translator.text("status.tui_help_dashboard_settings"),
                (
                    (session.translator.text("status.tui_help_dashboard_theme"), ()),
                    (session.translator.text("status.tui_help_dashboard_style"), ()),
                    (session.translator.text("status.tui_help_dashboard_header"), ()),
                    (session.translator.text("status.tui_help_dashboard_summary"), ()),
                    (
                        session.translator.text("status.tui_help_dashboard_layout"),
                        ((session.translator.text("status.tui_help_layout_chooser"), ()),),
                    ),
                    (
                        session.translator.text("status.tui_help_dashboard_grid"),
                        ((session.translator.text("status.tui_help_grid_editor"), ()),),
                    ),
                ),
            ),
            (session.translator.text("status.tui_help_common"), tuple(common_children)),
        )
    mode_nodes = (
        mode_node(
            "status.tui_help_browse_label",
            active=mode == "browse",
            enter=session.translator.text("status.tui_help_browse_enter"),
            exit=session.translator.text("status.tui_help_browse_exit"),
        ),
        mode_node(
            "status.tui_help_pane_label",
            active=mode == "pane",
            enter=session.translator.text("status.tui_help_pane_enter"),
            exit=session.translator.text("status.tui_help_pane_exit"),
        ),
        mode_node(
            "status.tui_help_global_label",
            active=mode == "global",
            enter=session.translator.text("status.tui_help_global_enter"),
            exit=session.translator.text("status.tui_help_global_exit"),
        ),
    )
    sections = (
        ("status.tui_help_section_modes", mode_nodes),
        *(
            (("status.tui_help_current_metric", current_metric_node[1]),)
            if current_metric_node is not None
            else ()
        ),
        ("status.tui_help_section_controls", control_nodes),
    )
    rows: list[str] = []
    for heading, nodes in sections:
        if rows:
            rows.append("")
        rows.append(help_heading(session.translator.text(heading)))
        for index, (value, children) in enumerate(nodes):
            rows.extend(
                tree_node(
                    "",
                    value,
                    cast(tuple[tuple[str, object], ...], children),
                    is_last=index == len(nodes) - 1,
                )
            )
    policy_children = [
        (
            session.translator.text(
                "status.tui_help_tip_ascii" if session.options.host.ascii else "status.tui_help_tip"
            ),
            (),
        )
    ]
    if mode == "browse":
        policy_children.extend(
            (
                (session.translator.text("status.tui_help_browse_hint"), ()),
                (session.translator.text("status.tui_help_schedule_coalesce"), ()),
            )
        )
    elif (
        mode == "pane"
        and session.focused is not None
        and isinstance(session.panes[session.focused], TuiAnimationPane)
    ):
        policy_children.append((session.translator.text("status.tui_help_animation_hint"), ()))
    focused_pane = session.panes[session.focused] if session.focused is not None else None
    if (
        mode == "pane"
        and isinstance(focused_pane, TuiChartPane)
        and (focused_pane.body_view == "chart")
        and (not isinstance(_pane_display_options(focused_pane).chart, MonitorConfig))
    ):
        policy_children.extend(
            (
                (
                    session.translator.text("status.tui_help_summary_scope"),
                    (
                        (session.translator.text("status.tui_help_summary_scope_fixed"), ()),
                        (session.translator.text("status.tui_help_summary_scope_filters"), ()),
                    ),
                ),
                (
                    session.translator.text("status.tui_help_summary_comparisons"),
                    (
                        (session.translator.text("status.tui_help_summary_comparisons_day"), ()),
                        (
                            session.translator.text(
                                "status.tui_help_summary_comparisons_month_quarter"
                            ),
                            (),
                        ),
                        (session.translator.text("status.tui_help_summary_comparisons_year"), ()),
                    ),
                ),
            )
        )
    policy_children.append((session.translator.text("status.tui_help_idle_close"), ()))
    rows.append("")
    rows.append(help_heading(session.translator.text("status.tui_help_section_policy")))
    for index, (value, children) in enumerate(policy_children):
        rows.extend(tree_node("", value, children, is_last=index == len(policy_children) - 1))
    return tuple(clip_width(line, width) for line in rows)


def help_panel(session: TuiSession, size_columns: int, size_lines: int) -> tuple[str, ...]:
    content_width = max(1, min(size_columns - 4, 100))
    lines = help_lines(session, content_width)
    context = RenderContext(
        content_width,
        1,
        session.translator,
        color=session.dashboard_theme != "no-color",
        ascii=session.options.host.ascii,
        color_scheme=session.dashboard_theme,
    )
    scheme = get_color_scheme(session.dashboard_theme)
    editor_help = session.help_overlay is not None and session.help_overlay.context == "editor"
    title = clip_width(
        styled_text(
            session.translator.text(
                "status.tui_help_editor_title" if editor_help else "status.tui_help_title"
            ),
            scheme.highlight,
            context,
            bold=True,
        ),
        content_width,
    )
    footer = clip_width(
        styled_text(
            session.translator.text(
                "status.tui_help_editor_close" if editor_help else "status.tui_help_close"
            ),
            scheme.other,
            context,
            dim=True,
        ),
        content_width,
    )
    panel_width = max(
        1, min(size_columns, max(*(display_width(line) for line in (*lines, title, footer)), 1) + 4)
    )
    body_rows = max(1, size_lines - 5)
    max_offset = max(0, len(lines) - body_rows)
    offset = min(
        session.help_overlay.scroll_offset if session.help_overlay is not None else 0, max_offset
    )
    visible = lines[offset : offset + body_rows]
    border = "-" * max(0, panel_width - 2)
    inner_width = max(0, panel_width - 4)
    rows = ["+" + border + "+", "| " + pad_width(title, inner_width) + " |"]
    rows.extend("| " + pad_width(line, inner_width) + " |" for line in visible)
    rows.append("|" + "-" * max(0, panel_width - 2) + "|")
    rows.append("| " + pad_width(footer, inner_width) + " |")
    rows.append("+" + border + "+")
    return tuple(rows)


def help_panel_bounds(
    session: TuiSession, size_columns: int, size_lines: int
) -> tuple[int, int, int, int]:
    panel = help_panel(session, size_columns, size_lines)
    width = max((display_width(line) for line in panel), default=1)
    height = len(panel)
    return ((size_columns - width) // 2 + 1, max(1, (size_lines - height) // 2 + 1), width, height)


def help_frame(session: TuiSession, size_columns: int, size_lines: int) -> Frame:
    panel = help_panel(session, size_columns, size_lines)
    x, y, panel_width, _ = help_panel_bounds(session, size_columns, size_lines)
    rows = ["" for _ in range(size_lines)]
    for offset, row in enumerate(panel):
        row_index = y - 1 + offset
        if 0 <= row_index < len(rows):
            rows[row_index] = " " * max(0, x - 1) + pad_width(row, panel_width)
    return Frame(tuple(rows))


def process_help_event(session: TuiSession, event: object) -> None:
    from ccusage_viz.tui.painting import paint

    assert session.help_overlay is not None
    if isinstance(event, KeyEvent) and event.value in {"h", "\x08", "\x1b", "\r", "\n"}:
        close_help(session)
    elif isinstance(event, KeyEvent) and event.value in {"\x1b[A", "\x1b[B"}:
        delta = -1 if event.value == "\x1b[A" else 1
        max_offset = max(
            0, len(help_lines(session, get_terminal_size().columns)) - get_terminal_size().lines + 5
        )
        session.help_overlay.scroll_offset = min(
            max(0, session.help_overlay.scroll_offset + delta), max_offset
        )
    elif isinstance(event, MouseEvent) and event.pressed:
        size = get_terminal_size()
        x, y, width, height = help_panel_bounds(session, size.columns, size.lines)
        if not (x <= event.x < x + width and y <= event.y < y + height):
            close_help(session)
    paint(session)


def _controls(session: TuiSession) -> tuple[str, ...]:
    width = get_terminal_size().columns
    if session.help_overlay is not None:
        return ()
    if session.grid_draft is not None:
        rows = [
            clip_width(
                session.translator.text("status.tui_layout_prompt", value=session.grid_draft), width
            )
        ]
        if session.grid_error is not None:
            rows.append(clip_width(session.grid_error, width))
        rows.append(clip_width(session.translator.text("status.tui_layout_controls"), width))
        return tuple(rows)
    if session.adjustment_mode == "pane" and session.focused is not None:
        pane = session.panes[session.focused]
        if isinstance(pane, TuiAnimationPane):
            return (
                *_animation_adjustment_footer(
                    pane,
                    session.adjustment_page,
                    session.translator,
                    width,
                    color=session.dashboard_theme != "no-color",
                ),
                global_operations(session, width),
            )
        if isinstance(pane, TuiEmptyPane):
            return (
                *_empty_pane_adjustment_footer(
                    session.translator, width, color=session.dashboard_theme != "no-color"
                ),
                global_operations(session, width),
            )
        if isinstance(pane, TuiCustomPane):
            if pane.body_view != "chart":
                return (
                    *_text_view_footer(
                        pane.body_view,
                        session.translator,
                        width,
                        line_count=pane.text_line_counts.get(pane.body_view, 0),
                        visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                    ),
                    global_operations(session, width),
                )
            return (
                *_custom_adjustment_footer(
                    pane,
                    session.adjustment_page,
                    session.translator,
                    width,
                    color=session.dashboard_theme != "no-color",
                ),
                global_operations(session, width),
            )
        if pane.body_view != "chart":
            return (
                *_text_view_footer(
                    pane.body_view,
                    session.translator,
                    width,
                    line_count=pane.text_line_counts.get(pane.body_view, 0),
                    visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                ),
                global_operations(session, width),
            )
        state = session.grid_error or _pane_adjustment_state(
            pane, session.adjustment_page, session.translator
        )
        return (
            *_adjustment_footer(
                state,
                _pane_display_options(pane).chart.kind,
                session.adjustment_page,
                pane.body_view,
                session.translator,
                width,
                chart=_pane_display_options(pane).chart,
                attachment_available=session.adjustment_page == "advanced"
                and isinstance(_pane_display_options(pane).chart, MonitorConfig)
                and is_monitor_ranking_style(_pane_display_options(pane).chart.presentation.style)
                and (pane.attachment is not None),
                color=session.dashboard_theme != "no-color",
            ),
            global_operations(session, width),
        )
    if session.adjustment_mode == "global":
        state = session.translator.text(
            "status.tui_current_state",
            runtime=session.translator.text("status.tui_running"),
            settings=f"{session.active_layout or session.active_grid} · {session.dashboard_theme} · {session.dashboard_style} · {session.header_style} · {session.header.summary_period}",
        )
        return (
            *_global_adjustment_footer(
                state=session.grid_error or state, translator=session.translator, width=width
            ),
            global_operations(session, width),
        )
    if session.body_view != "chart":
        return (
            *_text_view_footer(
                session.body_view,
                session.translator,
                width,
                line_count=session.dashboard_text_line_count,
                visible_rows=session.dashboard_text_visible_rows,
            ),
            global_operations(session, width),
        )
    if session.controls_hidden:
        return ()
    context = session.grid_error or session.translator.text(
        f"status.tui_{session.body_view.replace('-', '_')}_controls"
    )
    return (
        clip_width(context, width),
        preset_operations(session, width),
        global_operations(session, width),
    )


def controls(session: TuiSession) -> tuple[str, ...]:
    return (
        ()
        if session.controls_hidden or get_terminal_size().lines < MIN_PANE_HEIGHT
        else _controls(session)
    )


def notices(session: TuiSession) -> tuple[str, ...]:
    feedback = feedback_lines(
        session.copy_feedback,
        width=get_terminal_size().columns,
        color=session.dashboard_theme != "no-color",
        now=time.monotonic(),
    )
    manual = (
        (session.translator.text("status.tui_refreshing"),)
        if session.manual_refresh_operations
        else ()
    )
    return (*manual, *feedback)

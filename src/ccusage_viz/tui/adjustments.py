from __future__ import annotations

from ccusage_viz.animation import animation_style_choices
from ccusage_viz.animation_host.runtime import _format_overlay_interval
from ccusage_viz.data_view import BodyView
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    MonitorConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
    is_monitor_ranking_style,
)
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import FramePainter  # noqa: F401 - retained test injection seam
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows
from ccusage_viz.text_viewport import text_viewport_overflows
from ccusage_viz.tui.controls import (
    _ANIMATION_PANE_CONTENT_ACTIONS,
    _COMMON_PANE_ADVANCED_ACTIONS,
    _COMMON_PANE_QUICK_ACTIONS,
    _PANE_POSITION_ACTIONS,
    _localized_actions,
    _management_row,
    _pane_content_actions,
    _pane_management_divider,
)
from ccusage_viz.tui.models import TuiAnimationPane, TuiChartPane, _pane_display_options
from ccusage_viz.tui_input import read_event  # noqa: F401 - retained test injection seam

_PANE_QUICK_ACTIONS = {
    "timeline": (("p/P", "period"), ("g/G", "granularity"), ("b/B", "group"), ("+/-", "top")),
    "calendar": (("p/P", "period"),),
    "stack": (("p/P", "period"), ("g/G", "granularity"), ("b/B", "group"), ("+/-", "top")),
    "ranking": (("p/P", "period"), ("b/B", "group"), ("+/-", "top")),
    "monitor": (("w", "window"), ("b/B", "group"), ("+/-", "top")),
}

_PANE_ADVANCED_ACTIONS = {
    "timeline": (("o", "other"), ("l", "legend"), ("k", "weekdays")),
    "calendar": (),
    "stack": (("o", "other"), ("c", "cache"), ("l", "legend"), ("k", "weekdays")),
    "ranking": (("o", "other"),),
    "monitor": (("l", "legend"),),
}

_GLOBAL_ACTIONS = (
    ("t/T", "theme"),
    ("s/S", "style"),
    ("H", "header"),
    ("p/P", "summary"),
    ("z", "layout"),
)


def _project_grouping_available(chart: object | None) -> bool:
    return (
        isinstance(chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig))
        and chart.by == "project"
    )


def _pane_adjustment_bindings(
    command: str,
    page: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Return the state-aware, locale-independent bindings for a Pane page."""

    actions = (
        (*_PANE_QUICK_ACTIONS[command], *_COMMON_PANE_QUICK_ACTIONS)
        if page == "quick"
        else (*_PANE_ADVANCED_ACTIONS[command], *_COMMON_PANE_ADVANCED_ACTIONS)
    )
    visible = tuple(
        (key, label)
        for key, label in actions
        if not (
            isinstance(chart, MonitorConfig)
            and is_monitor_ranking_style(chart.presentation.style)
            and key == "w"
        )
        and not (isinstance(chart, StackConfig) and chart.by != "composition" and key == "c")
    )
    if (
        isinstance(chart, MonitorConfig)
        and chart.presentation.style == "cumulative-bars"
        and page == "quick"
    ):
        visible = (("w", "window"), ("g", "granularity"), *visible[1:])
    if attachment_available and page == "advanced":
        visible = (*visible, ("t/T", "animation_theme"), ("s/S", "animation_style"))
    return visible


def _pane_adjustment_actions(
    command: str,
    page: str,
    translator: Translator,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[AdjustmentAction, ...]:
    return _localized_actions(
        _pane_adjustment_bindings(
            command,
            page,
            chart=chart,
            attachment_available=attachment_available,
        ),
        translator,
    )


def _adjustment_controls(
    command: str, page: str, translator: Translator, *, chart: object | None = None
) -> str:
    return " · ".join(
        action.text for action in _pane_adjustment_actions(command, page, translator, chart=chart)
    )


def _adjustment_page_keys(
    command: str,
    page: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> frozenset[str]:
    """Return every individual key exposed by the current adjustment page."""

    return frozenset(
        character
        for binding, _label in _pane_adjustment_bindings(
            command,
            page,
            chart=chart,
            attachment_available=attachment_available,
        )
        for character in binding
        if character not in {"/", " "}
    )


def _adjustment_target_page(
    command: str,
    current_page: str,
    key: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> str | None:
    """Resolve an unambiguous Dashboard Pane adjustment shortcut target page."""

    other_page = "advanced" if current_page == "quick" else "quick"
    if key in _adjustment_page_keys(
        command,
        current_page,
        chart=chart,
        attachment_available=attachment_available,
    ):
        return current_page
    if key in _adjustment_page_keys(
        command,
        other_page,
        chart=chart,
        attachment_available=attachment_available,
    ):
        return other_page
    return None


def _adjustment_key_supported(
    command: str,
    page: str,
    key: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> bool:
    return key in _adjustment_page_keys(
        command,
        page,
        chart=chart,
        attachment_available=attachment_available,
    )


def _query_affecting_adjustment(command: str, key: str) -> bool:
    """Compatibility helper for key-only callers.

    Runtime paths compare complete configurations through
    :func:`historical_replacement_required` instead.
    """
    return (
        key in {"p", "P"}
        or (key in {"b", "B"} and command in {"timeline", "stack", "ranking", "monitor"})
        or (command == "monitor" and key == "w")
    )


def _text_view_footer(
    body_view: BodyView,
    translator: Translator,
    width: int,
    *,
    line_count: int,
    visible_rows: int,
) -> tuple[str, ...]:
    """Render the always-visible, read-only footer for a text body view."""
    scroll = (
        f"↑/↓ {translator.text('status.text_scroll')} · "
        f"Home {translator.text('status.text_top')} · "
        f"e {translator.text('status.text_end')} · "
        if text_viewport_overflows(line_count=line_count, visible_rows=visible_rows)
        else ""
    )
    return (
        clip_width(
            f"{scroll}y {translator.text('label.adjust_copy')} · "
            f"v/V {translator.text('label.adjust_view')}",
            width,
        ),
    )


def _pane_help_settings_actions(
    command: str,
    translator: Translator,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[tuple[str, AdjustmentAction], ...]:
    """Return every current settings binding with its effective adjustment page."""
    return tuple(
        (page, action)
        for page in ("quick", "advanced")
        for action in _pane_adjustment_actions(
            command,
            page,
            translator,
            chart=chart,
            attachment_available=attachment_available,
        )
    )


def _pane_help_action_text(page: str, action: AdjustmentAction, translator: Translator) -> str:
    detail_labels = (
        "period",
        "granularity",
        "group",
        "top",
        "density",
        "theme",
        "style",
        "other",
        "legend",
        "weekdays",
        "cache",
        "filters",
        "window",
        "animation_theme",
        "animation_style",
    )
    detail_labels_by_action = {
        translator.text(f"label.adjust_{label}"): label for label in detail_labels
    }
    detail_label = detail_labels_by_action.get(action.label)
    detail = (
        translator.text(f"status.tui_help_parameter_{detail_label}")
        if detail_label is not None
        else action.label
    )
    return translator.text(f"status.tui_help_parameter_{page}", action=action.text, detail=detail)


_ANIMATION_PANE_QUICK_BINDINGS = (
    ("p/P", "overlay_position"),
    ("t/T", "animation_theme"),
    ("s/S", "animation_style"),
)

_ANIMATION_PANE_ADVANCED_BINDINGS = (
    ("h/j/k/l", "overlay_move"),
    ("0", "overlay_reset"),
    ("e", "overlay_edit"),
    ("i", "overlay_interval"),
    ("L", "overlay_history"),
)


def _animation_pane_adjustment_keys(page: str) -> frozenset[str]:
    """Return individual non-global animation Pane adjustment keys."""

    bindings = (
        _ANIMATION_PANE_QUICK_BINDINGS if page == "quick" else _ANIMATION_PANE_ADVANCED_BINDINGS
    )
    return frozenset(
        character
        for binding, _label in bindings
        if binding != "Space"
        for character in binding
        if character not in {"/", " "}
    )


def _animation_adjustment_target_page(current_page: str, key: str) -> str | None:
    """Resolve an unambiguous Dashboard Animation Pane adjustment shortcut."""

    other_page = "advanced" if current_page == "quick" else "quick"
    if key in _animation_pane_adjustment_keys(current_page):
        return current_page
    if key in _animation_pane_adjustment_keys(other_page):
        return other_page
    return None


def _animation_pane_adjustment_actions(
    page: str, translator: Translator
) -> tuple[AdjustmentAction, ...]:
    bindings = (
        _ANIMATION_PANE_QUICK_BINDINGS if page == "quick" else _ANIMATION_PANE_ADVANCED_BINDINGS
    )
    return tuple(
        AdjustmentAction(binding, translator.text(f"adjustment.{label}"), priority)
        for priority, (binding, label) in enumerate(bindings)
    )


def _empty_pane_adjustment_footer(
    translator: Translator,
    width: int,
    *,
    color: bool = False,
) -> tuple[str, ...]:
    """Render Dashboard-only management controls for an unconfigured pane."""

    return (
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _ANIMATION_PANE_CONTENT_ACTIONS,
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _animation_adjustment_footer(
    pane: TuiAnimationPane,
    page: str,
    translator: Translator,
    width: int,
    *,
    color: bool = False,
) -> tuple[str, ...]:
    actions = _animation_pane_adjustment_actions(page, translator)
    shared = adjustment_rows(
        translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else (
                "status.animation_adjust_advanced_command"
                if pane.overlay.config.command is not None
                else "status.animation_adjust_advanced"
            ),
            style=pane.session.spec.display_name,
            style_index=animation_style_choices("pane").index(pane.session.spec.style) + 1,
            style_count=len(animation_style_choices("pane")),
            theme=pane.session.theme,
            theme_index=COLOR_SCHEMES.index(pane.session.theme) + 1,
            theme_count=len(COLOR_SCHEMES),
            position=pane.overlay.config.position,
            offset_x=pane.overlay.config.offset_x,
            offset_y=pane.overlay.config.offset_y,
            interval=_format_overlay_interval(pane.overlay.config.interval),
        ),
        translator.text(f"adjustment.page_{page}"),
        actions,
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _ANIMATION_PANE_CONTENT_ACTIONS,
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _adjustment_footer(
    state: str,
    command: str,
    page: str,
    body_view: BodyView,
    translator: Translator,
    width: int,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
    color: bool = False,
) -> tuple[str, ...]:
    shared = adjustment_rows(
        state,
        translator.text(f"status.tui_adjust_{page}"),
        _pane_adjustment_actions(
            command,
            page,
            translator,
            chart=chart,
            attachment_available=attachment_available,
        ),
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _pane_content_actions(body_view),
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _pane_adjustment_state(pane: TuiChartPane, page: str, translator: Translator) -> str:
    chart = _pane_display_options(pane).chart
    if page == "quick":
        settings_parts = [
            chart.kind,
            chart.presentation.density,
            chart.presentation.theme,
            chart.presentation.style,
        ]
        if isinstance(chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig)):
            settings_parts.extend(
                (
                    f"Group {chart.by or translator.text('label.all')}",
                    f"Top {chart.top or translator.text('label.all')}",
                )
            )
        settings_parts.append(pane.body_view)
        settings = " · ".join(settings_parts)
    else:
        advanced: list[str] = []
        if isinstance(chart, (TimelineConfig, StackConfig, RankingConfig)):
            advanced.append(f"Other {chart.other}")
        if isinstance(chart, (TimelineConfig, StackConfig)):
            advanced.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        if isinstance(chart, StackConfig) and chart.by == "composition":
            advanced.insert(0, f"Cache {chart.cache}")
        if isinstance(chart, MonitorConfig):
            advanced.append(f"Legend {chart.presentation.legend}")
            if is_monitor_ranking_style(chart.presentation.style) and pane.attachment is not None:
                advanced.append(
                    translator.text(
                        "status.monitor_attachment_settings",
                        style=(
                            pane.attachment.spec.display_name
                            if pane.attachment_enabled
                            else translator.text("label.animation_none")
                        ),
                        theme=pane.attachment.theme,
                    ).lstrip(" ·")
                )
        settings = " · ".join(advanced)
    if not settings:
        return translator.text("status.tui_running")
    return translator.text(
        "status.tui_current_state",
        runtime=translator.text("status.tui_running"),
        settings=settings,
    )


def _global_adjustment_footer(
    *,
    state: str,
    translator: Translator,
    width: int,
) -> tuple[str, str]:
    actions = _localized_actions(_GLOBAL_ACTIONS, translator)
    label = translator.text("status.tui_adjust_quick")
    prefix = f"{label}：" if any(ord(char) > 127 for char in label) else f"{label}: "
    action_row = " · ".join(
        (*(_action.text for _action in actions), translator.text("status.tui_finish_keys"))
    )
    return clip_width(state, width), clip_width(prefix + action_row, width)


def _adjustment_target(focused: int | None, key: str, pane_count: int) -> int | None:
    if key == "\x1b":
        return None
    if focused is None:
        return 0 if key == "m" and pane_count else None
    if key == "\t":
        return (focused + 1) % pane_count
    return focused


_CUSTOM_PANE_KINDS = ("timeline", "stack", "calendar", "ranking")

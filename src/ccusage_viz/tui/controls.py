from __future__ import annotations

from ccusage_viz.data_view import BodyView, body_view_copy_kind
from ccusage_viz.formatting import clip_width, display_width
from ccusage_viz.i18n import Translator
from ccusage_viz.terminal_ui import AdjustmentAction


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


_COMMON_PANE_QUICK_ACTIONS = (
    ("d/D", "density"),
    ("t/T", "theme"),
    ("s/S", "style"),
)

_COMMON_PANE_ADVANCED_ACTIONS = (("f", "filters"),)

_PANE_CONTENT_ACTIONS = (
    ("v", "view"),
    ("r", "replace"),
    ("N", "insert_before"),
    ("n", "insert_after"),
    ("x", "delete"),
)

_ANIMATION_PANE_CONTENT_ACTIONS = (
    ("r", "replace"),
    ("N", "insert_before"),
    ("n", "insert_after"),
    ("x", "delete"),
)

_PANE_POSITION_ACTIONS = (
    ("[", "previous"),
    ("]", "next"),
    ("↑/↓/←/→ / Tab", "select_pane"),
    ("{ / }", "width"),
    ("J / K", "height"),
)


def _localized_actions(
    actions: tuple[tuple[str, str], ...], translator: Translator
) -> tuple[AdjustmentAction, ...]:
    return tuple(
        AdjustmentAction(key, translator.text(f"label.adjust_{label}"), priority)
        for priority, (key, label) in enumerate(actions)
    )


def _pane_content_actions(body_view: BodyView) -> tuple[tuple[str, str], ...]:
    if body_view_copy_kind(body_view) is None:
        return _PANE_CONTENT_ACTIONS
    return (*_PANE_CONTENT_ACTIONS, ("y", "copy"))


def _pane_management_divider(translator: Translator, width: int, *, color: bool) -> str:
    """Render the Dashboard Pane section boundary above scoped actions."""

    divider = translator.text("status.tui_pane_management_divider")
    return clip_width(f"\x1b[1m{divider}\x1b[0m" if color else divider, width)


def _management_row(
    label: str,
    actions: tuple[tuple[str, str], ...],
    translator: Translator,
    width: int,
) -> str:
    localized = _localized_actions(actions, translator)
    separator = " · "

    def compose(visible: tuple[AdjustmentAction, ...]) -> str:
        omitted = len(localized) - len(visible)
        parts = [action.text for action in visible]
        if omitted:
            parts.append(f"…(+{omitted})")
        return f"{label}: {separator.join(parts)}"

    visible = localized
    while visible and display_width(compose(visible)) > width:
        visible = visible[:-1]
    return clip_width(compose(visible), width)

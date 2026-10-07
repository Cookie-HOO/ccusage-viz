from __future__ import annotations

from collections.abc import Callable
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import HELP_IDLE_TIMEOUT_SECONDS, AdjustmentIdleTimer, AdjustmentTimeout
from ccusage_viz.i18n import Translator
from ccusage_viz.terminal import compose_frame
from ccusage_viz.terminal_ui import controls_line


def run_standalone_help(
    screen: object,
    translator: Translator,
    *,
    color: bool,
    read_key: Callable[[float], str | None],
) -> None:
    """Show the shared standalone browse Help until closed or idle."""
    timer = AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS)
    while True:
        size = get_terminal_size()
        body = "\n".join(
            (
                translator.text("status.standalone_help_browse"),
                translator.text("status.standalone_help_text"),
                translator.text("status.standalone_help_adjust"),
                translator.text("status.standalone_help_policy"),
            )
        )
        screen.paint(
            compose_frame(
                body,
                translator.text("status.standalone_help_title"),
                controls_line(
                    translator.text("status.standalone_help_close"), width=size.columns, color=color
                ),
                height=size.lines,
            )
        )
        key = read_key(min(0.1, timer.remaining()))
        if key is None:
            try:
                timer.check()
            except AdjustmentTimeout:
                return
            continue
        if key in {"h", "\x1b", "\r", "\n"}:
            return
        timer.record_input()

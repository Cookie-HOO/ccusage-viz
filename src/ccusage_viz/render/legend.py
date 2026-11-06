"""Width-aware series legends shared by native and Dataset chart renderers."""

from __future__ import annotations

from collections.abc import Sequence

from ccusage_viz.formatting import clip_width, display_width
from ccusage_viz.render.base import RenderContext


def legend_rows(
    entries: Sequence[str],
    context: RenderContext,
    *,
    separator: str = " · ",
    reserved_rows: int = 1,
) -> tuple[str, ...]:
    """Keep complete entries together, using at most two physical rows.

    Preserve eight rows for the plot/chrome before allocating a second legend
    row. Oversized individual entries are visibly shortened; entries omitted
    by the row cap are counted, including the space needed by the count itself.
    ANSI styles and wide Unicode labels are measured in terminal cells.
    """
    width = context.width
    if not entries or width <= 0:
        return ()
    maximum = 2 if context.height - reserved_rows >= 10 else 1
    bounded = tuple(
        entry if display_width(entry) <= width else clip_width(entry, max(0, width - 1)) + "…"
        for entry in entries
    )

    def pack(items: Sequence[str]) -> tuple[str, ...] | None:
        rows: list[str] = []
        current = ""
        for item in items:
            candidate = separator.join((current, item)) if current else item
            if display_width(candidate) > width:
                if current:
                    rows.append(current)
                current = item
            else:
                current = candidate
            if len(rows) >= maximum:
                return None
        if current:
            rows.append(current)
        return tuple(rows) if len(rows) <= maximum else None

    packed = pack(bounded)
    if packed is not None:
        return packed
    for kept in range(len(bounded) - 1, -1, -1):
        omitted = clip_width(f"…(+{len(bounded) - kept})", width)
        packed = pack((*bounded[:kept], omitted))
        if packed is not None:
            return packed
    return ()

from __future__ import annotations

from ccusage_viz.animation_overlay import clip_overlay_placements, compose_overlay_row
from ccusage_viz.dashboard_layout import PaneLayout as ResolvedPaneLayout
from ccusage_viz.dashboard_layout import PaneRect, layout_for_pane_count, resolve_pane_layout
from ccusage_viz.dashboard_layout import parse_grid as parse_numeric_grid
from ccusage_viz.formatting import clip_width, pad_width
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.tui.models import DashboardOverlayPlacement, PaneLayout


def _grid_shape(grid: str, count: int) -> tuple[int, int]:
    """Return logical bands for compatibility with rectangular-grid callers."""
    layout = resolve_pane_layout(
        layout=grid,
        pane_count=count,
        width=max(8, count * 8),
        height=max(6, count * 6),
        divider_style="none",
    )
    return layout.topology.rows, layout.topology.columns

def _grid_for_pane_count(grid: str, pane_count: int) -> str:
    return layout_for_pane_count(grid, pane_count)

def _practical_grid(pane_count: int) -> str:
    """Return the smallest two-column grid suitable for numeric layout editing."""
    if pane_count == 1:
        return "1x1"
    columns = 2
    rows = (pane_count + columns - 1) // columns
    return f"{rows}x{columns}"

def parse_grid(value: str, pane_count: int) -> str | None:
    """Normalize a runtime numeric grid only when it can display every pane."""
    return parse_numeric_grid(value, pane_count)

def _dashboard_structure(style: str) -> tuple[str, str]:
    return {
        "minimal": ("none", "none"),
        "split": ("line", "none"),
        "framed": ("none", "subtle"),
        "accent": ("none", "accent"),
    }[style]

def resolve_panel_layout(
    *, width: int, height: int, rows: int, columns: int, divider_style: str
) -> PaneLayout:
    """Allocate every grid row and column, including uneven remainders."""
    gutter = 0 if divider_style == "none" else 1
    available_width = max(columns * 4, width - gutter * (columns - 1))
    available_height = max(rows * 3, height - gutter * (rows - 1))
    width_base, width_remainder = divmod(available_width, columns)
    height_base, height_remainder = divmod(available_height, rows)
    return PaneLayout(
        tuple(width_base + int(index < width_remainder) for index in range(columns)),
        tuple(height_base + int(index < height_remainder) for index in range(rows)),
        gutter,
    )

def pane_rects(
    *,
    pane_count: int,
    width: int,
    height: int,
    rows: int,
    columns: int,
    divider_style: str = "line",
    top: int = 2,
    left: int = 1,
) -> tuple[PaneRect, ...]:
    layout = resolve_panel_layout(
        width=width,
        height=height,
        rows=rows,
        columns=columns,
        divider_style=divider_style,
    )
    rects: list[PaneRect] = []
    for row, cell_height in enumerate(layout.heights):
        cell_left = left
        for column, cell_width in enumerate(layout.widths):
            index = row * columns + column
            if index < pane_count:
                rects.append(PaneRect(index, cell_left, top, cell_width, cell_height))
            cell_left += cell_width + layout.gutter
        top += cell_height + layout.gutter
    return tuple(rects)

def pane_at(rects: tuple[PaneRect, ...], x: int, y: int) -> int | None:
    for rect in rects:
        if rect.left <= x < rect.left + rect.width and rect.top <= y < rect.top + rect.height:
            return rect.index
    return None

def _fit_line(line: str, width: int) -> str:
    return pad_width(clip_width(line, width), width)

def _frame(
    lines: list[str],
    width: int,
    height: int,
    *,
    selected: bool,
    ascii: bool,
    frame_style: str,
    shell_context: RenderContext | None = None,
) -> list[str]:
    """Frame a pane only when configured or explicitly selected for adjustment."""
    if height <= 0:
        return []
    if width <= 0:
        return ["" for _ in range(height)]
    if width < 3 or height < 3:
        body = [_fit_line(line, width) for line in lines[:height]]
        body.extend(" " * width for _ in range(height - len(body)))
        return body
    if frame_style == "none" and not selected:
        body = [_fit_line(line, width) for line in lines[:height]]
        body.extend(" " * width for _ in range(height - len(body)))
        return body
    effective_style = "subtle" if frame_style == "none" else frame_style
    if ascii or effective_style == "mono":
        glyphs = ("+", "+", "-", "|", "+", "+")
    elif effective_style == "accent":
        glyphs = ("╔", "╗", "═", "║", "╚", "╝")
    else:
        glyphs = ("┌", "┐", "─", "│", "└", "┘")
    left, right, horizontal, vertical, bottom_left, bottom_right = glyphs
    if selected and effective_style == "auto":
        left, right, horizontal, vertical, bottom_left, bottom_right = "╔", "╗", "═", "║", "╚", "╝"
    if shell_context is not None:
        color = (
            get_color_scheme(shell_context.color_scheme).highlight
            if selected
            else get_color_scheme(shell_context.color_scheme).other
        )
        left, right, horizontal, vertical, bottom_left, bottom_right = (
            styled_text(glyph, color, shell_context, bold=selected)
            for glyph in (left, right, horizontal, vertical, bottom_left, bottom_right)
        )
    body = [_fit_line(line, width - 2) for line in lines[: height - 2]]
    body.extend(" " * (width - 2) for _ in range(height - 2 - len(body)))
    return [
        left + horizontal * (width - 2) + right,
        *(vertical + item + vertical for item in body),
        bottom_left + horizontal * (width - 2) + bottom_right,
    ]

def compose_panes(
    charts: list[str],
    width: int,
    height: int,
    rows: int,
    columns: int,
    *,
    focused: int = -1,
    ascii: bool = False,
    divider_style: str = "line",
    frame_style: str = "auto",
    shell_context: RenderContext | None = None,
) -> str:
    """Compose charts with either framed cells or explicit row/column separators."""
    layout = resolve_panel_layout(
        width=width,
        height=height,
        rows=rows,
        columns=columns,
        divider_style=divider_style,
    )

    def cell(index: int, cell_width: int, cell_height: int) -> list[str]:
        chart = charts[index].splitlines() if index < len(charts) else []
        return _frame(
            chart,
            cell_width,
            cell_height,
            selected=index == focused,
            ascii=ascii,
            frame_style=frame_style,
            shell_context=shell_context,
        )

    separator = (
        ":" if ascii and divider_style == "dashed" else "┊" if divider_style == "dashed" else "│"
    )
    horizontal = (
        "." if ascii and divider_style == "dashed" else "┄" if divider_style == "dashed" else "─"
    )
    if shell_context is not None:
        border = get_color_scheme(shell_context.color_scheme).other
        separator = styled_text(separator, border, shell_context)
        horizontal = styled_text(horizontal, border, shell_context)
    output: list[str] = []
    for row, cell_height in enumerate(layout.heights):
        row_cells = [
            cell(row * columns + column, cell_width, cell_height)
            for column, cell_width in enumerate(layout.widths)
        ]
        joiner = separator if layout.gutter else ""
        output.extend(joiner.join(parts) for parts in zip(*row_cells, strict=True))
        if layout.gutter and row + 1 < rows:
            output.append(horizontal * layout.width)
    return "\n".join(output)

def _compose_dashboard_overlays(
    grid: str,
    layout: ResolvedPaneLayout,
    overlays: tuple[DashboardOverlayPlacement, ...],
    *,
    focused: int,
) -> str:
    """Paint pane-relative overlays above the complete Dashboard grid."""
    rows = grid.splitlines()
    ordered = sorted(
        overlays,
        key=lambda item: (item.source_index == focused, item.source_index),
    )
    for item in ordered:
        for placement in clip_overlay_placements(
            (item.placement,), width=layout.width, height=layout.height
        ):
            rows[placement.row] = compose_overlay_row(
                rows[placement.row], placement, width=layout.width
            )
    return "\n".join(rows)

def _compose_resolved_panes(
    charts: list[str],
    layout: ResolvedPaneLayout,
    *,
    focused: int = -1,
    ascii: bool = False,
    divider_style: str = "line",
    frame_style: str = "auto",
    shell_context: RenderContext | None = None,
) -> str:
    """Compose exactly the rectangles produced by the shared layout resolver."""
    rendered = {
        rect.index: _frame(
            charts[rect.index].splitlines() if rect.index < len(charts) else [],
            rect.width,
            rect.height,
            selected=rect.index == focused,
            ascii=ascii,
            frame_style=frame_style,
            shell_context=shell_context,
        )
        for rect in layout.panes
        if rect.width > 0 and rect.height > 0
    }
    vertical = (
        ":" if ascii and divider_style == "dashed" else "┊" if divider_style == "dashed" else "│"
    )
    horizontal = (
        "." if ascii and divider_style == "dashed" else "┄" if divider_style == "dashed" else "─"
    )
    intersection = "+" if ascii else "┼"
    if shell_context is not None:
        border = get_color_scheme(shell_context.color_scheme).other
        vertical, horizontal, intersection = (
            styled_text(glyph, border, shell_context)
            for glyph in (vertical, horizontal, intersection)
        )

    column_gutters: set[int] = set()
    cursor = 0
    for size in layout.column_sizes[:-1]:
        cursor += size
        column_gutters.update(range(cursor, cursor + layout.column_gutter))
        cursor += layout.column_gutter
    row_gutters: set[int] = set()
    cursor = 0
    for size in layout.row_sizes[:-1]:
        cursor += size
        row_gutters.update(range(cursor, cursor + layout.row_gutter))
        cursor += layout.row_gutter

    output: list[str] = []
    for y in range(layout.height):
        segments: list[str] = []
        x = 0
        while x < layout.width:
            rect = next(
                (
                    item
                    for item in layout.panes
                    if item.width > 0
                    and item.height > 0
                    and item.left <= x < item.left + item.width
                    and item.top <= y < item.top + item.height
                ),
                None,
            )
            if rect is not None:
                segments.append(rendered[rect.index][y - rect.top])
                x = rect.left + rect.width
                continue
            if x in column_gutters and y in row_gutters:
                segments.append(intersection)
            elif y in row_gutters:
                segments.append(horizontal)
            elif x in column_gutters:
                segments.append(vertical)
            else:
                segments.append(" ")
            x += 1
        output.append("".join(segments))
    return "\n".join(output)

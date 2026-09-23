from __future__ import annotations

from math import ceil

from ccusage_viz.chart_models import (
    DistributionCoverage,
    TimeOfDayDistributionModel,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens, pad_width
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    styled_text,
    title_with_querying,
    y_tick_spec,
)
from ccusage_viz.render.palette import categorical_colors, get_color_scheme


def _dimension_label(model: TimeOfDayDistributionModel, context: RenderContext) -> str:
    """Infer the selected Monitor dimension from its semantic series keys."""
    if context.title_content:
        return context.title_content
    if not model.series or model.series[0].key == "Total":
        return context.translator.text("label.total")
    key = model.series[0].key
    if isinstance(key, tuple) and key and key[0] in {"agent", "model", "project"}:
        return context.translator.text(f"label.{key[0]}")
    return context.translator.text("label.total")


def _day_label(model: TimeOfDayDistributionModel, context: RenderContext) -> str:
    return context.translator.text(f"label.monitor_distribution_{model.day_window}")


def _granularity_label(model: TimeOfDayDistributionModel, context: RenderContext) -> str:
    return context.translator.text(f"label.monitor_distribution_{model.granularity}")


def _series_colors(model: TimeOfDayDistributionModel, context: RenderContext) -> dict[object, int]:
    colors = categorical_colors((series.key for series in model.series), context.color_scheme)
    scheme = get_color_scheme(context.color_scheme)
    for series in model.series:
        if series.is_other:
            colors[series.key] = scheme.other
    return colors


def _time_ticks(
    model: TimeOfDayDistributionModel, bar_positions: list[tuple[int, int]], plot_width: int
) -> list[tuple[int, str]]:
    """Select non-overlapping local-time labels centered beneath their bars."""
    if not model.buckets:
        return []
    time_format = "%H" if model.granularity == "hour" else "%H:%M"
    labels = [bucket.started_at.strftime(time_format) for bucket in model.buckets]
    label_width = max(len(label) for label in labels)
    capacity = max(2, plot_width // (label_width + 2))
    step = max(1, ceil(len(labels) / capacity))
    candidates = list(range(0, len(labels), step))
    if candidates[-1] != len(labels) - 1:
        candidates.append(len(labels) - 1)
    ticks: list[tuple[int, str]] = []
    occupied = [False] * plot_width
    for index in candidates:
        label = labels[index]
        bar_start, bar_width = bar_positions[index]
        start = max(
            0,
            min(
                plot_width - len(label),
                bar_start + ceil((bar_width - len(label)) / 2),
            ),
        )
        end = start + len(label)
        if any(occupied[max(0, start - 1) : min(plot_width, end + 1)]):
            continue
        occupied[start:end] = [True] * (end - start)
        ticks.append((start, label))
    return ticks


def _distribution_grid(
    model: TimeOfDayDistributionModel,
    context: RenderContext,
    *,
    header_rows: int,
) -> str:
    bucket_count = len(model.buckets)
    values = [sum(bucket.values.values()) for bucket in model.buckets]
    positions, tick_labels = y_tick_spec(values)
    label_width = max(display_width(label) for label in tick_labels)
    gutter = label_width + 2
    plot_width = context.width - gutter
    if plot_width < bucket_count:
        raise UsageError("error.stack_stacked_width", width=context.width)

    slot_bounds = [index * plot_width // bucket_count for index in range(bucket_count + 1)]
    bar_positions = []
    for index in range(bucket_count):
        slot_width = slot_bounds[index + 1] - slot_bounds[index]
        bar_width = 2 if slot_width >= 3 else 1
        bar_start = slot_bounds[index] + (slot_width - bar_width) // 2
        bar_positions.append((bar_start, bar_width))
    # Let the plot consume the remaining pane height after title/legend,
    # x-axis, and tick-label rows.
    data_rows = max(4, context.height - header_rows - 2)
    maximum = positions[-1] if positions else 0.0
    grid = [[" "] * plot_width for _ in range(data_rows)]
    scheme = get_color_scheme(context.color_scheme)
    colors = _series_colors(model, context)
    solid = "#" if context.ascii else "█"
    partial = "+" if context.ascii else "▓"
    unobserved = ":" if context.ascii else "░"
    zero = "o" if context.ascii else "•"

    for bucket_index, bucket in enumerate(model.buckets):
        column, bar_width = bar_positions[bucket_index]
        if bucket.coverage is DistributionCoverage.UNOBSERVED:
            for row in range(data_rows):
                for offset in range(bar_width):
                    grid[row][column + offset] = styled_text(
                        unobserved, scheme.muted, context, dim=True
                    )
            continue

        mark = partial if bucket.coverage is DistributionCoverage.PARTIAL else solid
        cumulative = 0.0
        for series in model.series:
            lower = round(cumulative / maximum * data_rows) if maximum else 0
            cumulative += bucket.values.get(series.key, 0.0)
            upper = round(cumulative / maximum * data_rows) if maximum else 0
            for row in range(data_rows - upper, data_rows - lower):
                if 0 <= row < data_rows:
                    for offset in range(bar_width):
                        grid[row][column + offset] = styled_text(mark, colors[series.key], context)
        if cumulative == 0:
            for offset in range(bar_width):
                grid[-1][column + offset] = styled_text(zero, scheme.muted, context)

    tick_rows = (
        {
            data_rows - 1 - round(position / maximum * (data_rows - 1)): label
            for position, label in zip(positions, tick_labels, strict=True)
        }
        if maximum
        else {data_rows - 1: tick_labels[0]}
    )
    vertical = "|" if context.ascii else "│"
    axis = "+" if context.ascii else "┼"
    horizontal = "-" if context.ascii else "─"
    lines = [
        pad_width(tick_rows.get(row, ""), label_width, align="right")
        + f" {vertical}"
        + "".join(cells)
        for row, cells in enumerate(grid)
    ]
    lines.append(" " * (label_width + 1) + axis + horizontal * plot_width)
    tick_row = [" "] * plot_width
    for start, label in _time_ticks(model, bar_positions, plot_width):
        tick_row[start : start + len(label)] = label
    lines.append(" " * gutter + "".join(tick_row))
    return "\n".join(lines)


def _series_legend(
    model: TimeOfDayDistributionModel,
    context: RenderContext,
    *,
    values: bool = False,
    include_coverage: bool = False,
) -> str:
    """Render one compact, width-bounded series identity row."""
    colors = _series_colors(model, context)
    marks = ("#", "=", "+", ":", "%", "@") if context.ascii else ("█", "■", "●", "◆", "✚", "•")
    entries = []
    for index, series in enumerate(model.series):
        entry = (
            f"{colored_mark(marks[index % len(marks)], colors[series.key], context)} {series.label}"
        )
        if values:
            total = sum(bucket.values.get(series.key, 0.0) for bucket in model.buckets)
            entry = f"{entry} {format_tokens(round(total))}"
        entries.append(entry)
    if include_coverage:
        scheme = get_color_scheme(context.color_scheme)
        entries.append(
            f"{styled_text('#' if context.ascii else '█', scheme.muted, context, dim=True)} "
            f"{context.translator.text('label.monitor_distribution_unobserved')}"
        )
    return clip_width(" · ".join(entries), context.width)


def render_monitor_distribution(model: TimeOfDayDistributionModel, context: RenderContext) -> str:
    """Render Monitor-only calendar-day token increments with honest coverage states."""
    if not model.buckets:
        return context.translator.text("message.no_data")

    dimension = _dimension_label(model, context)
    heading = center_text(
        title_with_querying(
            context.translator.text(
                "label.monitor_distribution_title",
                mode=dimension,
                day=f"{_day_label(model, context)} · {_granularity_label(model, context)}",
            ),
            context,
        ),
        context.width,
    )
    multi_series = len(model.series) > 1
    legend_mode = context.legend_position if multi_series else "hidden"
    legend_line = ""
    if context.height >= 13 and legend_mode == "below-title":
        legend_line = _series_legend(model, context, include_coverage=True)
    elif context.height >= 12 and legend_mode == "inside":
        legend_line = _series_legend(model, context)
    elif context.height >= 13 and legend_mode == "values":
        legend_line = _series_legend(model, context, values=True)

    # The terminal renderer has no overlay layer.  An inside legend is therefore
    # intentionally the first plot row: it remains in the chart's own area while
    # preserving the same total row budget as hidden mode.
    if legend_mode == "inside" and legend_line:
        grid = _distribution_grid(model, context, header_rows=1)
        grid_lines = grid.splitlines()
        grid_lines[0] = center_text(legend_line, context.width)
        return "\n".join((heading, *grid_lines))

    legend_lines = [center_text(legend_line, context.width)] if legend_line else []
    return "\n".join(
        (
            heading,
            *legend_lines,
            _distribution_grid(model, context, header_rows=1 + len(legend_lines)),
        )
    )

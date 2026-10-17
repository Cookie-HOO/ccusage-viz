"""Shared Plotext presentation for native and custom timeline charts."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from decimal import Decimal

import plotext as plt

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    isolated_plot,
    plot_height,
    plot_text,
)
from ccusage_viz.render.palette import categorical_colors, get_color_scheme


@dataclass(frozen=True, slots=True)
class TimelinePresentationSeries:
    """Numeric timeline values with a stable identity for palette allocation."""

    color_key: Hashable
    label: str
    # ``None`` preserves a source-declared missing interval.  The renderer
    # deliberately splits line runs and omits missing bars instead of drawing a
    # fabricated zero or connecting across the gap.
    values: tuple[int | float | Decimal | None, ...]
    is_other: bool = False


@dataclass(frozen=True, slots=True)
class TimelinePlot:
    chart: str
    legend: str


def render_timeline_plot(
    series: Sequence[TimelinePresentationSeries],
    *,
    x_values: Sequence[int | float | Decimal],
    x_ticks: tuple[Sequence[int | float | Decimal], Sequence[str]],
    y_ticks: tuple[Sequence[int | float | Decimal], Sequence[str]],
    context: RenderContext,
    text_rows: int,
    sole_total: bool,
    use_bars: bool = False,
    y_maximum: int | float | Decimal | None = None,
) -> TimelinePlot:
    """Render the common timeline plot and optional below-title legend."""

    if context.style == "area" and len(series) != 1:
        raise UsageError("error.timeline_area_series")

    show_legend = (not sole_total and context.legend_position != "hidden") or (
        sole_total and context.legend_position == "inside"
    )
    marker_names = ("dot", "circle", "diamond", "square", "cross", "star", "up", "xmark")
    marker_labels = ("•", "○", "◆", "■", "✚", "✱", "▲", "×")
    ascii_marker_labels = (".", "o", "D", "#", "+", "*", "^", "x")
    uniform_points = context.style in {"points", "line-points"}
    scheme = get_color_scheme(context.color_scheme)
    colors = categorical_colors(
        (item.color_key for item in series if not item.is_other), context.color_scheme
    )

    def color_for(item: TimelinePresentationSeries) -> int:
        return scheme.other if item.is_other else colors[item.color_key]

    def legend_mark(index: int, item: TimelinePresentationSeries) -> str:
        if uniform_points:
            return "." if context.ascii else "•"
        if item.is_other:
            return "#" if context.ascii else "◆"
        return (
            ascii_marker_labels[index % len(ascii_marker_labels)]
            if context.ascii
            else marker_labels[index % len(marker_labels)]
        )

    legend = (
        clip_width(
            " · ".join(
                f"{colored_mark(legend_mark(index, item), color_for(item), context)} {item.label}"
                for index, item in enumerate(series)
            ),
            context.width,
        )
        if show_legend and context.legend_position == "below-title"
        else ""
    )

    if any(0 < sum(value is not None for value in item.values) < 2 for item in series):
        rows = []
        for item in series:
            observed = tuple(value for value in item.values if value is not None)
            if observed:
                rows.append(clip_width(f"{item.label} {float(observed[-1]):g}", context.width))
        return TimelinePlot("\n".join(rows), legend)

    with isolated_plot():
        configure_plot(context)
        # Plotext constrains explicit plot sizes to its ambient terminal by
        # default. Dashboard panes supply their own geometry, which can exceed
        # that ambient height after chrome is removed; let this renderer own
        # its explicit dimensions instead of silently dropping the final row.
        plt.terminal.limit(False, False)
        plt.figure.plot_size(context.width, plot_height(context, text_rows=text_rows))
        for index, item in enumerate(series):
            marker_name = (
                "."
                if context.ascii
                else "dot"
                if uniform_points
                else marker_names[index % len(marker_names)]
            )
            marker = plt.marker(
                marker_name,
                pixel=plt.pixel(foreground=color_for(item)) if context.color else None,
            )
            raw_points = list(zip(x_values, item.values, strict=True))
            numeric_points = [(point, value) for point, value in raw_points if value is not None]
            if not numeric_points:
                continue
            signals = []
            if use_bars:
                signals.append(
                    plt.figure.bar(
                        [float(point) for point, _ in numeric_points],
                        [float(value) for _, value in numeric_points],
                        marker=marker,
                        width=0.75,
                    )
                )
            else:
                # Source-owned missing observations are factual gaps. Draw
                # contiguous runs separately rather than joining across them.
                runs: list[list[tuple[int | float | Decimal, int | float | Decimal]]] = []
                run: list[tuple[int | float | Decimal, int | float | Decimal]] = []
                for point, value in raw_points:
                    if value is None:
                        if run:
                            runs.append(run)
                            run = []
                        continue
                    run.append((point, value))
                if run:
                    runs.append(run)
                for run in runs:
                    points_x = [point for point, _ in run]
                    points_y = [value for _, value in run]
                    if context.style == "step":
                        points_x = [
                            point for position in points_x for point in (position, position + 1)
                        ]
                        points_y = [value for value in points_y for value in (value, value)]
                    signal = plt.figure.signal(
                        [float(point) for point in points_x],
                        [float(value) for value in points_y],
                        marker=marker,
                    ).lines(context.style not in {"no-line", "points", "stem"})
                    if context.style in {"stem", "area"}:
                        signal.fillx()
                    signals.append(signal)
            if show_legend and context.legend_position == "inside":
                signals[0].label(item.label)
            for signal in signals:
                plt.figure.draw(signal)
        plt.figure.legend(active=context.legend_position == "inside")
        positions, labels = x_ticks
        plt.figure.ruler("x").ticks([float(position) for position in positions], labels)
        y_positions, y_labels = y_ticks
        if y_maximum is not None:
            plt.figure.ruler("y").lim(0, float(y_maximum))
        plt.figure.ruler("y").ticks([float(position) for position in y_positions], y_labels)
        return TimelinePlot(plot_text(context), legend)

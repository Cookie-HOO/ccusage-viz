"""ccuv-owned Ranking label semantics and snapshot-stable band legends."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from ccusage_viz.formatting import sanitize_terminal_text
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.legend import legend_rows
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_description import _highlight_parts
from ccusage_viz.render.ranking_entries import RankingNumber, RankingPresentationEntry


def label_change(
    entry: RankingPresentationEntry,
    context: RenderContext,
    *,
    comparison_available: bool = True,
) -> RankingNumber | float | None:
    """An accepted refresh delta (including zero) overrides period comparison."""
    deltas = context.label_deltas if context.label_deltas is not None else context.deltas
    if deltas is not None and entry.key in deltas:
        return deltas[entry.key]
    if (
        comparison_available
        and context.period != "all"
        and entry.comparison_ready
        and entry.previous is not None
    ):
        return entry.current - entry.previous
    return None


def band_colors(context: RenderContext) -> dict[str, int]:
    palette = get_color_scheme(context.color_scheme).categorical
    return {
        band.id: palette[index % len(palette)] for index, band in enumerate(context.ranking_bands)
    }


def ranking_label(
    text: str,
    entry: RankingPresentationEntry,
    context: RenderContext,
    *,
    query: str = "",
    pending: bool = False,
    comparison_available: bool = True,
) -> str:
    """Style label spans only; search spans retain their independent emphasis."""
    scheme = get_color_scheme(context.color_scheme)
    color = None
    mode = context.label_color_mode
    if not entry.is_other:
        if mode == "band":
            color = band_colors(context).get(entry.band_id)
        elif not pending and not context.pending and mode != "none":
            change = label_change(entry, context, comparison_available=comparison_available)
            if change is not None and change != 0:
                if mode == "change":
                    color = scheme.highlight
                elif change > 0 and mode in {"increase", "direction"}:
                    color = scheme.trend_increase
                elif change < 0 and mode in {"decrease", "direction"}:
                    color = scheme.trend_decrease
    return "".join(
        styled_text(part, scheme.highlight, context, bold=True)
        if matched
        else styled_text(part, color, context, bold=True)
        if color is not None
        else part
        for part, matched in _highlight_parts(text, query)
    )


def ranking_band_legend_entries(
    entries: Sequence[RankingPresentationEntry], context: RenderContext
) -> tuple[str, ...]:
    """Complete named band entries before width packing or local filtering."""
    if context.label_color_mode != "band" or context.legend_position == "hidden":
        return ()
    represented = {entry.band_id for entry in entries if not entry.is_other}
    colors = band_colors(context)
    items = []
    for band in context.ranking_bands:
        if band.id not in represented or band.label is None:
            continue
        label = band.label.zh_cn if context.translator.language == "zh" else band.label.en
        label = sanitize_terminal_text(label).replace("\n", "\\n")
        swatch = styled_text("o" if context.ascii else "●", colors[band.id], context)
        items.append(f"{swatch} {label}")
    return tuple(items)


def ranking_band_legend(
    entries: Sequence[RankingPresentationEntry], context: RenderContext
) -> tuple[str, ...]:
    """Named represented bands, declared order, before search or viewport filtering."""
    return legend_rows(ranking_band_legend_entries(entries, context), context)


def group_label_deltas(
    group_id: str, entries: Sequence[RankingPresentationEntry], context: RenderContext
) -> Mapping[Hashable, float] | None:
    """Remap only present group-local deltas; missing is not an accepted zero."""
    if context.deltas is None:
        return None
    return {
        entry.key: context.deltas[(group_id, entry.key)]
        for entry in entries
        if (group_id, entry.key) in context.deltas
    }

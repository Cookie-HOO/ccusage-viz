from __future__ import annotations

from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import Filters


def active_filter_summary(filters: Filters, translator: Translator, *, width: int) -> str:
    """Render submitted filter selectors in a compact, fixed dimension order."""
    selections = tuple(
        (dimension, values)
        for dimension, values in (
            ("agent", filters.agents),
            ("model", filters.models),
            ("project", filters.projects),
        )
        if values
    )
    if not selections:
        return ""
    budget = max(1, width)
    for formatter in (_full_segments, _abbreviated_segments, _count_segments):
        rendered = _summary(formatter(selections, translator), translator)
        if display_width(rendered) <= budget:
            return rendered
    return _summary(_count_segments(selections, translator), translator)


def _full_segments(
    selections: tuple[tuple[str, tuple[str, ...]], ...], translator: Translator
) -> tuple[str, ...]:
    return tuple(
        _segment(dimension, ", ".join(values), translator) for dimension, values in selections
    )


def _abbreviated_segments(
    selections: tuple[tuple[str, tuple[str, ...]], ...], translator: Translator
) -> tuple[str, ...]:
    return tuple(
        _segment(
            dimension,
            values[0]
            if len(values) == 1
            else f"{values[0]} {translator.text('filter.more', count=len(values) - 1)}",
            translator,
        )
        for dimension, values in selections
    )


def _count_segments(
    selections: tuple[tuple[str, tuple[str, ...]], ...], translator: Translator
) -> tuple[str, ...]:
    return tuple(
        translator.text("filter.count", dimension=dimension, count=len(values))
        for dimension, values in selections
    )


def _segment(dimension: str, values: str, translator: Translator) -> str:
    return translator.text("filter.dimension", dimension=dimension, values=values)


def _summary(segments: tuple[str, ...], translator: Translator) -> str:
    return translator.text("filter.summary", filters=" · ".join(segments))

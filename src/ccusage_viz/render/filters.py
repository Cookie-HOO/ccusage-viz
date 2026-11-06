from __future__ import annotations

from ccusage_viz.custom_models import CustomPresentationDescriptor
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CustomFilters, Filters


def active_filter_summaries(filters: Filters, translator: Translator) -> tuple[str, ...]:
    """Return complete-to-compact filter summaries for title width negotiation."""
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
        return ()
    return tuple(
        dict.fromkeys(
            _summary(formatter(selections, translator), translator)
            for formatter in (_full_segments, _abbreviated_segments, _count_segments)
        )
    )


def custom_filter_summaries(
    filters: CustomFilters,
    descriptor: CustomPresentationDescriptor | None,
    translator: Translator,
) -> tuple[str, ...]:
    """Return localized Dataset filter summaries for the shared title chrome."""
    if descriptor is None:
        return ()
    selections = tuple(
        (
            _localized(descriptor.filter_labels.get(filter_id), filter_id, translator),
            tuple(
                _localized(descriptor.filter_values.get((filter_id, value)), value, translator)
                for value in values
            ),
        )
        for filter_id, values in filters
        if values
    )
    return _summaries(selections, translator)


def _localized(value: object, fallback: str, translator: Translator) -> str:
    if value is None:
        return fallback
    return value.zh_cn if translator.language == "zh" else value.en


def _summaries(
    selections: tuple[tuple[str, tuple[str, ...]], ...], translator: Translator
) -> tuple[str, ...]:
    if not selections:
        return ()
    return tuple(
        dict.fromkeys(
            _summary(formatter(selections, translator), translator)
            for formatter in (_full_segments, _abbreviated_segments, _count_segments)
        )
    )


def active_filter_summary(filters: Filters, translator: Translator, *, width: int) -> str:
    """Render the richest submitted filter summary that fits a known width."""
    summaries = active_filter_summaries(filters, translator)
    if not summaries:
        return ""
    budget = max(1, width)
    return next(
        (summary for summary in summaries if display_width(summary) <= budget), summaries[-1]
    )


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

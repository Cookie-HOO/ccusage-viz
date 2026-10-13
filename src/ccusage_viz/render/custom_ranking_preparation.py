"""Shared flat preparation for direct and viewport Custom Ranking rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import display_width, sanitize_terminal_text
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.processing.custom_ranking import (
    CustomProjectedRankingEntry,
    CustomRankingProjection,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    filter_ranking_entries,
)
from ccusage_viz.render.summary import format_custom_value

RankingEntry = CustomProjectedSeries | CustomProjectedRankingEntry
RankingProjection = CustomChartProjection | CustomRankingProjection
CopyMarker = Callable[[RankingEntry], str | None]


@dataclass(frozen=True, slots=True)
class PreparedCustomRanking:
    """Complete and query-matched entries plus full-ranking scalar facts."""

    full_entries: tuple[RankingPresentationEntry, ...]
    matched_entries: tuple[RankingPresentationEntry, ...]
    by_id: dict[str, RankingPresentationEntry]
    full_total: Decimal
    full_maximum: Decimal


def prepare_custom_ranking(
    projection: RankingProjection,
    context: RenderContext,
    *,
    search_query: str = "",
    copy_marker: CopyMarker | None = None,
) -> PreparedCustomRanking:
    """Prepare localized flat ranking facts shared by all rendering paths."""

    def localized(text: LocalizedText) -> str:
        return text.zh_cn if context.translator.language == "zh" else text.en

    def value(number: int | Decimal) -> str:
        return format_custom_value(
            Decimal(number), projection.unit, language=context.translator.language
        )

    def prepare_entry(entry: RankingEntry, rank: int) -> RankingPresentationEntry:
        display = (
            sanitize_terminal_text(localized(entry.display))
            if entry.display and not entry.is_other
            else value(entry.total)
        )
        comparison_display = (
            sanitize_terminal_text(localized(entry.comparison_display))
            if entry.comparison_display and not entry.is_other
            else (
                f"{'+' if entry.total > entry.previous_total else '-'}"
                f"{value(abs(entry.total - entry.previous_total))}"
                if entry.previous_total is not None and entry.total != entry.previous_total
                else None
            )
        )
        return RankingPresentationEntry(
            entry.id,
            context.translator.text("label.other")
            if entry.is_other
            else sanitize_terminal_text(localized(entry.label)).replace("\n", "\\n"),
            entry.total,
            entry.previous_total,
            entry.comparison_ready,
            entry.is_other,
            entry.previous_rank,
            description=(
                localized(entry.description) if entry.description and not entry.is_other else None
            ),
            display=display,
            comparison_display=comparison_display,
            copy_marker=(copy_marker(entry) if copy_marker is not None else None),
            project_link=None if entry.is_other else entry.link,
            display_width=display_width(display),
            comparison_display_width=(
                display_width(comparison_display) if comparison_display is not None else None
            ),
            rank=entry.rank or rank,
        )

    full_entries = tuple(
        prepare_entry(entry, rank) for rank, entry in enumerate(projection.series, 1)
    )
    prior = {
        entry.key: rank
        for rank, entry in enumerate(
            sorted(
                (
                    entry
                    for entry in full_entries
                    if entry.previous is not None and not entry.is_other
                ),
                key=lambda entry: (-cast(Decimal, entry.previous), str(entry.key)),
            ),
            1,
        )
    }
    full_entries = tuple(
        replace(entry, previous_rank=entry.previous_rank or prior.get(entry.key))
        for entry in full_entries
    )
    # Empty-query preparation is the common building block for grouped
    # rankings. Avoid passing the complete tuple through the search predicate
    # only for the grouped adapter to filter it again.
    matched_entries = (
        filter_ranking_entries(full_entries, search_query) if search_query else full_entries
    )
    return PreparedCustomRanking(
        full_entries,
        matched_entries,
        {str(entry.key): entry for entry in matched_entries},
        sum((Decimal(entry.current) for entry in full_entries), start=Decimal()),
        max((Decimal(entry.current) for entry in full_entries), default=Decimal()),
    )

"""Standalone presentation for partitioned Custom Rankings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import center_text, display_width
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    CustomProjectedRankingGroup,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom_ranking_preparation import prepare_custom_ranking
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    measure_ranking_columns,
    render_historical_ranking,
    render_ranking_heading_row,
)
from ccusage_viz.render.ranking_viewport import RankingColumns
from ccusage_viz.render.summary import format_custom_value


@dataclass(frozen=True, slots=True)
class GroupedRankingPresentationGroup:
    """Localized group metadata and complete facts for one inner ranking."""

    id: str
    label: str
    description: str | None
    link: str | None
    display: str
    comparison_display: str
    share: Decimal | None
    entries: tuple[RankingPresentationEntry, ...]
    total: Decimal
    maximum: Decimal


def _localized(value: LocalizedText, context: RenderContext) -> str:
    return value.zh_cn if context.translator.language == "zh" else value.en


def _value(value: Decimal, projection: CustomChartProjection, context: RenderContext) -> str:
    return format_custom_value(value, projection.unit, language=context.translator.language)


def _prepare_group(
    group: CustomProjectedRankingGroup,
    projection: CustomChartProjection,
    context: RenderContext,
    *,
    global_total: Decimal,
) -> GroupedRankingPresentationGroup:
    # Reuse the flat adapter so item metadata, custom displays, safe links,
    # previous ranks, and Other behavior stay identical to ordinary Rankings.
    prepared = prepare_custom_ranking(
        replace(projection, series=group.series, groups=None), context
    )
    display = (
        _localized(group.display, context)
        if group.display
        else _value(group.total, projection, context)
    )
    comparison_display = ""
    if (
        context.period != "all"
        and projection.comparison_available
        and group.comparison_ready
        and group.previous_total is not None
    ):
        if group.comparison_display is not None:
            comparison_display = _localized(group.comparison_display, context)
        else:
            delta = group.total - group.previous_total
            comparison_display = (
                "0"
                if delta == 0
                else f"{'+' if delta > 0 else '-'}{_value(abs(delta), projection, context)}"
            )
    return GroupedRankingPresentationGroup(
        group.id,
        _localized(group.label, context).replace("\n", "\\n"),
        _localized(group.description, context) if group.description else None,
        group.link,
        display,
        comparison_display,
        None if global_total == 0 else group.total / global_total,
        prepared.full_entries,
        group.total,
        group.maximum,
    )


def render_grouped_custom_ranking(
    projection: CustomChartProjection,
    context: RenderContext,
    *,
    heading: str,
    summary: str = "",
    descriptions_visible: bool = False,
) -> str:
    """Render Dataset-ordered groups with independent rank, share, and bar facts."""
    groups = projection.groups or ()
    global_total = sum((group.total for group in groups), start=Decimal())
    prepared = tuple(
        _prepare_group(group, projection, context, global_total=global_total) for group in groups
    )
    lines = [line for line in (summary, center_text(heading, context.width)) if line]
    if not prepared:
        lines.append(context.translator.text("message.custom_no_data"))
        return "\n".join(lines)
    columns = RankingColumns()
    all_entries = tuple(entry for group in prepared for entry in group.entries)
    comparison_mode = (
        projection.config.ranking_comparison if projection.config is not None else "full"
    )
    total_entry_count = max((len(group.entries) for group in prepared), default=0)
    comparison_visible = (
        context.density in {"full", "detailed"}
        and context.width >= 58
        and context.period != "all"
        and projection.comparison_available
        and comparison_mode != "none"
    )
    if all_entries and context.width >= 58 and context.density in {"full", "detailed"}:
        measure_ranking_columns(
            all_entries,
            context=context,
            total=max((group.total for group in prepared), default=Decimal()),
            show_percentage=projection.show_percentage,
            comparison_mode=comparison_mode,
            comparison_available=projection.comparison_available,
            show_new_entries=True,
            total_entry_count=total_entry_count,
            columns=columns,
        )
        # Include every heading before rendering so later groups cannot shift
        # columns already used by earlier groups.
        if comparison_visible:
            columns.widths["current"] = max(
                columns.widths.get("current", 0),
                *(display_width(group.display) + 2 for group in prepared),
            )
            if comparison_mode == "full":
                columns.widths["delta"] = max(
                    columns.widths.get("delta", 0),
                    *(display_width(group.comparison_display) for group in prepared),
                )
            if projection.show_percentage:
                columns.widths["share"] = max(
                    columns.widths.get("share", 0),
                    *(
                        display_width(f"{group.share:>5.1%}") if group.share is not None else 0
                        for group in prepared
                    ),
                )
        else:
            columns.widths["right"] = max(
                columns.widths.get("right", 1),
                *(
                    display_width(group.display)
                    + (
                        display_width(f"{group.share:>5.1%}")
                        if projection.show_percentage and group.share is not None
                        else 0
                    )
                    + 3
                    for group in prepared
                ),
            )
    for index, group in enumerate(prepared):
        if index and lines and lines[-1]:
            lines.append("")
        lines.extend(
            render_ranking_heading_row(
                label=group.label,
                value=group.display,
                delta=group.comparison_display,
                share=(
                    f"{group.share:>5.1%}"
                    if projection.show_percentage and group.share is not None
                    else ""
                ),
                description=group.description,
                context=context,
                link=group.link,
                descriptions_visible=descriptions_visible,
                comparison_visible=comparison_visible,
                comparison_mode=comparison_mode,
                show_percentage=projection.show_percentage,
                total_entry_count=total_entry_count,
                columns=columns,
            )
        )
        if not group.entries:
            lines.append(context.translator.text("message.grouped_ranking_no_data"))
            continue
        body = render_historical_ranking(
            group.entries,
            heading="",
            value_formatter=lambda value: _value(cast(Decimal, value), projection, context),
            delta_formatter=lambda value: (
                f"{'+' if value > 0 else '-'}{_value(abs(cast(Decimal, value)), projection, context)}"
            ),
            context=context,
            descriptions_visible=descriptions_visible,
            comparison_mode=comparison_mode,
            comparison_available=projection.comparison_available,
            show_new_entries=True,
            compact_labels=False,
            label_max_width=48,
            total_entry_count=total_entry_count,
            total=group.total,
            maximum=group.maximum,
            show_percentage=projection.show_percentage,
            entries_matched=True,
            columns=(columns if columns.widths else None),
        )
        lines.extend(body.splitlines())
    return "\n".join(lines)

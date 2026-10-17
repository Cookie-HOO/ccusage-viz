from dataclasses import replace
from datetime import date
from decimal import Decimal

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    CustomProjectedRankingGroup,
    CustomProjectedSeries,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom_ranking_viewport import render_custom_ranking_viewport
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingViewport,
    render_grouped_custom_ranking_viewport,
)


def projection(count=100, *, descriptions=False, comparison=False):
    day = date(2026, 9, 1)
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("test", ("unused",)),
        DateRange(day, day),
        presentation=ChartPresentation(density="detailed" if descriptions else "normal"),
    )
    return CustomChartProjection(
        "ranking",
        (day,),
        tuple(
            CustomProjectedSeries(
                str(index),
                LocalizedText(f"Project {index}", f"项目 {index}"),
                (Decimal(count - index),),
                description=LocalizedText("First line\nSecond line\nHidden third", "描述")
                if descriptions
                else None,
                previous_total=Decimal(index + 1) if comparison else None,
                comparison_ready=comparison,
                link=f"https://example.com/{index}",
            )
            for index in range(count)
        ),
        CustomUnit("count", LocalizedText("items", "项"), "suffix", 0),
        config.date_range,
        "day",
        config,
        comparison_available=comparison,
    )

def grouped_projection() -> CustomChartProjection:
    model = projection(0)

    def group(group_id: str, label: str, entries: tuple[tuple[str, str, str], ...]):
        series = tuple(
            CustomProjectedSeries(
                series_id,
                LocalizedText(series_label, series_label),
                (Decimal(value),),
                rank=index,
                description=LocalizedText(f"Details for {series_label}", "描述"),
                link=f"https://example.com/{group_id}/{series_id}",
            )
            for index, (series_id, series_label, value) in enumerate(entries, 1)
        )
        total = sum((item.total for item in series), start=Decimal())
        return CustomProjectedRankingGroup(
            group_id,
            LocalizedText(label, label),
            series,
            total,
            None,
            False,
            max((item.total for item in series), default=Decimal()),
            description=LocalizedText(f"About {label}", "描述"),
            link=f"https://example.com/{group_id}",
        )

    groups = (
        group("coding", "Coding Model", (("shared", "Seed", "70"), ("sonnet", "Sonnet", "30"))),
        group("general", "General Model", (("shared", "Sonnet General", "20"),)),
        group("empty", "Empty Unmatched Group", ()),
    )
    return replace(model, groups=groups, series=())

def grouped_projection_with_visible_comparisons() -> CustomChartProjection:
    model = grouped_projection()
    groups = tuple(
        replace(
            group,
            series=tuple(
                replace(
                    series,
                    previous_total=series.total - Decimal(10),
                    comparison_ready=True,
                )
                for series in group.series
            ),
            previous_total=group.total - Decimal(20),
            comparison_ready=True,
        )
        for group in model.groups or ()
    )
    return replace(model, groups=groups, comparison_available=True)

def render_grouped(
    model: CustomChartProjection,
    viewport: GroupedRankingViewport,
    ctx: RenderContext | None = None,
    *,
    search: str = "",
    spacing: str = "compact",
    scrollbar: bool = False,
    scrollbar_hovered: bool = False,
    copy_all_action: bool = False,
    copied: tuple[str, ...] | None = None,
) -> str:
    return render_grouped_custom_ranking_viewport(
        model,
        ctx or context(),
        viewport,
        heading="Grouped Ranking",
        descriptions_visible=(ctx or context()).density in {"full", "detailed"},
        search_query=search,
        search_editing=False,
        show_visible_count=True,
        copied_entry_id=copied,
        item_spacing=spacing,
        scrollbar=scrollbar,
        scrollbar_hovered=scrollbar_hovered,
        copy_all_action=copy_all_action,
        copied_all=False,
    )

def context(*, height=12, width=100, density="normal", color=False, period=None, pending=False):
    return RenderContext(
        width,
        height,
        load_translator("en"),
        density=density,
        style="dot",
        color=color,
        period=period,
        pending=pending,
    )

def render(
    model,
    viewport,
    ctx=None,
    *,
    search="",
    spacing="compact",
    copied=None,
    scrollbar=False,
    scrollbar_hovered=False,
    copy_all_action=False,
    copied_all=False,
    search_editing=False,
):
    ctx = ctx or context()
    return render_custom_ranking_viewport(
        model,
        ctx,
        viewport,
        heading="Ranking",
        descriptions_visible=ctx.density in {"full", "detailed"},
        search_query=search,
        search_editing=search_editing,
        show_visible_count=True,
        copied_entry_id=copied,
        item_spacing=spacing,
        scrollbar=scrollbar,
        scrollbar_hovered=scrollbar_hovered,
        copy_all_action=copy_all_action,
        copied_all=copied_all,
    )

def _search_fact_projection() -> CustomChartProjection:
    def item(
        key: str,
        value: int,
        *,
        previous: int,
        description: str | None = None,
    ) -> CustomProjectedSeries:
        return CustomProjectedSeries(
            key,
            LocalizedText(key.title(), key),
            (Decimal(value),),
            previous_total=Decimal(previous),
            comparison_ready=True,
            description=LocalizedText(description, description) if description else None,
            link=f"https://example.com/{key}",
        )

    return replace(
        projection(0, comparison=True),
        series=(
            item("alpha", 50, previous=20),
            item("beta", 30, previous=60),
            item("claude", 20, previous=40, description="Release notes"),
        ),
        show_percentage=True,
    )

def _track(line: str, mark: str, empty: str) -> str:
    return next(part for part in line.split() if mark in part and set(part) <= {mark, empty})

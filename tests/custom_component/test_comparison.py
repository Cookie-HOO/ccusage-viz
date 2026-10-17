from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

import pytest

from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import (
    CustomCompletion,
    CustomHistoricalComponent,
)
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomData,
    CustomPoint,
    LocalizedText,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, Density
from ccusage_viz.processing.custom_historical import (
    CustomProjectionError,
    process_custom_historical,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_projection

from .helpers import _grouped_response, config, response


def test_custom_ranking_uses_capability_sort_direction_for_entries_and_prior_ranks() -> None:
    current = response((("older", "8"), ("recent", "2")))
    previous = response((("older", "1"), ("recent", "9")), point_date=date(2026, 8, 30))
    ascending = replace(
        current,
        capabilities=replace(
            current.capabilities,
            charts={
                **current.capabilities.charts,
                "ranking": replace(
                    current.capabilities.charts["ranking"], sort_direction="ascending"
                ),
            },
        ),
    )
    chart = config(kind="ranking")
    comparison_chart = replace(chart, date_range=DateRange(date(2026, 8, 30), date(2026, 8, 30)))

    projection = process_custom_historical(
        ascending, chart, comparison_response=previous, comparison_config=comparison_chart
    )

    assert [series.id for series in projection.series] == ["recent", "older"]
    assert [series.previous_rank for series in projection.series] == [2, 1]

def test_grouped_projection_period_all_retains_dated_totals_without_comparison() -> None:
    source = _grouped_response((("one", (("a", "2"),)),))
    group = source.data.groups[0]  # type: ignore[index]
    source = replace(
        source,
        data=CustomData(
            groups=(
                replace(
                    group,
                    series=(
                        replace(
                            group.series[0],
                            points=(
                                CustomPoint(date(2026, 9, 1), Decimal("2")),
                                CustomPoint(date(2026, 9, 2), Decimal("3")),
                            ),
                        ),
                    ),
                ),
            )
        ),
    )
    chart = config(
        kind="ranking",
        partition_by="logical_model",
        group_by="real_model",
        top=None,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2), period="all"),
    )

    projection = process_custom_historical(source, chart)

    assert projection.groups is not None
    assert projection.groups[0].series[0].values == (Decimal("2"), Decimal("3"))
    assert projection.groups[0].total == Decimal("5")
    assert not projection.comparison_available

@pytest.mark.parametrize("current_grouped", (False, True))
def test_ranking_rejects_incompatible_current_and_comparison_shapes(
    current_grouped: bool,
) -> None:
    flat = response((("a", "1"),))
    grouped = _grouped_response((("one", (("a", "1"),)),))
    current, previous = (grouped, flat) if current_grouped else (flat, grouped)
    chart = config(
        kind="ranking",
        partition_by="logical_model" if current_grouped else None,
        group_by="real_model" if current_grouped else "book",
        top=None,
    )
    comparison_chart = replace(
        chart,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
        partition_by=None if current_grouped else "logical_model",
        group_by="book" if current_grouped else "real_model",
    )

    with pytest.raises(CustomProjectionError, match="comparison shape"):
        process_custom_historical(
            current,
            chart,
            comparison_response=previous,
            comparison_config=comparison_chart,
        )

def test_comparison_response_is_validated_against_its_own_query_capability() -> None:
    current = response((("a", "1"),))
    previous = replace(
        response((("a", "2"),), point_date=date(2026, 8, 30)),
        capabilities=CustomCapabilities(
            (), (), {"ranking": CustomChartCapability(("day",), (None,), ())}
        ),
    )
    chart = config(kind="ranking", top=None)
    comparison_chart = replace(
        chart,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
    )

    with pytest.raises(CustomProjectionError, match="grouping by book"):
        process_custom_historical(
            current,
            chart,
            comparison_response=previous,
            comparison_config=comparison_chart,
        )

def test_custom_ranking_derives_decimal_comparison_facts_from_raw_responses() -> None:
    current = response((("api", "3"), ("app", "1")))
    previous = response((("api", "1"), ("app", "2"), ("batch", "4")), point_date=date(2026, 8, 30))
    comparison_config = replace(
        config(kind="ranking"), date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31))
    )

    projection = process_custom_historical(
        current,
        config(kind="ranking"),
        comparison_response=previous,
        comparison_config=comparison_config,
    )

    api, app = projection.series
    assert api.total == Decimal("3")
    assert api.previous_total == Decimal("1")
    assert api.previous_rank == 3
    assert api.comparison_ready
    assert app.previous_total == Decimal("2")
    assert app.previous_rank == 2

def test_custom_ranking_distinguishes_missing_comparison_response_from_new_series() -> None:
    current = response((("api", "3"), ("app", "2"), ("batch", "1")))
    current_config = config(
        kind="ranking",
        group_by=None,
        top=2,
        presentation=ChartPresentation(density="detailed", style="dot"),
    )
    previous = response((("api", "1"),), point_date=date(2026, 8, 30))
    comparison_config = replace(
        current_config,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
    )

    unavailable = process_custom_historical(current, current_config)
    partial = process_custom_historical(
        current,
        current_config,
        comparison_response=previous,
        comparison_config=comparison_config,
    )

    assert not unavailable.comparison_available
    assert all(not series.comparison_ready for series in unavailable.series)
    assert partial.comparison_available
    api, app, other = partial.series
    assert api.comparison_ready and api.previous_total == Decimal("1")
    assert not app.comparison_ready and app.previous_total is None
    assert not other.comparison_ready and other.previous_total is None

def test_custom_ranking_hides_unavailable_comparison_columns_and_labels_new_entries() -> None:
    current = response((("api", "3"), ("app", "2"), ("batch", "1")))
    current_config = config(
        kind="ranking",
        group_by=None,
        top=2,
        presentation=ChartPresentation(density="detailed", style="dot"),
    )
    previous = response((("api", "1"),), point_date=date(2026, 8, 30))
    comparison_config = replace(
        current_config,
        date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
    )
    context = RenderContext(
        110,
        20,
        load_translator("en"),
        color=False,
        density="detailed",
        style="dot",
        period="14d",
    )

    unavailable = render_custom_projection(
        process_custom_historical(current, current_config), context
    )
    partial = render_custom_projection(
        process_custom_historical(
            current,
            current_config,
            comparison_response=previous,
            comparison_config=comparison_config,
        ),
        context,
    )

    assert "vs prior" not in unavailable
    assert "Rank Δ" not in unavailable
    assert "vs prior 14d" in partial
    assert "New" in next(line for line in partial.splitlines() if "app" in line)
    assert "New in ranking" in next(line for line in partial.splitlines() if "app" in line)
    assert "New" not in next(line for line in partial.splitlines() if "Other" in line)

    chinese = render_custom_projection(
        process_custom_historical(
            current,
            current_config,
            comparison_response=previous,
            comparison_config=comparison_config,
        ),
        replace(context, translator=load_translator("zh")),
    )
    app_line = next(line for line in chinese.splitlines() if "app" in line)
    assert "新增" in app_line
    assert "新上榜" in app_line

def test_timestamp_comparison_is_contiguous_with_the_accepted_anchor() -> None:
    end = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    current = TimestampRange(end - timedelta(minutes=10), end, relative_until=True, period="10m")
    component = CustomHistoricalComponent(
        config(kind="ranking", metric_id="reading_time", date_range=current)
    )

    previous = component.comparison_request_config()

    assert previous is not None
    assert previous.date_range == TimestampRange(
        end - timedelta(minutes=20),
        end - timedelta(minutes=10),
        period="10m",
        fixed_bounds=True,
    )

def test_component_accepts_matching_comparison_without_replacing_current_projection() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response((("api", "3"), ("app", "1"))))
    comparison_config = component.start_comparison()
    assert comparison_config is not None
    previous = response(
        (("api", "1"), ("app", "2"), ("batch", "4")), point_date=comparison_config.date_range.since
    )

    assert component.accept_response(previous, purpose="comparison")

    assert component.model is not None
    api, app = component.model.series
    assert api.previous_total == Decimal("1")
    assert api.previous_rank == 3
    assert app.previous_total == Decimal("2")
    assert not component.comparison_is_pending

def test_component_rejects_stale_or_unrequested_comparison_response() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response())
    comparison_config = component.start_comparison()
    assert comparison_config is not None

    assert not component.apply_result(
        CustomCompletion(component.generation, component.candidate, response(), "comparison")
    )
    assert component.comparison_response is None

@pytest.mark.parametrize(
    ("density", "expected"),
    (("minimal", False), ("compact", False), ("full", True), ("detailed", True)),
)
def test_ranking_comparison_request_uses_complete_content_densities(
    density: str, expected: bool
) -> None:
    component = CustomHistoricalComponent(
        config(kind="ranking", presentation=ChartPresentation(density=cast(Density, density)))
    )

    request = component.comparison_request_config()

    assert (request is not None) is expected
    if request is not None:
        assert request.date_range.fixed_bounds

def test_ranking_all_period_never_requests_a_prior_range() -> None:
    component = CustomHistoricalComponent(
        replace(
            config(kind="ranking", presentation=ChartPresentation(density="detailed")),
            date_range=DateRange(
                date(1971, 1, 1), date(2026, 10, 9), relative_until=True, period="all"
            ),
        )
    )

    assert component.comparison_request_config() is None

@pytest.mark.parametrize(
    ("comparison", "expected"),
    (("full", True), ("rank", True), ("none", False)),
)
def test_ranking_comparison_capability_controls_prior_range_requests(
    comparison: str, expected: bool
) -> None:
    component = CustomHistoricalComponent(
        replace(
            config(kind="ranking", presentation=ChartPresentation(density="detailed")),
            ranking_comparison=cast(Literal["full", "rank", "none"], comparison),
        )
    )

    assert (component.comparison_request_config() is not None) is expected

def test_comparison_semantic_change_cancels_pending_and_rejects_completion_and_failure() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response())
    issued = component.start_comparison()
    assert issued is not None
    component.configure(replace(component.candidate, top=1), data_affecting=False)
    revision = component.render_revision

    assert not component.comparison_is_pending
    assert not component.apply_result(
        CustomCompletion(component.generation, issued, response(), "comparison")
    )
    error = RuntimeError("stale comparison failure")
    assert not component.fail(error, generation=component.generation, purpose="comparison")
    assert component.comparison_error is None
    assert component.comparison_response is None
    assert component.render_revision == revision

def test_comparison_disable_clears_existing_error_and_rejects_stale_failure() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response())
    assert component.start_comparison() is not None
    failure = RuntimeError("first failure")
    assert component.fail(failure, generation=component.generation, purpose="comparison")
    assert component.comparison_error is failure

    component.configure(
        replace(
            component.candidate,
            presentation=replace(component.candidate.presentation, density="minimal"),
        ),
        data_affecting=False,
    )

    assert component.comparison_error is None
    stale = RuntimeError("stale failure")
    assert not component.fail(stale, generation=component.generation, purpose="comparison")
    assert component.comparison_error is None

def test_accepted_comparison_detaches_and_reattaches_only_for_matching_request() -> None:
    component = CustomHistoricalComponent(config(kind="ranking"))
    assert component.accept_response(response((("api", "3"), ("app", "1"))))
    issued = component.start_comparison()
    assert issued is not None
    previous = response((("api", "1"), ("app", "2")), point_date=issued.date_range.since)
    assert component.apply_result(
        CustomCompletion(component.generation, issued, previous, "comparison")
    )
    accepted_comparison = component.comparison_response

    component.configure(
        replace(component.candidate, ranking_comparison="none"), data_affecting=False
    )

    assert component.comparison_response is accepted_comparison
    assert component.model is not None
    assert not component.model.comparison_available

    component.configure(
        replace(component.candidate, ranking_comparison="full"), data_affecting=False
    )

    assert component.comparison_response is accepted_comparison
    assert component.model is not None
    assert component.model.comparison_available

    component.configure(replace(component.candidate, top=1), data_affecting=False)
    assert component.comparison_response is accepted_comparison
    assert component.model is not None
    assert not component.model.comparison_available

def test_custom_ranking_prefers_dataset_owned_localized_comparison_display() -> None:
    current = response((("book", "10"),))
    previous = response((("book", "3"),), point_date=date(2026, 8, 30))
    current = replace(
        current,
        data=replace(
            current.data,
            series=(
                replace(
                    current.data.series[0],
                    comparison_display=LocalizedText("+7 chapters", "+7 章"),
                ),
            ),
        ),
    )
    projection = process_custom_historical(
        current,
        config(
            kind="ranking", group_by=None, top=None, presentation=ChartPresentation(style="dot")
        ),
        comparison_response=previous,
        comparison_config=replace(
            config(kind="ranking", group_by=None, top=None),
            date_range=DateRange(date(2026, 8, 30), date(2026, 8, 31)),
        ),
    )

    english = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("en"), color=False, style="dot")
    )
    chinese = render_custom_projection(
        projection, RenderContext(100, 20, load_translator("zh"), color=False, style="dot")
    )

    assert "+7 chapters" in english
    assert "+7 章" in chinese
